#!/usr/bin/env python3
"""Deterministic, stdlib-only provider quota monitor and launch guard."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import uuid
from urllib.request import Request, urlopen

STATES = {"GREEN", "AMBER", "RED", "UNKNOWN", "EXCLUDED"}
HEALTH = {"FRESH", "UNAVAILABLE", "STALE", "MALFORMED", "CONFIGURATION_INCOMPLETE", "EXCLUDED"}
TRUSTWORTHY_STATES = ("GREEN", "AMBER", "RED")
# Policy v1.1 separates a transient telemetry failure from persistent UNKNOWN/STALE.
# A failed probe denies new work at once; active work keeps following the last
# trustworthy reading until it ages past the central `monitoring.staleAfterSeconds`
# threshold, at which point the provider becomes fail-closed UNKNOWN/STALE.
TELEMETRY_FAILURE_ACTIVE_WORK = "retain_last_trustworthy_reading"
TELEMETRY_GRACE_PREFIX = "TELEMETRY_GRACE_"
DECISIONS = {"allow": "ALLOW", "defer": "DEFER", "deny": "DENY", "continue": "ALLOW", "finish_current": "FINISH_CURRENT", "checkpoint_stop": "CHECKPOINT_STOP"}
CLOUD = ("anthropic", "openai")
# The only Claude windows that are capacity inputs, and therefore the only ones a
# failed-probe diagnostic needs to describe.
CLAUDE_PLAN_WINDOWS = ("five_hour", "seven_day")
LOCAL_WORKER_AGENT_ID = "48ed952b-bcbe-4fa1-86e2-5048b76535ce"
CHECKPOINT_COLLECTOR_TIMEOUT_SECONDS = 60
CLAUDE_ENV_OVERRIDES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_MODEL", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECUTABLE", "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDECODE",
)

# Failed-probe diagnostics. A provider that returns no usable quota snapshot stays
# UNAVAILABLE/UNKNOWN; these fields only preserve enough structure to classify WHY
# the snapshot was unusable. Nothing here is a capacity input, and nothing here may
# carry the raw provider response, credentials, or authentication material.
STDERR_READ_CHUNK_SIZE = 256  # characters requested from stderr at a time
STDERR_CAPTURE_LIMIT = 8192  # raw characters retained while the rest of stderr is drained and discarded
STDERR_DIAGNOSTIC_LIMIT = 1024  # characters retained after redaction
MESSAGE_DIAGNOSTIC_LIMIT = 200  # characters retained from a provider-supplied failure classification
CONTROL_RESPONSE_SUBTYPES_LIMIT = 20  # unique first-seen subtype labels retained for diagnostics
# Stderr is read in bounded chunks, reassembled only up to STDERR_CAPTURE_LIMIT,
# and redacted as one bounded value. If the raw prefix reaches that limit, its
# incomplete trailing lexical span is removed before pattern matching so a
# credential crossing the capture boundary cannot survive as a fragment.
REDACTIONS = (
    (re.compile(r"(?i)\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}"), "<redacted-key>"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)?"), "<redacted-jwt>"),
    (re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), "<redacted-authorization>"),
    (
        # `(?:\b|_)` rather than `\b`: the credential names most likely to reach a
        # probe's stderr are underscored environment variables such as
        # `CLAUDE_CODE_MESSAGING_TOKEN=...`, where no word boundary precedes the
        # keyword. The separator must still be `:`/`=`, so a path like
        # `.claude\auth.json: ENOENT` stays readable.
        re.compile(
            r"(?i)(?:\b|_)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|passwd|authorization|auth|cookie|credential|session[_-]?key)"
            r"[\"']?\s*[:=]\s*[\"']?[^\s,;\"'}\]]+"
        ),
        "<redacted-credential>",
    ),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<redacted-email>"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<redacted-hex>"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}"), "<redacted-blob>"),
)

STDERR_CAPTURE_BOUNDARY_REPLACEMENT = "<redacted-boundary-fragment>"
STDERR_CAPTURE_BOUNDARY_DELIMITERS = frozenset(",;\"'}]")

# Probe-outcome journal. Diagnostics only: nothing written here is read back as a
# capacity input, by any decision path, or by the launch guard. It exists because
# `state.json` is replaced every cycle, so a failed probe's diagnostics survive
# roughly one poll interval and cannot explain an incident reviewed hours later.
# The journal changes no threshold, no interval, and no fail-closed transition.
JOURNAL_FILENAME = "probe-outcomes.jsonl"
JOURNAL_MAX_BYTES = 1_048_576  # same bound and single-generation policy as monitor.log
JOURNAL_PROBE_RECORD = "probe"
JOURNAL_CYCLE_RECORD = "cycle"
JOURNAL_DIAGNOSTIC_DEPTH = 3  # nesting walked before a value is reduced to its shape


def probe_process_options() -> dict[str, int]:
    """Return platform-specific options that keep telemetry probes windowless."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _redact_credentials(text: str) -> str:
    value = text
    for pattern, replacement in REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def _redact_capture_boundary(text: str) -> str:
    """Remove the possibly incomplete lexical span at a full capture boundary.

    Every credential pattern's sensitive value is terminated by whitespace or
    one of these delimiters. If the retained raw prefix ends elsewhere, the
    entire trailing span is ambiguous and is conservatively replaced before the
    regular-expression redactor sees it.
    """
    start = len(text)
    while (
        start > 0
        and not text[start - 1].isspace()
        and text[start - 1] not in STDERR_CAPTURE_BOUNDARY_DELIMITERS
    ):
        start -= 1
    if start == len(text):
        return text
    prefix_limit = STDERR_CAPTURE_LIMIT - len(STDERR_CAPTURE_BOUNDARY_REPLACEMENT)
    safe_end = min(start, prefix_limit)
    while (
        safe_end > 0
        and not text[safe_end - 1].isspace()
        and text[safe_end - 1] not in STDERR_CAPTURE_BOUNDARY_DELIMITERS
    ):
        safe_end -= 1
    return text[:safe_end] + STDERR_CAPTURE_BOUNDARY_REPLACEMENT


def redact(text: Any) -> str | None:
    """Redact credential-shaped material from a diagnostic string.

    Applied to every free-text diagnostic before it reaches state on disk. The
    caller applies its relevant bound only after this transformation.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    return _redact_credentials(text).strip()


def bounded(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def structural_kind(container: Any, key: str) -> str:
    """Name the shape of ``container[key]`` without retaining its value."""
    if not isinstance(container, dict) or key not in container:
        return "absent"
    value = container[key]
    if value is None:
        return "null"
    for kind, types in (("boolean", bool), ("object", dict), ("array", list), ("string", str), ("number", (int, float))):
        if isinstance(value, types):
            return kind
    return "invalid"


def safe_scalar(value: Any) -> Any:
    """Keep a diagnostic value verbatim only when it is a non-sensitive scalar."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return structural_kind({"value": value}, "value")


def checkpoint_interruption_id(company_id: str, provider: str, agent_id: str, runs: list[dict[str, str]]) -> str:
    identities = sorted({f"{item['taskId']}:{item['runId']}" for item in runs})
    material = "\n".join(["quota-pause-v1", company_id, provider, agent_id, *identities])
    return "quota-pause-v1-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class QuotaError(Exception):
    def __init__(self, code: str, message: str, health: str = "UNAVAILABLE", diagnostic: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.health = code, health
        # Structural, bounded, redacted evidence about why the probe produced no
        # usable snapshot. Never a capacity input and never the raw response.
        self.diagnostic = diagnostic

    def with_diagnostic(self, extra: dict[str, Any]) -> "QuotaError":
        self.diagnostic = {**(self.diagnostic or {}), **extra}
        return self


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def missing_policy_values(policy: Any) -> list[str]:
    def number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> bool:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        return valid and (not positive or value > 0) and (not nonnegative or value >= 0)

    missing: list[str] = []
    if not isinstance(policy, dict):
        return ["$"]
    required = ("schemaVersion", "configurationVersion", "companyId", "monitoring", "paperclip", "providers", "behaviors", "runtimeControl")
    for key in required:
        if key not in policy:
            missing.append(key)
    if missing:
        return missing
    if policy.get("schemaVersion") != 1:
        missing.append("schemaVersion")
    if not policy.get("configurationVersion") or str(policy.get("configurationVersion")).upper() == "TBD":
        missing.append("configurationVersion")
    for key in ("enabled", "pollIntervalSeconds", "staleAfterSeconds"):
        if policy.get("monitoring", {}).get(key) is None:
            missing.append(f"monitoring.{key}")
    if policy.get("monitoring", {}).get("enabled") not in (True, False, None):
        missing.append("monitoring.enabled")
    for key in ("pollIntervalSeconds", "staleAfterSeconds"):
        value = policy.get("monitoring", {}).get(key)
        if value is not None and not number(value, positive=True):
            missing.append(f"monitoring.{key}")
    if not policy.get("paperclip", {}).get("baseUrl"):
        missing.append("paperclip.baseUrl")
    if not policy.get("paperclip", {}).get("activeRunsPath"):
        missing.append("paperclip.activeRunsPath")
    if policy.get("paperclip", {}).get("activeRunsTimeoutSeconds") is None:
        missing.append("paperclip.activeRunsTimeoutSeconds")
    elif not number(policy["paperclip"]["activeRunsTimeoutSeconds"], positive=True):
        missing.append("paperclip.activeRunsTimeoutSeconds")
    page_size = policy.get("paperclip", {}).get("activeRunsPageSize")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 1000:
        missing.append("paperclip.activeRunsPageSize")
    for provider in CLOUD:
        config = policy.get("providers", {}).get(provider)
        if not isinstance(config, dict):
            missing.append(f"providers.{provider}")
            continue
        if config.get("applicable") is None:
            missing.append(f"providers.{provider}.applicable")
        elif config.get("applicable") not in (True, False):
            missing.append(f"providers.{provider}.applicable")
        if config.get("applicable") is False:
            continue
        for key in ("poolId",):
            if not config.get(key):
                missing.append(f"providers.{provider}.{key}")
        source = config.get("source", {})
        for key in ("kind", "command", "profileDirectory", "timeoutSeconds"):
            if source.get(key) is None or source.get(key) == "":
                missing.append(f"providers.{provider}.source.{key}")
        expected_kind = "claude_stream_json_get_usage" if provider == "anthropic" else "codex_app_server_rate_limits"
        if source.get("kind") != expected_kind:
            missing.append(f"providers.{provider}.source.kind")
        if source.get("timeoutSeconds") is not None and not number(source["timeoutSeconds"], positive=True):
            missing.append(f"providers.{provider}.source.timeoutSeconds")
        thresholds = config.get("thresholds")
        if not isinstance(thresholds, dict) or not thresholds:
            missing.append(f"providers.{provider}.thresholds")
        else:
            expected_windows = {"five_hour", "seven_day"} if provider == "anthropic" else {"primary", "secondary"}
            if set(thresholds) != expected_windows:
                missing.append(f"providers.{provider}.thresholds.windows")
            for window, threshold in thresholds.items():
                for key in ("metric", "amberAtOrAbove", "redAtOrAbove", "reserve"):
                    if threshold.get(key) is None:
                        missing.append(f"providers.{provider}.thresholds.{window}.{key}")
                for key in ("amberAtOrAbove", "redAtOrAbove"):
                    if threshold.get(key) is not None and not number(threshold[key]):
                        missing.append(f"providers.{provider}.thresholds.{window}.{key}")
                if threshold.get("reserve") is not None and not number(threshold["reserve"], nonnegative=True):
                    missing.append(f"providers.{provider}.thresholds.{window}.reserve")
                if number(threshold.get("amberAtOrAbove")) and number(threshold.get("redAtOrAbove")) and threshold["amberAtOrAbove"] > threshold["redAtOrAbove"]:
                    missing.append(f"providers.{provider}.thresholds.{window}.ordering")
        concurrency = config.get("concurrency", {})
        if concurrency.get("enabled") is None:
            missing.append(f"providers.{provider}.concurrency.enabled")
        elif concurrency.get("enabled"):
            for key in ("strategy", "adjustmentPerAdditionalConsumer"):
                if concurrency.get(key) is None:
                    missing.append(f"providers.{provider}.concurrency.{key}")
            if concurrency.get("strategy") not in (None, "add_to_observed_metric"):
                missing.append(f"providers.{provider}.concurrency.strategy")
            adjustment = concurrency.get("adjustmentPerAdditionalConsumer")
            if adjustment is not None and not number(adjustment, nonnegative=True):
                missing.append(f"providers.{provider}.concurrency.adjustmentPerAdditionalConsumer")
    anthropic_adapters = set(policy.get("providers", {}).get("anthropic", {}).get("adapterTypes", []))
    openai_adapters = set(policy.get("providers", {}).get("openai", {}).get("adapterTypes", []))
    if anthropic_adapters & openai_adapters:
        missing.append("providers.adapterTypes.poolOverlap")
    for state in ("amber", "red", "unknown"):
        for work in ("newWork", "activeWork"):
            if policy.get("behaviors", {}).get(state, {}).get(work) is None:
                missing.append(f"behaviors.{state}.{work}")
    for work in ("newWork", "activeWork"):
        if policy.get("behaviors", {}).get("telemetryFailure", {}).get(work) is None:
            missing.append(f"behaviors.telemetryFailure.{work}")
    if policy.get("behaviors", {}).get("unknown") != {"newWork": "deny", "activeWork": "checkpoint_stop"}:
        missing.append("behaviors.unknown.failClosedInvariant")
    if policy.get("behaviors", {}).get("telemetryFailure") != {"newWork": "deny", "activeWork": TELEMETRY_FAILURE_ACTIVE_WORK}:
        missing.append("behaviors.telemetryFailure.failClosedInvariant")
    if policy.get("behaviors", {}).get("amber", {}).get("newWork") not in (None, "defer", "deny"):
        missing.append("behaviors.amber.newWork")
    if policy.get("behaviors", {}).get("red", {}).get("newWork") not in (None, "deny"):
        missing.append("behaviors.red.newWork")
    if policy.get("behaviors", {}).get("red", {}).get("activeWork") not in (None, "checkpoint_stop"):
        missing.append("behaviors.red.activeWork")
    control = policy.get("runtimeControl", {})
    for key in ("enabled", "mechanism", "pauseAgentPath", "requestTimeoutSeconds"):
        if control.get(key) is None or control.get(key) == "":
            missing.append(f"runtimeControl.{key}")
    if control.get("enabled") not in (True, False, None):
        missing.append("runtimeControl.enabled")
    if control.get("mechanism") not in (None, "paperclip_agent_pause"):
        missing.append("runtimeControl.mechanism")
    timeout = control.get("requestTimeoutSeconds")
    if timeout is not None and not number(timeout, positive=True):
        missing.append("runtimeControl.requestTimeoutSeconds")
    actions = control.get("actions", {})
    for state in ("amber", "red", "unknown"):
        if actions.get(state) is None:
            missing.append(f"runtimeControl.actions.{state}")
    if actions.get("amber") not in (None, "none", "pause_agents"):
        missing.append("runtimeControl.actions.amber")
    for state in ("red", "unknown"):
        if actions.get(state) not in (None, "pause_agents"):
            missing.append(f"runtimeControl.actions.{state}")
    behavior_to_control = {"finish_current": "none", "checkpoint_stop": "pause_agents"}
    for state in ("amber", "red", "unknown"):
        active_behavior = policy.get("behaviors", {}).get(state, {}).get("activeWork")
        if active_behavior in behavior_to_control and actions.get(state) not in (None, behavior_to_control[active_behavior]):
            missing.append(f"runtimeControl.actions.{state}.behaviorAlignment")
    return sorted(set(missing))


def claude_failure_classification(item: Any) -> str | None:
    """A provider-supplied failure label from a non-success control response."""
    response = item.get("response") if isinstance(item, dict) else None
    if not isinstance(response, dict):
        return None
    error = response.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("code") or error.get("type")
    return bounded(redact(error), MESSAGE_DIAGNOSTIC_LIMIT)


def parse_claude_output(text: str) -> dict[str, Any]:
    response = None
    # Transport-shape evidence, collected on the way through so a failure can be
    # classified later without re-probing. Counts and subtypes only.
    seen = {"jsonLines": 0, "controlResponses": 0}
    subtypes: list[str] = []
    classification = None
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        seen["jsonLines"] += 1
        if not isinstance(item, dict) or item.get("type") != "control_response":
            continue
        seen["controlResponses"] += 1
        subtype = item.get("response", {}).get("subtype") if isinstance(item.get("response"), dict) else None
        if (
            isinstance(subtype, str)
            and subtype not in subtypes
            and len(subtypes) < CONTROL_RESPONSE_SUBTYPES_LIMIT
        ):
            subtypes.append(subtype)
        if subtype == "success":
            response = item["response"].get("response") or item["response"].get("data") or item["response"]
            break
        classification = classification or claude_failure_classification(item)
    if not isinstance(response, dict):
        raise QuotaError("CLAUDE_RESPONSE_MISSING", "No successful get_usage control response", "MALFORMED", {
            **seen,
            "controlResponseSubtypes": [bounded(redact(value), MESSAGE_DIAGNOSTIC_LIMIT) for value in subtypes],
            "failureClassification": classification,
            "successResponseKind": structural_kind({"response": response}, "response"),
        })
    available = response.get("rate_limits_available")
    limits = response.get("rate_limits")
    structure = {
        "rateLimitsAvailable": safe_scalar(available),
        "rateLimitsKind": structural_kind(response, "rate_limits"),
    }
    if available is not True or not isinstance(limits, dict):
        # The observed AXI-52 failure shape is `rate_limits_available: true` with
        # `rate_limits: null`. It is recorded, never read as capacity.
        raise QuotaError("CLAUDE_LIMITS_UNAVAILABLE", "Claude rate limits were not available", diagnostic=structure)
    windows = []
    # Only subscription plan windows are capacity inputs. Extra usage, purchased
    # credits, promotional/banked pools, and provider-added windows are ignored.
    for name in CLAUDE_PLAN_WINDOWS:
        item = limits.get(name)
        if not isinstance(item, dict) or item.get("utilization") is None:
            continue
        windows.append({
            "id": name,
            "metric": "used_percent",
            "value": float(item["utilization"]),
            "resetsAt": item.get("resets_at"),
        })
    if not windows:
        raise QuotaError("CLAUDE_WINDOWS_MALFORMED", "Claude returned no usable quota windows", "MALFORMED", {
            **structure,
            "planWindows": {name: structural_kind(limits, name) for name in CLAUDE_PLAN_WINDOWS},
            "planWindowUtilization": {
                name: structural_kind(limits[name], "utilization")
                for name in CLAUDE_PLAN_WINDOWS if isinstance(limits.get(name), dict)
            },
        })
    return {"sourceKind": "claude_stream_json_get_usage", "subscriptionType": response.get("subscription_type"), "windows": windows}


def parse_codex_output(text: str) -> dict[str, Any]:
    payload = None
    account = None
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        if "rateLimitsByLimitId" in result or "rateLimits" in result or "ordinaryUsageAllowed" in result:
            payload = result
        if "account" in result:
            account = result.get("account")
    if not isinstance(payload, dict):
        raise QuotaError("CODEX_RESPONSE_MISSING", "No account/rateLimits/read result", "MALFORMED")
    if payload.get("ordinaryUsageAllowed") is False:
        return {"sourceKind": "codex_app_server_rate_limits", "ordinaryUsageAllowed": False, "account": account, "windows": []}
    if payload.get("ordinaryUsageAllowed") is not True:
        raise QuotaError("CODEX_USAGE_PERMISSION_UNKNOWN", "Codex ordinaryUsageAllowed was null or missing")
    limits = payload.get("rateLimits")
    if not isinstance(limits, dict):
        by_id = payload.get("rateLimitsByLimitId")
        if isinstance(by_id, dict) and by_id:
            limits = next(iter(by_id.values()))
    if not isinstance(limits, dict):
        raise QuotaError("CODEX_LIMITS_UNAVAILABLE", "Codex rate limits were not available")
    windows = []
    for name in ("primary", "secondary"):
        item = limits.get(name)
        if item is None:
            continue
        if not isinstance(item, dict) or item.get("usedPercent") is None:
            raise QuotaError("CODEX_WINDOW_MALFORMED", f"Codex {name} window is malformed", "MALFORMED")
        windows.append({
            "id": name,
            "metric": "used_percent",
            "value": float(item["usedPercent"]),
            "resetsAt": item.get("resetsAt"),
            "windowDurationMins": item.get("windowDurationMins"),
        })
    if not windows:
        raise QuotaError("CODEX_WINDOWS_MALFORMED", "Codex returned no usable quota windows", "MALFORMED")
    safe_account = {
        "accountId": payload.get("accountId"),
        "planType": payload.get("planType") or (account.get("planType") if isinstance(account, dict) else None),
        "type": account.get("type") if isinstance(account, dict) else None,
    }
    return {"sourceKind": "codex_app_server_rate_limits", "ordinaryUsageAllowed": payload.get("ordinaryUsageAllowed"), "account": safe_account, "windows": windows}


def run_probe(provider: str, config: dict[str, Any]) -> dict[str, Any]:
    source = config["source"]
    env = os.environ.copy()
    profile = source["profileDirectory"]
    if provider == "anthropic":
        for name in CLAUDE_ENV_OVERRIDES:
            env.pop(name, None)
        env["CLAUDE_CONFIG_DIR"] = profile
        request = {"type": "control_request", "request_id": "quota-manager-get-usage", "request": {"subtype": "get_usage", "skip_behaviors": True}}
        command = [source["command"], "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        parser = parse_claude_output
    else:
        env["CODEX_HOME"] = profile
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "paperclip-quota-manager", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "account/read", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {"skipResetCreditsDetail": True}},
        ]
        request = messages
        command = [source["command"], "-s", "read-only", "-a", "never", "app-server", "--stdio"]
        parser = parse_codex_output
    requests = request if isinstance(request, list) else [request]
    try:
        # stderr is captured, not inherited or discarded, so a failed usage fetch can
        # be classified afterwards. It is drained on its own thread and hard-capped:
        # the reader below must never stall because the child filled a pipe buffer.
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **probe_process_options(),
        )
    except OSError as exc:
        raise QuotaError("PROBE_EXECUTION_FAILED", type(exc).__name__, diagnostic={
            "failureClass": type(exc).__name__, "errno": exc.errno,
        }) from exc
    timed_out = False
    matched = False
    captured: list[str] = []
    capture_lock = threading.Lock()
    capture_boundary_reached = False
    capture_closed = False
    def drain() -> None:
        nonlocal capture_boundary_reached
        held = 0
        try:
            while True:
                chunk = process.stderr.read(STDERR_READ_CHUNK_SIZE)  # type: ignore[union-attr]
                if not chunk:
                    break
                with capture_lock:
                    if capture_closed:
                        continue
                    remaining = STDERR_CAPTURE_LIMIT - held
                    if remaining > 0:
                        retained = chunk[:remaining]
                        captured.append(retained)
                        held += len(retained)
                    # Treat an exactly full prefix conservatively: until EOF has
                    # been observed, its trailing span may be only a credential
                    # fragment. Raw stderr continues to be drained below.
                    if held >= STDERR_CAPTURE_LIMIT or len(chunk) > remaining:
                        capture_boundary_reached = True
        except (OSError, ValueError):
            # A read failure can leave the bounded prefix at an arbitrary point
            # inside a credential, so its trailing span must not be trusted.
            with capture_lock:
                capture_boundary_reached = True
    reader = None
    if getattr(process, "stderr", None) is not None:
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
    def expire() -> None:
        nonlocal timed_out
        timed_out = True
        process.kill()
    timer = threading.Timer(source["timeoutSeconds"], expire)
    lines: list[str] = []
    try:
        timer.start()
        assert process.stdin is not None and process.stdout is not None
        for item in requests:
            process.stdin.write(json.dumps(item) + "\n")
        process.stdin.flush()  # Deliberately leave stdin open; both control protocols are session-oriented.
        for line in process.stdout:
            lines.append(line)
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if provider == "anthropic" and message.get("type") == "control_response" and message.get("response", {}).get("request_id") == "quota-manager-get-usage":
                matched = True
                break
            if provider == "openai" and message.get("id") == 2:
                matched = True
                break
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        if reader is not None:
            reader.join(timeout=1)
            if reader.is_alive():
                # Freeze the bounded snapshot if an inherited/stuck pipe prevents
                # EOF after the child exits. The ambiguous tail is treated exactly
                # like a reached capture boundary.
                with capture_lock:
                    capture_closed = True
                    capture_boundary_reached = True
    with capture_lock:
        captured_stderr = "".join(captured)
        capture_was_truncated = capture_boundary_reached
    if capture_was_truncated:
        captured_stderr = _redact_capture_boundary(captured_stderr)
    transport = {"exitCode": process.returncode, "stderr": bounded(redact(captured_stderr), STDERR_DIAGNOSTIC_LIMIT)}
    if timed_out:
        raise QuotaError("PROBE_TIMEOUT", "Provider probe timed out", diagnostic=transport)
    if not matched and process.returncode:
        raise QuotaError("PROBE_NONZERO_EXIT", f"Provider probe exited {process.returncode}", diagnostic=transport)
    try:
        return parser("".join(lines))
    except QuotaError as exc:
        # A parse failure is the case most in need of transport context: the probe
        # spoke, so the reason the snapshot was unusable is in the shape it returned
        # plus whatever the CLI reported on stderr.
        raise exc.with_diagnostic(transport)


def fetch_active_consumers(policy: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    base = policy["paperclip"]["baseUrl"].rstrip("/")
    page_size = policy["paperclip"]["activeRunsPageSize"]
    path = policy["paperclip"]["activeRunsPath"].format(companyId=policy["companyId"], limit=page_size)
    try:
        with urlopen(Request(base + path, headers={"Accept": "application/json"}), timeout=policy["paperclip"]["activeRunsTimeoutSeconds"]) as response:
            runs = json.load(response)
    except Exception as exc:
        raise QuotaError("ACTIVE_RUNS_UNAVAILABLE", type(exc).__name__) from exc
    if not isinstance(runs, list):
        raise QuotaError("ACTIVE_RUNS_MALFORMED", "Paperclip active-runs response is not an array", "MALFORMED")
    if len(runs) >= page_size:
        raise QuotaError("ACTIVE_RUNS_TRUNCATED", "Paperclip active-run result reached its configured page size")
    output = {provider: [] for provider in CLOUD}
    for run in runs:
        if not isinstance(run, dict) or run.get("status") not in ("queued", "running"):
            continue
        for provider in CLOUD:
            adapters = policy["providers"][provider].get("adapterTypes", [])
            if run.get("adapterType") in adapters:
                if not isinstance(run.get("id"), str) or not run["id"] or not isinstance(run.get("agentId"), str) or not run["agentId"]:
                    raise QuotaError("ACTIVE_RUN_IDENTITY_MALFORMED", "Cloud active run is missing a run or agent identifier", "MALFORMED")
                task_id = run.get("issueId")
                output[provider].append({"runId": run.get("id"), "taskId": task_id if isinstance(task_id, str) and task_id else None, "agentId": run.get("agentId"), "agentName": run.get("agentName"), "status": run.get("status")})
    return output


def classify(signal: dict[str, Any], config: dict[str, Any], consumer_count: int) -> tuple[str, list[dict[str, Any]]]:
    if signal.get("ordinaryUsageAllowed") is False:
        return "RED", []
    windows_by_id = {window["id"]: window for window in signal.get("windows", [])}
    evaluated = []
    state = "GREEN"
    concurrency = config["concurrency"]
    extra = max(0, consumer_count - 1)
    adjustment = extra * concurrency["adjustmentPerAdditionalConsumer"] if concurrency["enabled"] else 0
    for window_id, threshold in config["thresholds"].items():
        window = windows_by_id.get(window_id)
        if not window or window.get("metric") != threshold["metric"]:
            raise QuotaError("REQUIRED_WINDOW_MISSING", f"Required window {window_id!r} missing or metric differs", "MALFORMED")
        effective = window["value"] + threshold["reserve"] + adjustment
        window_state = "RED" if effective >= threshold["redAtOrAbove"] else "AMBER" if effective >= threshold["amberAtOrAbove"] else "GREEN"
        if window_state == "RED" or (window_state == "AMBER" and state == "GREEN"):
            state = window_state
        evaluated.append({
            "id": window_id,
            "metric": window["metric"],
            "observedValue": window["value"],
            "effectiveValue": effective,
            "resetsAt": window.get("resetsAt"),
            "windowDurationMins": window.get("windowDurationMins"),
            "amberAtOrAbove": threshold["amberAtOrAbove"],
            "redAtOrAbove": threshold["redAtOrAbove"],
            "reserve": threshold["reserve"],
            "concurrencyAdjustment": adjustment,
            "state": window_state,
        })
    for window in evaluated:
        window["determinesProviderState"] = window["state"] == state
    return state, evaluated


def causing_window_ids(signal: Any) -> list[str]:
    windows = signal.get("windows", []) if isinstance(signal, dict) else []
    return [window.get("id") for window in windows if isinstance(window, dict) and window.get("determinesProviderState") is True]


def trustworthy_reading(record: Any) -> dict[str, Any] | None:
    """The last provider reading this record is still entitled to trust, or None.

    A record written by a successful probe is its own trustworthy reading. A record
    written by a failed probe carries the retained one forward under ``telemetry``,
    so consecutive failures keep measuring age from the original observation rather
    than restarting the clock on every retry.
    """
    if not isinstance(record, dict):
        return None
    telemetry = record.get("telemetry")
    if isinstance(telemetry, dict) and telemetry.get("lastTrustworthyAt") and telemetry.get("lastTrustworthyState") in TRUSTWORTHY_STATES:
        return {
            "at": telemetry["lastTrustworthyAt"],
            "state": telemetry["lastTrustworthyState"],
            "causingWindows": list(telemetry.get("lastTrustworthyCausingWindows") or []),
        }
    if record.get("health") == "FRESH" and record.get("observedAt") and record.get("state") in TRUSTWORTHY_STATES:
        return {"at": record["observedAt"], "state": record["state"], "causingWindows": causing_window_ids(record.get("signal"))}
    return None


def telemetry_record(now: dt.datetime, health: str, reading: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "probedAt": iso(now),
        "health": health,
        "lastTrustworthyAt": reading["at"] if reading else None,
        "lastTrustworthyState": reading["state"] if reading else None,
        "lastTrustworthyCausingWindows": reading["causingWindows"] if reading else [],
    }


def retained_reading(policy: dict[str, Any], previous: Any, provider: str) -> dict[str, Any] | None:
    """Carry a trustworthy reading across a poll only when its provenance still holds."""
    if not isinstance(previous, dict):
        return None
    if previous.get("companyId") != policy.get("companyId") or previous.get("configurationVersion") != policy.get("configurationVersion"):
        return None
    return trustworthy_reading(previous.get("providers", {}).get(provider))


def incomplete_state(policy: dict[str, Any], missing: list[str], now: dt.datetime) -> dict[str, Any]:
    providers = {}
    for provider in CLOUD:
        providers[provider] = {
            "applicable": policy.get("providers", {}).get(provider, {}).get("applicable"),
            "poolId": policy.get("providers", {}).get(provider, {}).get("poolId"),
            "observedAt": None, "health": "CONFIGURATION_INCOMPLETE", "state": "UNKNOWN",
            "signal": None, "activeConsumers": [], "error": {"code": "POLICY_INCOMPLETE", "fields": missing},
            # An incomplete or disabled configuration is not a transient telemetry
            # failure, so it is granted no retained reading and no grace window.
            "telemetry": telemetry_record(now, "CONFIGURATION_INCOMPLETE", None),
        }
    providers["ollama"] = {"applicable": False, "health": "EXCLUDED", "state": "EXCLUDED"}
    return {"schemaVersion": 1, "companyId": policy.get("companyId"), "configurationVersion": policy.get("configurationVersion"), "generatedAt": iso(now), "providers": providers}


def rotate_journal(path: Path, max_bytes: int = JOURNAL_MAX_BYTES) -> None:
    """Keep one previous journal so a sustained failure loop cannot fill the disk.

    Mirrors ``monitor-service.rotate_log``: the same 1 MiB bound and the same
    single-generation policy, applied to the file the monitor appends to.
    """
    try:
        if path.is_file() and path.stat().st_size > max_bytes:
            previous = path.with_name(path.name + ".1")
            previous.unlink(missing_ok=True)
            path.replace(previous)
    except OSError:
        # Journalling must never prevent the monitor from completing a cycle.
        pass


def journal_diagnostic(value: Any, depth: int = 0) -> Any:
    """Copy a failed-probe diagnostic into the journal through the same boundary.

    Every value here was already redacted and bounded when the probe raised, so
    this re-applies that boundary rather than widening it: free text goes through
    ``redact()``/``bounded()`` again, scalars through ``safe_scalar()``, and
    anything deeper than ``JOURNAL_DIAGNOSTIC_DEPTH`` is reduced to its shape.
    Re-redaction is safe because no replacement marker matches a redaction
    pattern, so the journal copy cannot differ from the state copy by more than
    a further truncation.
    """
    if isinstance(value, str):
        return bounded(redact(value), STDERR_DIAGNOSTIC_LIMIT)
    if depth < JOURNAL_DIAGNOSTIC_DEPTH:
        if isinstance(value, dict):
            return {str(key): journal_diagnostic(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [journal_diagnostic(item, depth + 1) for item in value[:CONTROL_RESPONSE_SUBTYPES_LIMIT]]
    return safe_scalar(value)


def grace_age_seconds(record: Any, now: dt.datetime) -> float | None:
    """Age of the reading this provider is still entitled to trust, in seconds.

    This is the quantity the central ``monitoring.staleAfterSeconds`` threshold is
    compared against, recorded so an incident shows how close each cycle came to
    the fail-closed transition. It is reported, never enforced, here.
    """
    telemetry = record.get("telemetry") if isinstance(record, dict) else None
    at = telemetry.get("lastTrustworthyAt") if isinstance(telemetry, dict) else None
    if not isinstance(at, str) or not at:
        return None
    try:
        return round((now - parse_time(at)).total_seconds(), 3)
    except ValueError:
        return None


class ProbeJournal:
    """Append-only, rotation-bounded journal of per-cycle probe outcomes.

    Each completed cycle writes one ``probe`` record per applicable provider and
    one ``cycle`` heartbeat record. A monitor that stops being scheduled therefore
    shows up as *absent* ``cycle`` records, which a completed-but-failed probe
    never produces; that is what makes a scheduling stall distinguishable from a
    probe failure after the fact.

    Writing is best-effort by design. The journal is diagnostic, so a failed
    append increments ``write_errors`` and is otherwise ignored: it must never
    change an observation, a decision, or the monitor's liveness.

    ``consecutiveFailureCount`` is process-local. A monitor restart resets it to
    zero mid-run; the ``pid`` on each heartbeat is what lets a reader see that a
    restart, rather than a recovery, ended a failure run.
    """

    def __init__(self, path: Path | str, max_bytes: int = JOURNAL_MAX_BYTES) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.consecutive_failures: dict[str, int] = {}
        self.write_errors = 0

    def append(self, record: dict[str, Any]) -> None:
        try:
            rotate_journal(self.path, self.max_bytes)
            append_jsonl(self.path, record)
        except OSError:
            self.write_errors += 1

    def probe_record(self, provider: str, record: dict[str, Any], timing: dict[str, Any], now: dt.datetime, generated_at: Any) -> dict[str, Any]:
        health = record.get("health")
        # Counts consecutive non-FRESH outcomes. A configuration-incomplete cycle
        # is also non-FRESH but ran no probe, which `probeInvoked` keeps visible.
        count = self.consecutive_failures.get(provider, 0) + 1 if health != "FRESH" else 0
        self.consecutive_failures[provider] = count
        error = record.get("error") if isinstance(record.get("error"), dict) else None
        consumers = record.get("activeConsumers")
        return {
            "record": JOURNAL_PROBE_RECORD,
            "schemaVersion": 1,
            "generatedAt": generated_at,
            "observedAt": record.get("observedAt"),
            "provider": provider,
            "health": health,
            "state": record.get("state"),
            "error": None if error is None else {
                "code": error.get("code"),
                "diagnostic": journal_diagnostic(error.get("diagnostic")) if error.get("diagnostic") is not None else None,
            },
            "probeInvoked": bool(timing),
            "probeStartedAt": timing.get("startedAt"),
            "probeDurationMs": timing.get("durationMs"),
            "consecutiveFailureCount": count,
            "graceAgeSeconds": grace_age_seconds(record, now),
            "activeConsumerCount": len(consumers) if isinstance(consumers, list) else None,
        }

    def record_cycle(self, now: dt.datetime, state: dict[str, Any], timings: dict[str, dict[str, Any]]) -> None:
        generated_at = state.get("generatedAt")
        providers = state.get("providers")
        providers = providers if isinstance(providers, dict) else {}
        outcomes: dict[str, Any] = {}
        for provider in CLOUD:
            record = providers.get(provider)
            if not isinstance(record, dict) or not record.get("applicable"):
                self.consecutive_failures.pop(provider, None)
                continue
            outcome = self.probe_record(provider, record, timings.get(provider) or {}, now, generated_at)
            self.append(outcome)
            outcomes[provider] = outcome["health"]
        self.append({
            "record": JOURNAL_CYCLE_RECORD,
            "schemaVersion": 1,
            "generatedAt": generated_at,
            "completedAt": iso(now),
            "pid": os.getpid(),
            "providers": outcomes,
            "probesInvoked": sorted(timings),
        })


def journalled(journal: Any, now: dt.datetime, state: dict[str, Any], timings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Record the cycle that produced ``state``, then return it unchanged."""
    if journal is not None:
        journal.record_cycle(now, state, timings)
    return state


def timed_probe(provider: str, config: dict[str, Any], timings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run one probe, recording its start and duration on success and failure alike.

    The timing is kept out of ``state.json`` deliberately: it is diagnostic, and
    the published state schema is a durable record whose shape is approved
    separately. A timeout is therefore distinguishable from an immediate failure
    in the journal without changing the state contract.
    """
    started = utc_now()
    counter = time.perf_counter()
    try:
        return run_probe(provider, config)
    finally:
        timings[provider] = {
            "startedAt": iso(started),
            "durationMs": round((time.perf_counter() - counter) * 1000.0, 3),
        }


def observe(policy: dict[str, Any], now: dt.datetime | None = None, previous: dict[str, Any] | None = None, journal: Any = None) -> dict[str, Any]:
    now = now or utc_now()
    timings: dict[str, dict[str, Any]] = {}
    missing = missing_policy_values(policy)
    if missing:
        return journalled(journal, now, incomplete_state(policy, missing, now), timings)
    if not policy["monitoring"]["enabled"]:
        return journalled(journal, now, incomplete_state(policy, ["monitoring.enabled=false"], now), timings)
    needs_consumers = any(policy["providers"][p]["applicable"] and policy["providers"][p]["concurrency"]["enabled"] for p in CLOUD)
    try:
        consumers = fetch_active_consumers(policy) if needs_consumers else {p: [] for p in CLOUD}
        consumer_error = None
    except QuotaError as exc:
        consumers, consumer_error = {p: [] for p in CLOUD}, exc
    providers = {}
    for provider in CLOUD:
        config = policy["providers"][provider]
        if not config["applicable"]:
            providers[provider] = {"applicable": False, "health": "EXCLUDED", "state": "EXCLUDED"}
            continue
        if config["concurrency"]["enabled"] and consumer_error:
            error = consumer_error
        else:
            try:
                signal = timed_probe(provider, config, timings)
                state, evaluated = classify(signal, config, len(consumers[provider]))
                fresh = {"at": iso(now), "state": state, "causingWindows": causing_window_ids({"windows": evaluated})}
                providers[provider] = {
                    "applicable": True, "poolId": config["poolId"], "observedAt": iso(now), "health": "FRESH", "state": state,
                    "signal": {**signal, "windows": evaluated}, "activeConsumers": consumers[provider], "error": None,
                    "telemetry": telemetry_record(now, "FRESH", fresh),
                }
                continue
            except QuotaError as exc:
                error = exc
        providers[provider] = {
            "applicable": True, "poolId": config["poolId"], "observedAt": iso(now), "health": error.health, "state": "UNKNOWN",
            "signal": None, "activeConsumers": consumers[provider],
            "error": {"code": error.code, "message": str(error), "diagnostic": error.diagnostic},
            "telemetry": telemetry_record(now, error.health, retained_reading(policy, previous, provider)),
        }
    providers["ollama"] = {"applicable": False, "health": "EXCLUDED", "state": "EXCLUDED"}
    observation = {"schemaVersion": 1, "companyId": policy["companyId"], "configurationVersion": policy["configurationVersion"], "generatedAt": iso(now), "providers": providers}
    return journalled(journal, now, observation, timings)


def guard_decision(policy: dict[str, Any], state: dict[str, Any], provider: str, work: str, now: dt.datetime | None = None) -> dict[str, str]:
    now = now or utc_now()
    if provider == "ollama":
        return {"decision": "ALLOW", "reason": "PROVIDER_EXCLUDED"}
    if provider not in CLOUD:
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": "UNKNOWN_PROVIDER"}
    missing = missing_policy_values(policy)
    if missing:
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": "POLICY_INCOMPLETE"}
    record = state.get("providers", {}).get(provider)
    if not isinstance(record, dict):
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": "STATE_MISSING"}
    if state.get("companyId") != policy["companyId"] or state.get("configurationVersion") != policy["configurationVersion"]:
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": "STATE_PROVENANCE_MISMATCH"}
    observed = record.get("observedAt")
    if not observed:
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": record.get("health", "STATE_UNKNOWN")}
    try:
        stale = (now - parse_time(observed)).total_seconds() > policy["monitoring"]["staleAfterSeconds"]
    except (TypeError, ValueError):
        stale = True
    if stale:
        return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": "STATE_STALE"}
    quota_state, reason = record.get("state"), record.get("state")
    if record.get("health") != "FRESH" or quota_state not in TRUSTWORTHY_STATES:
        # Policy v1.1: a failed probe denies new provider work at once. Active work
        # keeps following the last trustworthy reading until it ages out of the
        # approved stale window, after which this falls closed with the rest.
        grace_state, grace_reason = effective_provider_state(policy, state, provider, now)
        if work != "active" or not grace_reason.startswith(TELEMETRY_GRACE_PREFIX):
            return {"decision": "DENY" if work == "new" else "CHECKPOINT_STOP", "reason": record.get("health", "STATE_UNKNOWN")}
        quota_state, reason = grace_state, grace_reason
    if quota_state == "GREEN":
        return {"decision": "ALLOW", "reason": reason}
    configured = policy["behaviors"][quota_state.lower()]["newWork" if work == "new" else "activeWork"]
    return {"decision": DECISIONS.get(configured, "DENY" if work == "new" else "CHECKPOINT_STOP"), "reason": reason}


def effective_provider_state(policy: dict[str, Any], state: dict[str, Any], provider: str, now: dt.datetime | None = None) -> tuple[str, str]:
    """Resolve runtime-control state without turning missing evidence into GREEN."""
    now = now or utc_now()
    record = state.get("providers", {}).get(provider)
    if state.get("companyId") != policy.get("companyId") or state.get("configurationVersion") != policy.get("configurationVersion"):
        return "UNKNOWN", "STATE_PROVENANCE_MISMATCH"
    if not isinstance(record, dict):
        return "UNKNOWN", "STATE_MISSING"
    reading = trustworthy_reading(record)
    try:
        stale = not reading or (now - parse_time(reading["at"])).total_seconds() > policy["monitoring"]["staleAfterSeconds"]
    except (KeyError, TypeError, ValueError):
        stale = True
    if stale:
        return "UNKNOWN", "STATE_STALE"
    if record.get("health") == "FRESH" and record.get("state") in TRUSTWORTHY_STATES:
        return record["state"], record["state"]
    # Policy v1.1: a failed or unavailable probe does not by itself pause already-running
    # work. Until the retained reading ages past the approved stale threshold it still
    # determines the provider state; past it the branch above falls closed to UNKNOWN.
    return reading["state"], TELEMETRY_GRACE_PREFIX + str(record.get("health") or "STATE_UNKNOWN")


def plan_active_controls(policy: dict[str, Any], state: dict[str, Any], consumers: dict[str, list[dict[str, Any]]], now: dt.datetime | None = None) -> list[dict[str, Any]]:
    if not policy.get("runtimeControl", {}).get("enabled"):
        return []
    plans: list[dict[str, Any]] = []
    for provider in CLOUD:
        if policy["providers"][provider].get("applicable") is not True:
            continue
        quota_state, reason = effective_provider_state(policy, state, provider, now)
        action_key = quota_state.lower() if quota_state in ("AMBER", "RED") else "unknown"
        action = policy["runtimeControl"]["actions"][action_key]
        if quota_state == "GREEN" or action != "pause_agents":
            continue
        by_agent: dict[str, list[str]] = {}
        interruptions_by_agent: dict[str, list[dict[str, str]]] = {}
        identities: dict[str, dict[str, Any]] = {}
        for consumer in consumers.get(provider, []):
            agent_id = consumer.get("agentId")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            by_agent.setdefault(agent_id, []).append(consumer.get("runId"))
            run_id, task_id = consumer.get("runId"), consumer.get("taskId")
            if isinstance(run_id, str) and run_id and isinstance(task_id, str) and task_id:
                interruptions_by_agent.setdefault(agent_id, []).append({"runId": run_id, "taskId": task_id})
            identities[agent_id] = consumer
        reading = trustworthy_reading(state.get("providers", {}).get(provider, {}))
        causing_windows = reading["causingWindows"] if reading and quota_state in ("AMBER", "RED") else []
        for agent_id, run_ids in by_agent.items():
            plans.append({
                "action": "pause_agent",
                "provider": provider,
                "poolId": policy["providers"][provider].get("poolId"),
                "quotaState": quota_state,
                "stateReason": reason,
                "causingWindows": causing_windows,
                "agentId": agent_id,
                "agentName": identities[agent_id].get("agentName"),
                "runIds": sorted({run_id for run_id in run_ids if isinstance(run_id, str) and run_id}),
                "interruptedRuns": sorted(
                    {
                        (item["taskId"], item["runId"]): item
                        for item in interruptions_by_agent.get(agent_id, [])
                    }.values(),
                    key=lambda item: (item["taskId"], item["runId"]),
                ),
                "checkpointUnresolvedRunIds": sorted(
                    set(run_ids) - {item["runId"] for item in interruptions_by_agent.get(agent_id, [])}
                ),
                "requiresProviderInference": False,
                "automaticResumeRequested": False,
                "failureClassification": "quota_manager_preventive_stop",
            })
    return plans


def pause_paperclip_agent(policy: dict[str, Any], agent_id: str) -> dict[str, Any]:
    base = policy["paperclip"]["baseUrl"].rstrip("/")
    path = policy["runtimeControl"]["pauseAgentPath"].format(agentId=agent_id)
    request = Request(base + path, data=b"{}", headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=policy["runtimeControl"]["requestTimeoutSeconds"]) as response:
            result = json.load(response)
    except Exception as exc:
        raise QuotaError("AGENT_PAUSE_FAILED", type(exc).__name__) from exc
    if not isinstance(result, dict) or result.get("id") != agent_id or result.get("status") != "paused":
        raise QuotaError("AGENT_PAUSE_UNCONFIRMED", "Paperclip did not confirm paused agent state", "MALFORMED")
    return {"agentId": agent_id, "agentStatus": "paused"}


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one durable JSON line, flushed and fsynced before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_control_event(path: Path, event: dict[str, Any]) -> None:
    append_jsonl(path, event)


def _fetch_paperclip_json(policy: dict[str, Any], path: str) -> dict[str, Any]:
    base = policy["paperclip"]["baseUrl"].rstrip("/")
    request = Request(base + path, headers={"Accept": "application/json"})
    with urlopen(request, timeout=policy["paperclip"]["activeRunsTimeoutSeconds"]) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise QuotaError("CHECKPOINT_EVIDENCE_MALFORMED", f"Paperclip returned a non-object for {path}", "MALFORMED")
    return value


def _checkpoint_run_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    context = run.get("contextSnapshot") if isinstance(run.get("contextSnapshot"), dict) else {}
    continuation = context.get("paperclipContinuationSummary")
    return {
        "id": run.get("id"),
        "agentId": run.get("agentId"),
        "status": run.get("status"),
        "errorCode": run.get("errorCode"),
        "startedAt": run.get("startedAt"),
        "finishedAt": run.get("finishedAt"),
        "contextSnapshot": {
            "issueId": context.get("issueId"),
            "taskId": context.get("taskId"),
            "projectId": context.get("projectId"),
            "paperclipContinuationSummary": continuation if isinstance(continuation, dict) else None,
        },
    }


def _checkpoint_issue_snapshot(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "status": issue.get("status"),
        "projectId": issue.get("projectId"),
        "updatedAt": issue.get("updatedAt"),
    }


def _checkpoint_local_worker_spec(evidence: Path, output: Path, task_id: str, run_id: str, agent_id: str) -> dict[str, Any]:
    collector = Path(__file__).with_name("checkpoint_collector.py").resolve()
    return {
        "command": str(Path(sys.executable).resolve()),
        "args": [
            str(collector),
            "--evidence", str(evidence.resolve()),
            "--output", str(output.resolve()),
            "--task-id", task_id,
            "--run-id", run_id,
            "--agent-id", agent_id,
        ],
        "workingDirectory": str(Path(__file__).parents[2].resolve()),
        "expectedArtifacts": [str(output.resolve())],
        "expectedExitCode": 0,
        "timeoutSeconds": CHECKPOINT_COLLECTOR_TIMEOUT_SECONDS,
    }


def dispatch_checkpoint_tasks(
    policy: dict[str, Any], plan: dict[str, Any], result_event: dict[str, Any], event_path: Path
) -> dict[str, int]:
    """Persist evidence and idempotently assign one collector task per interrupted run."""
    created = failed = 0
    dispatch_path = event_path.with_name("checkpoint-dispatches.jsonl")
    evidence_root = event_path.parent / "checkpoint-evidence"
    checkpoint_root = event_path.parent / "checkpoints"
    unresolved = plan.get("checkpointUnresolvedRunIds", [])
    for run_id in unresolved:
        append_control_event(dispatch_path, {
            "schemaVersion": 1,
            "eventId": result_event["eventId"],
            "recordedAt": result_event["recordedAt"],
            "taskId": None,
            "runId": run_id,
            "agentId": plan["agentId"],
            "outcome": "failed",
            "error": {"code": "CHECKPOINT_TASK_ID_UNKNOWN", "type": "CheckpointIdentityError"},
            "requiresProviderInference": False,
        })
        failed += 1
    for identity in plan.get("interruptedRuns", []):
        run_id, task_id = identity.get("runId"), identity.get("taskId")
        if not all(isinstance(value, str) and value for value in (run_id, task_id)):
            failed += 1
            append_control_event(dispatch_path, {
                "schemaVersion": 1, "outcome": "failed", "reason": "INTERRUPTION_IDENTITY_MISSING",
                "eventId": result_event["eventId"], "recordedAt": result_event["recordedAt"],
            })
            continue
        checkpoint_id = checkpoint_interruption_id(
            policy["companyId"], plan["provider"], plan["agentId"], [{"taskId": task_id, "runId": run_id}]
        )
        evidence_path = evidence_root / f"{checkpoint_id}.json"
        output_path = checkpoint_root / f"{checkpoint_id}.json"
        idempotency_key = f"quota-checkpoint:v1:{checkpoint_id.removeprefix('quota-pause-v1-')}"
        try:
            run = _fetch_paperclip_json(policy, f"/api/heartbeat-runs/{run_id}")
            issue = _fetch_paperclip_json(policy, f"/api/issues/{task_id}")
            run_snapshot, issue_snapshot = _checkpoint_run_snapshot(run), _checkpoint_issue_snapshot(issue)
            if run_snapshot["id"] != run_id or run_snapshot["agentId"] != plan["agentId"]:
                raise QuotaError("CHECKPOINT_RUN_IDENTITY_MISMATCH", "Paperclip run identity changed", "MALFORMED")
            context = run_snapshot["contextSnapshot"]
            if (context.get("issueId") or context.get("taskId")) != task_id or issue_snapshot["id"] != task_id:
                raise QuotaError("CHECKPOINT_TASK_IDENTITY_MISMATCH", "Paperclip task identity changed", "MALFORMED")
            evidence = {
                "schemaVersion": 1,
                "interruptionId": checkpoint_id,
                "controlEvent": result_event,
                "run": run_snapshot,
                "issue": issue_snapshot,
                "verifiedCompletedWork": [],
            }
            write_state(evidence_path, evidence)
            spec = _checkpoint_local_worker_spec(evidence_path, output_path, task_id, run_id, plan["agentId"])
            fence = "```"
            description = (
                "Create the deterministic continuation checkpoint for the confirmed quota-manager interruption below. "
                "Do not interpret intent, infer next work, or invoke a model/provider.\n\n"
                f"Source task: {issue_snapshot.get('identifier') or task_id}\n"
                f"Interrupted run: {run_id}\n"
                f"Interrupted agent: {plan['agentId']}\n\n"
                f"{fence}local-worker-run\n{json.dumps(spec, indent=2)}\n{fence}"
            )
            payload = {
                "projectId": issue_snapshot.get("projectId"),
                "title": f"Collect quota-pause checkpoint for {issue_snapshot.get('identifier') or task_id}",
                "description": description,
                "status": "todo",
                "assigneeAgentId": LOCAL_WORKER_AGENT_ID,
                "idempotencyKey": idempotency_key,
                "allowDuplicate": True,
            }
            base = policy["paperclip"]["baseUrl"].rstrip("/")
            request = Request(
                base + f"/api/companies/{policy['companyId']}/issues",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=policy["runtimeControl"]["requestTimeoutSeconds"]) as response:
                created_issue = json.load(response)
            if not isinstance(created_issue, dict) or created_issue.get("assigneeAgentId") != LOCAL_WORKER_AGENT_ID:
                raise QuotaError("CHECKPOINT_TASK_ASSIGNMENT_UNCONFIRMED", "Paperclip did not confirm Local Worker assignment", "MALFORMED")
            append_control_event(dispatch_path, {
                "schemaVersion": 1,
                "checkpointId": checkpoint_id,
                "eventId": result_event["eventId"],
                "recordedAt": result_event["recordedAt"],
                "taskId": task_id,
                "runId": run_id,
                "agentId": plan["agentId"],
                "collectorIssueId": created_issue.get("id"),
                "collectorIssueIdentifier": created_issue.get("identifier"),
                "idempotencyKey": idempotency_key,
                "evidencePath": str(evidence_path.resolve()),
                "checkpointPath": str(output_path.resolve()),
                "outcome": "dispatched",
                "deduplicated": created_issue.get("deduplicated") is True,
                "requiresProviderInference": False,
            })
            created += 1
        except Exception as exc:
            append_control_event(dispatch_path, {
                "schemaVersion": 1,
                "checkpointId": checkpoint_id,
                "eventId": result_event["eventId"],
                "recordedAt": result_event["recordedAt"],
                "taskId": task_id,
                "runId": run_id,
                "agentId": plan["agentId"],
                "idempotencyKey": idempotency_key,
                "outcome": "failed",
                "error": {"code": getattr(exc, "code", "CHECKPOINT_DISPATCH_FAILED"), "type": type(exc).__name__},
                "requiresProviderInference": False,
            })
            failed += 1
    return {"planned": len(plan.get("interruptedRuns", [])) + len(unresolved), "dispatched": created, "failed": failed}


def enforce_active_controls(policy: dict[str, Any], state: dict[str, Any], event_path: Path, *, now: dt.datetime | None = None, consumers: dict[str, list[dict[str, Any]]] | None = None, pause_agent: Any = None, checkpoint_dispatcher: Any = None) -> dict[str, Any]:
    now = now or utc_now()
    if missing_policy_values(policy):
        return {"outcome": "blocked", "reason": "POLICY_INCOMPLETE", "planned": 0, "succeeded": 0, "failed": 0}
    if not policy["runtimeControl"]["enabled"]:
        return {"outcome": "disabled", "reason": "RUNTIME_CONTROL_DISABLED", "planned": 0, "succeeded": 0, "failed": 0}
    active = consumers if consumers is not None else fetch_active_consumers(policy)
    plans = plan_active_controls(policy, state, active, now)
    pause = pause_agent or (lambda agent_id: pause_paperclip_agent(policy, agent_id))
    succeeded = failed = checkpoint_planned = checkpoint_dispatched = checkpoint_failed = 0
    for plan in plans:
        event_id = str(uuid.uuid4())
        common = {"schemaVersion": 1, "eventId": event_id, "recordedAt": iso(now), "companyId": policy["companyId"], **plan}
        append_control_event(event_path, {**common, "phase": "intent", "outcome": "pending"})
        try:
            receipt = pause(plan["agentId"])
            result_event = {**common, "phase": "result", "outcome": "paused", "receipt": receipt}
            append_control_event(event_path, result_event)
            succeeded += 1
            if checkpoint_dispatcher is not None:
                dispatch = checkpoint_dispatcher(policy, plan, result_event, event_path)
                checkpoint_planned += dispatch["planned"]
                checkpoint_dispatched += dispatch["dispatched"]
                checkpoint_failed += dispatch["failed"]
        except Exception as exc:
            append_control_event(event_path, {**common, "phase": "result", "outcome": "failed", "error": {"code": getattr(exc, "code", "PAUSE_FAILED"), "type": type(exc).__name__}})
            failed += 1
    return {
        "outcome": "completed" if failed == 0 and checkpoint_failed == 0 else "partial_failure",
        "reason": None,
        "planned": len(plans), "succeeded": succeeded, "failed": failed,
        "checkpointPlanned": checkpoint_planned,
        "checkpointDispatched": checkpoint_dispatched,
        "checkpointFailed": checkpoint_failed,
    }


def resolve_launch_command(policy: dict[str, Any], provider: str, passthrough: list[str], engine: str = "cli") -> list[str] | None:
    """Build the guarded provider launch from the central policy binding.

    The wrapper supplies only the adapter's own arguments. Every executable comes
    from the central configuration so a launch seam cannot drift from what the
    monitor was configured against, and so it never depends on PATH shim
    resolution (the `.ps1`/`.cmd` shims are not directly executable).

    Paperclip starts a `claude_local`/`codex_local` agent through one of two
    engines, and they start different programs, so each engine needs its own
    binding. `cli` launches the provider's command-line tool, bound by
    `source.command` — the same binary the monitor probes. `acp` launches the
    provider's ACP protocol server, bound by `launch.acp`, which the monitor
    never probes; both its interpreter and its entry module must exist, so a
    missing or moved ACP install denies the launch instead of being retried
    through PATH.
    """
    entry = policy.get("providers", {}).get(provider)
    if not isinstance(entry, dict) or not entry.get("applicable"):
        return None
    if engine == "acp":
        binding = (entry.get("launch") or {}).get("acp")
        if not isinstance(binding, dict):
            return None
        binary, leading = binding.get("command"), [binding.get("module")]
    elif engine == "cli":
        binary, leading = (entry.get("source") or {}).get("command"), []
    else:
        return None
    if not all(isinstance(part, str) and part.strip() and Path(part).is_file() for part in [binary, *leading]):
        return None
    return [binary, *leading, *passthrough]


def command_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "observe", "monitor", "enforce"):
        item = sub.add_parser(name)
        item.add_argument("--policy", type=Path, required=True)
        if name != "validate":
            item.add_argument("--state", type=Path, required=True)
        if name in ("monitor", "enforce"):
            item.add_argument("--events", type=Path)
    guard = sub.add_parser("guard")
    guard.add_argument("--policy", type=Path, required=True); guard.add_argument("--state", type=Path, required=True)
    guard.add_argument("--provider", required=True); guard.add_argument("--work", choices=("new", "active"), default="new")
    execute = sub.add_parser("exec")
    execute.add_argument("--policy", type=Path, required=True); execute.add_argument("--state", type=Path, required=True)
    execute.add_argument("--provider", required=True)
    execute.add_argument("--engine", choices=("cli", "acp"), default="cli")
    execute.add_argument("remainder", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    # `exec` hands its own stdout to the launched program. For the ACP engine that
    # stream IS the agent protocol channel (newline-delimited JSON-RPC), so any
    # diagnostic the guard writes there would be read as a protocol message and
    # corrupt the session. Every `exec` diagnostic therefore goes to stderr, which
    # Paperclip already captures per run.
    diagnostics = sys.stderr if args.command == "exec" else sys.stdout
    try:
        policy = read_json(args.policy)
    except Exception as exc:
        print(json.dumps({"decision": "DENY", "reason": "POLICY_MALFORMED", "errorType": type(exc).__name__}), file=diagnostics)
        return 78
    if args.command == "validate":
        missing = missing_policy_values(policy)
        print(json.dumps({"valid": not missing, "missing": missing}, indent=2))
        return 0 if not missing else 78
    if args.command == "enforce":
        try:
            state = read_json(args.state)
        except Exception as exc:
            print(json.dumps({"outcome": "blocked", "reason": "STATE_MALFORMED", "errorType": type(exc).__name__}))
            return 75
        events = args.events or args.state.with_name("control-events.jsonl")
        result = enforce_active_controls(policy, state, events, checkpoint_dispatcher=dispatch_checkpoint_tasks)
        print(json.dumps(result, indent=2))
        return 0 if result["outcome"] in ("completed", "disabled") and result["failed"] == 0 else 75
    if args.command in ("observe", "monitor"):
        # A restart must be able to inherit the retained reading the stale window is
        # measured from, so the previous state is seeded from disk and then carried
        # in memory for the life of the loop.
        try:
            previous = read_json(args.state)
        except Exception:
            previous = None
        if not isinstance(previous, dict):
            previous = None
        # The journal belongs to the supervised monitor loop: it is how a probe
        # outcome outlives the state file that replaces it every cycle. A one-shot
        # `observe` prints its own result and leaves no journal behind.
        journal = ProbeJournal(args.state.with_name(JOURNAL_FILENAME)) if args.command == "monitor" else None
        if args.command == "monitor" and (missing_policy_values(policy) or not policy.get("monitoring", {}).get("enabled")):
            state = observe(policy, previous=previous, journal=journal)
            write_state(args.state, state)
            print(json.dumps(state, indent=2))
            return 78
        while True:
            state = observe(policy, previous=previous, journal=journal)
            write_state(args.state, state)
            previous = state
            if args.command == "observe":
                print(json.dumps(state, indent=2))
                return 0 if all(v.get("state") in ("GREEN", "AMBER", "RED", "EXCLUDED") for v in state["providers"].values()) else 75
            if policy["runtimeControl"]["enabled"]:
                enforce_active_controls(policy, state, args.events or args.state.with_name("control-events.jsonl"), checkpoint_dispatcher=dispatch_checkpoint_tasks)
            time.sleep(policy["monitoring"]["pollIntervalSeconds"])
    try:
        state = read_json(args.state)
    except Exception as exc:
        state = {"providers": {}, "readError": type(exc).__name__}
    decision = guard_decision(policy, state, args.provider, "new" if args.command == "exec" else args.work)
    if args.command == "guard":
        print(json.dumps(decision))
        return 0 if decision["decision"] == "ALLOW" else 75
    passthrough = args.remainder[1:] if args.remainder[:1] == ["--"] else args.remainder
    if decision["decision"] != "ALLOW":
        print(json.dumps(decision), file=sys.stderr)
        return 75
    command = resolve_launch_command(policy, args.provider, passthrough, args.engine)
    if not command:
        print(json.dumps({"decision": "DENY", "reason": "LAUNCH_COMMAND_UNRESOLVED", "provider": args.provider, "engine": args.engine}), file=sys.stderr)
        return 64
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(command_main())
