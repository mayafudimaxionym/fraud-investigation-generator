from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "quota_manager.py"
SPEC = importlib.util.spec_from_file_location("quota_manager", MODULE_PATH)
qm = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qm)


def complete_policy() -> dict:
    threshold = lambda: {"metric": "used_percent", "amberAtOrAbove": 60, "redAtOrAbove": 85, "reserve": 5}
    provider = lambda kind, adapters, windows: {
        "applicable": True,
        "poolId": "shared-test-pool",
        "adapterTypes": adapters,
        "source": {"kind": kind, "command": "fixture-command", "profileDirectory": "fixture-profile", "timeoutSeconds": 2},
        "thresholds": {window: threshold() for window in windows},
        "concurrency": {"enabled": True, "strategy": "add_to_observed_metric", "adjustmentPerAdditionalConsumer": 4},
    }
    return {
        "schemaVersion": 1,
        "configurationVersion": "test-v1",
        "companyId": "test-company",
        "monitoring": {"enabled": True, "pollIntervalSeconds": 30, "staleAfterSeconds": 120},
        "paperclip": {"baseUrl": "http://fixture.invalid", "activeRunsPath": "/api/companies/{companyId}/live-runs?minCount=0&limit={limit}", "activeRunsTimeoutSeconds": 2, "activeRunsPageSize": 50},
        "providers": {
            "anthropic": provider("claude_stream_json_get_usage", ["claude_local"], ("five_hour", "seven_day")),
            "openai": provider("codex_app_server_rate_limits", ["codex_local"], ("primary", "secondary")),
            "ollama": {"applicable": False, "reason": "local"},
        },
        "behaviors": {
            "amber": {"newWork": "defer", "activeWork": "finish_current"},
            "red": {"newWork": "deny", "activeWork": "checkpoint_stop"},
            "unknown": {"newWork": "deny", "activeWork": "checkpoint_stop"},
            "telemetryFailure": {"newWork": "deny", "activeWork": "retain_last_trustworthy_reading"},
        },
        "runtimeControl": {
            "enabled": True,
            "mechanism": "paperclip_agent_pause",
            "pauseAgentPath": "/api/agents/{agentId}/pause",
            "requestTimeoutSeconds": 2,
            "actions": {"amber": "none", "red": "pause_agents", "unknown": "pause_agents"},
        },
    }


def fresh_state(policy: dict, state: str = "GREEN", now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    return {
        "schemaVersion": 1, "companyId": policy["companyId"], "configurationVersion": policy["configurationVersion"], "generatedAt": qm.iso(now),
        "providers": {
            "anthropic": {"applicable": True, "observedAt": qm.iso(now), "health": "FRESH", "state": state, "signal": {"windows": [{"id": "five_hour", "determinesProviderState": True}]}},
            "openai": {"applicable": True, "observedAt": qm.iso(now), "health": "FRESH", "state": state, "signal": {"windows": [{"id": "primary", "determinesProviderState": True}]}},
            "ollama": {"applicable": False, "health": "EXCLUDED", "state": "EXCLUDED"},
        },
    }


class PolicyTests(unittest.TestCase):
    def test_complete_configuration_parses(self):
        self.assertEqual([], qm.missing_policy_values(complete_policy()))

    def test_missing_configuration_is_explicit(self):
        policy = complete_policy()
        policy["monitoring"]["staleAfterSeconds"] = None
        policy["providers"]["anthropic"]["thresholds"]["five_hour"]["redAtOrAbove"] = None
        missing = qm.missing_policy_values(policy)
        self.assertIn("monitoring.staleAfterSeconds", missing)
        self.assertIn("providers.anthropic.thresholds.five_hour.redAtOrAbove", missing)
        observed = qm.observe(policy, dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))
        self.assertEqual("CONFIGURATION_INCOMPLETE", observed["providers"]["anthropic"]["health"])
        self.assertEqual("UNKNOWN", observed["providers"]["anthropic"]["state"])

    def test_runtime_control_configuration_is_required(self):
        policy = complete_policy()
        policy["runtimeControl"]["enabled"] = None
        policy["runtimeControl"]["requestTimeoutSeconds"] = None
        policy["runtimeControl"]["actions"]["red"] = None
        missing = qm.missing_policy_values(policy)
        self.assertIn("runtimeControl.enabled", missing)
        self.assertIn("runtimeControl.requestTimeoutSeconds", missing)
        self.assertIn("runtimeControl.actions.red", missing)

    def test_runtime_control_action_must_match_active_work_behavior(self):
        policy = complete_policy()
        policy["runtimeControl"]["actions"]["amber"] = "pause_agents"
        self.assertIn("runtimeControl.actions.amber.behaviorAlignment", qm.missing_policy_values(policy))

    def test_invalid_configuration_fails_validation(self):
        policy = complete_policy()
        policy["providers"]["openai"]["source"]["kind"] = "claude_stream_json_get_usage"
        policy["providers"]["openai"]["thresholds"]["primary"]["amberAtOrAbove"] = 90
        policy["providers"]["openai"]["thresholds"]["primary"]["redAtOrAbove"] = 80
        issues = qm.missing_policy_values(policy)
        self.assertIn("providers.openai.source.kind", issues)
        self.assertIn("providers.openai.thresholds.primary.ordering", issues)

    def test_adapter_types_cannot_map_one_run_to_two_pools(self):
        policy = complete_policy()
        policy["providers"]["openai"]["adapterTypes"].append("claude_local")
        self.assertIn("providers.adapterTypes.poolOverlap", qm.missing_policy_values(policy))


class ProviderParsingTests(unittest.TestCase):
    def test_valid_claude_observation(self):
        value = {"type": "control_response", "response": {"subtype": "success", "request_id": "quota-manager-get-usage", "response": {
            "subscription_type": "pro", "rate_limits_available": True,
            "rate_limits": {"five_hour": {"utilization": 12, "resets_at": "2030-01-01T01:00:00Z"}, "seven_day": {"utilization": 34, "resets_at": "2030-01-02T00:00:00Z"}, "future_field": {"other": True}},
        }}}
        parsed = qm.parse_claude_output(json.dumps(value))
        self.assertEqual([12.0, 34.0], [w["value"] for w in parsed["windows"]])

    def test_extra_usage_and_banked_provider_windows_are_not_capacity(self):
        value = {"type": "control_response", "response": {"subtype": "success", "response": {
            "rate_limits_available": True,
            "rate_limits": {
                "five_hour": {"utilization": 12, "resets_at": "2030-01-01T01:00:00Z"},
                "seven_day": {"utilization": 34, "resets_at": "2030-01-02T00:00:00Z"},
                "extra_usage": {"is_enabled": True, "utilization": 1, "used_credits": 2},
                "promotional_pool": {"utilization": 0, "resets_at": None},
            },
        }}}
        parsed = qm.parse_claude_output(json.dumps(value))
        self.assertEqual(["five_hour", "seven_day"], [w["id"] for w in parsed["windows"]])

    def test_valid_codex_observation_and_provider_separation(self):
        rate = {"jsonrpc": "2.0", "id": 2, "result": {"ordinaryUsageAllowed": True, "creditBalance": 999, "autoReload": True, "rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": 23, "windowDurationMins": 300, "resetsAt": 1},
            "secondary": {"usedPercent": 45, "windowDurationMins": 10080, "resetsAt": 2},
        }}}}
        account = {"jsonrpc": "2.0", "id": 3, "result": {"account": {"type": "chatgpt", "planType": "pro"}}}
        parsed = qm.parse_codex_output(json.dumps(rate) + "\n" + json.dumps(account))
        self.assertEqual("codex_app_server_rate_limits", parsed["sourceKind"])
        self.assertEqual([23.0, 45.0], [w["value"] for w in parsed["windows"]])
        self.assertNotIn("creditBalance", parsed)
        self.assertNotIn("autoReload", parsed)

    def test_null_codex_availability_is_unknown(self):
        value = {"jsonrpc": "2.0", "id": 2, "result": {"ordinaryUsageAllowed": None, "rateLimits": {
            "primary": {"usedPercent": 0}, "secondary": {"usedPercent": 0}
        }}}
        with self.assertRaises(qm.QuotaError) as error:
            qm.parse_codex_output(json.dumps(value))
        self.assertEqual("UNAVAILABLE", error.exception.health)

    def test_malformed_and_unavailable_are_not_green(self):
        with self.assertRaises(qm.QuotaError) as malformed:
            qm.parse_claude_output('{"type":"not-a-control-response"}')
        self.assertEqual("MALFORMED", malformed.exception.health)
        unavailable = {"type": "control_response", "response": {"subtype": "success", "response": {"rate_limits_available": False, "rate_limits": None}}}
        with self.assertRaises(qm.QuotaError) as error:
            qm.parse_claude_output(json.dumps(unavailable))
        self.assertEqual("UNAVAILABLE", error.exception.health)


class CodexProbeTransportTests(unittest.TestCase):
    """The installed codex-cli answers app-server requests out of order, so the read
    loop must key on the essential rate-limit response rather than request order."""

    RATE_LIMITS = {
        "id": 2,
        "result": {
            "ordinaryUsageAllowed": True,
            "rateLimits": {
                "primary": {"usedPercent": 66, "windowDurationMins": 300, "resetsAt": 1791310714},
                "secondary": {"usedPercent": 10, "windowDurationMins": 10080, "resetsAt": 1791897514},
            },
            "accountId": "fixture-account",
            "planType": "plus",
        },
    }
    ACCOUNT = {"id": 3, "result": {"account": {"type": "chatgpt", "planType": "plus"}}}

    class FakePopen:
        def __init__(self, lines):
            self._lines = list(lines)
            self.stdin = io.StringIO()
            self.stdout = iter(self._lines)
            self.returncode = 0

        def poll(self):
            return self.returncode

        def kill(self):
            pass

        def wait(self):
            return self.returncode

    def probe(self, emitted):
        captured = {}

        def fake_popen(command, **kwargs):
            captured["command"] = command
            return self.FakePopen(json.dumps(item) + chr(10) for item in emitted)

        provider = complete_policy()["providers"]["openai"]
        with patch.object(qm.subprocess, "Popen", fake_popen):
            return qm.run_probe("openai", provider), captured["command"]

    def test_account_response_before_rate_limits_is_not_lost(self):
        # Observed ordering against codex-cli 0.156.1: id 3 answered before id 2.
        signal, _ = self.probe([self.ACCOUNT, self.RATE_LIMITS])
        self.assertEqual([window["id"] for window in signal["windows"]], ["primary", "secondary"])
        self.assertEqual(signal["windows"][0]["value"], 66.0)
        self.assertTrue(signal["ordinaryUsageAllowed"])

    def test_rate_limits_response_before_account_still_parses(self):
        signal, _ = self.probe([self.RATE_LIMITS, self.ACCOUNT])
        self.assertEqual([window["id"] for window in signal["windows"]], ["primary", "secondary"])

    def test_rate_limit_response_alone_is_sufficient(self):
        # Optional account metadata must never gate provider availability.
        signal, _ = self.probe([self.RATE_LIMITS])
        self.assertEqual(signal["account"]["accountId"], "fixture-account")

    def test_probe_uses_an_approval_value_the_installed_cli_accepts(self):
        # codex-cli 0.156.1 rejects `-a untrusted` with exit 2.
        _, command = self.probe([self.RATE_LIMITS])
        self.assertIn("-a", command)
        self.assertEqual(command[command.index("-a") + 1], "never")
        self.assertEqual(command[command.index("-s") + 1], "read-only")


class ClassificationTests(unittest.TestCase):
    def test_transitions_use_fixture_values_only(self):
        config = complete_policy()["providers"]["openai"]
        signal = {"windows": [{"id": "primary", "metric": "used_percent", "value": 20}, {"id": "secondary", "metric": "used_percent", "value": 20}]}
        self.assertEqual("GREEN", qm.classify(signal, config, 1)[0])
        signal["windows"][0]["value"] = 56
        self.assertEqual("AMBER", qm.classify(signal, config, 1)[0])
        signal["windows"][0]["value"] = 80
        self.assertEqual("RED", qm.classify(signal, config, 1)[0])

    def test_concurrency_adjusts_shared_pool(self):
        config = complete_policy()["providers"]["openai"]
        signal = {"windows": [{"id": "primary", "metric": "used_percent", "value": 48}, {"id": "secondary", "metric": "used_percent", "value": 10}]}
        state, windows = qm.classify(signal, config, 3)
        self.assertEqual("AMBER", state)
        self.assertEqual(61, windows[0]["effectiveValue"])
        self.assertEqual(23, windows[1]["effectiveValue"])
        self.assertEqual([8, 8], [window["concurrencyAdjustment"] for window in windows])

    def test_worst_window_determines_provider_state_and_is_explainable(self):
        config = complete_policy()["providers"]["openai"]
        signal = {"windows": [
            {"id": "primary", "metric": "used_percent", "value": 10, "resetsAt": 1, "windowDurationMins": 300},
            {"id": "secondary", "metric": "used_percent", "value": 81, "resetsAt": 2, "windowDurationMins": 10080},
        ]}
        state, windows = qm.classify(signal, config, 1)
        self.assertEqual("RED", state)
        self.assertEqual(["GREEN", "RED"], [window["state"] for window in windows])
        self.assertEqual([False, True], [window["determinesProviderState"] for window in windows])
        self.assertEqual([1, 2], [window["resetsAt"] for window in windows])
        self.assertEqual([60, 60], [window["amberAtOrAbove"] for window in windows])
        self.assertEqual([85, 85], [window["redAtOrAbove"] for window in windows])
        self.assertEqual([5, 5], [window["reserve"] for window in windows])

    def test_policy_rejects_non_plan_capacity_window(self):
        policy = complete_policy()
        policy["providers"]["anthropic"]["thresholds"]["extra_usage"] = {
            "metric": "used_percent", "amberAtOrAbove": 60, "redAtOrAbove": 85, "reserve": 5
        }
        self.assertIn("providers.anthropic.thresholds.windows", qm.missing_policy_values(policy))

    def test_ollama_is_excluded(self):
        policy = complete_policy()
        self.assertEqual({"decision": "ALLOW", "reason": "PROVIDER_EXCLUDED"}, qm.guard_decision(policy, {}, "ollama", "new"))

    @patch.object(qm, "urlopen")
    def test_truncated_concurrency_input_fails_closed(self, open_url):
        policy = complete_policy()
        policy["paperclip"]["activeRunsPageSize"] = 1
        response = io.StringIO(json.dumps([{"id": "run-1", "status": "running", "adapterType": "claude_local"}]))
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        open_url.return_value = response
        with self.assertRaises(qm.QuotaError) as error:
            qm.fetch_active_consumers(policy)
        self.assertEqual("ACTIVE_RUNS_TRUNCATED", error.exception.code)


class StateAndGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        self.policy = complete_policy()

    def test_shared_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            expected = fresh_state(self.policy, now=self.now)
            qm.write_state(path, expected)
            self.assertEqual(expected, qm.read_json(path))

    def test_green_allows_and_red_prevents_new_cloud_work(self):
        green = qm.guard_decision(self.policy, fresh_state(self.policy, "GREEN", self.now), "anthropic", "new", self.now)
        red = qm.guard_decision(self.policy, fresh_state(self.policy, "RED", self.now), "anthropic", "new", self.now)
        self.assertEqual("ALLOW", green["decision"])
        self.assertEqual("DENY", red["decision"])

    def test_amber_new_work_defers_and_active_work_finishes(self):
        state = fresh_state(self.policy, "AMBER", self.now)
        self.assertEqual("DEFER", qm.guard_decision(self.policy, state, "openai", "new", self.now)["decision"])
        self.assertEqual("FINISH_CURRENT", qm.guard_decision(self.policy, state, "openai", "active", self.now)["decision"])

    def test_stale_unavailable_and_missing_never_false_green(self):
        stale_time = self.now - dt.timedelta(seconds=121)
        stale = qm.guard_decision(self.policy, fresh_state(self.policy, "GREEN", stale_time), "anthropic", "new", self.now)
        self.assertEqual("DENY", stale["decision"])
        unavailable = fresh_state(self.policy, "UNKNOWN", self.now)
        unavailable["providers"]["anthropic"]["health"] = "UNAVAILABLE"
        self.assertEqual("DENY", qm.guard_decision(self.policy, unavailable, "anthropic", "new", self.now)["decision"])
        self.assertEqual("DENY", qm.guard_decision(self.policy, {}, "anthropic", "new", self.now)["decision"])

    def test_configuration_provenance_mismatch_fails_closed(self):
        state = fresh_state(self.policy, "GREEN", self.now)
        state["configurationVersion"] = "old"
        self.assertEqual("DENY", qm.guard_decision(self.policy, state, "openai", "new", self.now)["decision"])

    @patch.object(qm, "run_probe")
    @patch.object(qm, "fetch_active_consumers")
    def test_observe_separates_provider_failures(self, consumers, probe):
        consumers.return_value = {"anthropic": [{"runId": "c1"}, {"runId": "c2"}], "openai": [{"runId": "o1"}]}
        def result(provider, _config):
            if provider == "anthropic":
                raise qm.QuotaError("FIXTURE_UNAVAILABLE", "fixture")
            return {"ordinaryUsageAllowed": True, "windows": [{"id": "primary", "metric": "used_percent", "value": 1}, {"id": "secondary", "metric": "used_percent", "value": 1}]}
        probe.side_effect = result
        state = qm.observe(self.policy, self.now)
        self.assertEqual("UNKNOWN", state["providers"]["anthropic"]["state"])
        self.assertEqual("GREEN", state["providers"]["openai"]["state"])


def succeeding_probe(value: float):
    def result(provider, _config):
        windows = ("five_hour", "seven_day") if provider == "anthropic" else ("primary", "secondary")
        return {"ordinaryUsageAllowed": True, "windows": [{"id": window, "metric": "used_percent", "value": value} for window in windows]}
    return result


def failing_probe(_provider, _config):
    raise qm.QuotaError("FIXTURE_UNAVAILABLE", "fixture probe failed")


class TelemetryFailureGraceTests(unittest.TestCase):
    """Policy v1.1: transient telemetry failure is distinct from persistent UNKNOWN/STALE."""

    def setUp(self):
        self.now = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        self.policy = complete_policy()  # monitoring.staleAfterSeconds = 120
        self.window = self.policy["monitoring"]["staleAfterSeconds"]
        self.consumers = {
            "anthropic": [{"runId": "claude-1", "taskId": "task-c1", "agentId": "agent-c1", "agentName": "Claude One", "status": "running"}],
            "openai": [],
        }

    def observed(self, probe, now, previous=None):
        with patch.object(qm, "fetch_active_consumers", return_value={"anthropic": [], "openai": []}), \
             patch.object(qm, "run_probe", side_effect=probe):
            return qm.observe(self.policy, now, previous=previous)

    def test_policy_requires_the_approved_telemetry_failure_behaviour(self):
        absent = complete_policy()
        del absent["behaviors"]["telemetryFailure"]
        missing = qm.missing_policy_values(absent)
        self.assertIn("behaviors.telemetryFailure.newWork", missing)
        self.assertIn("behaviors.telemetryFailure.failClosedInvariant", missing)
        weakened = complete_policy()
        weakened["behaviors"]["telemetryFailure"]["newWork"] = "defer"
        self.assertIn("behaviors.telemetryFailure.failClosedInvariant", qm.missing_policy_values(weakened))
        self.assertEqual([], qm.missing_policy_values(complete_policy()))

    def test_transient_failure_blocks_new_work_without_pausing_active_work(self):
        green = self.observed(succeeding_probe(10), self.now)
        self.assertEqual("GREEN", green["providers"]["anthropic"]["state"])
        later = self.now + dt.timedelta(seconds=60)
        failed = self.observed(failing_probe, later, previous=green)
        record = failed["providers"]["anthropic"]
        self.assertEqual(("UNAVAILABLE", "UNKNOWN"), (record["health"], record["state"]))
        self.assertEqual(qm.iso(self.now), record["telemetry"]["lastTrustworthyAt"])
        self.assertEqual("GREEN", record["telemetry"]["lastTrustworthyState"])
        self.assertEqual("DENY", qm.guard_decision(self.policy, failed, "anthropic", "new", later)["decision"])
        self.assertEqual("ALLOW", qm.guard_decision(self.policy, failed, "anthropic", "active", later)["decision"])
        self.assertEqual([], qm.plan_active_controls(self.policy, failed, self.consumers, later))

    def test_consecutive_failures_do_not_restart_the_stale_clock(self):
        green = self.observed(succeeding_probe(10), self.now)
        first = self.observed(failing_probe, self.now + dt.timedelta(seconds=40), previous=green)
        inside = self.now + dt.timedelta(seconds=self.window - 1)
        second = self.observed(failing_probe, inside, previous=first)
        self.assertEqual(qm.iso(self.now), second["providers"]["anthropic"]["telemetry"]["lastTrustworthyAt"])
        self.assertEqual(qm.iso(inside), second["providers"]["anthropic"]["telemetry"]["probedAt"])
        self.assertEqual([], qm.plan_active_controls(self.policy, second, self.consumers, inside))

    def test_persistent_failure_pauses_active_work_once_the_window_elapses(self):
        green = self.observed(succeeding_probe(10), self.now)
        failed = self.observed(failing_probe, self.now + dt.timedelta(seconds=40), previous=green)
        after = self.now + dt.timedelta(seconds=self.window + 1)
        plans = qm.plan_active_controls(self.policy, failed, self.consumers, after)
        self.assertEqual(["agent-c1"], [plan["agentId"] for plan in plans])
        self.assertEqual(("UNKNOWN", "STATE_STALE"), (plans[0]["quotaState"], plans[0]["stateReason"]))
        self.assertEqual([], plans[0]["causingWindows"])
        self.assertEqual("CHECKPOINT_STOP", qm.guard_decision(self.policy, failed, "anthropic", "active", after)["decision"])
        self.assertEqual("DENY", qm.guard_decision(self.policy, failed, "anthropic", "new", after)["decision"])

    def test_recovery_inside_the_window_lets_the_new_reading_govern(self):
        green = self.observed(succeeding_probe(10), self.now)
        failed = self.observed(failing_probe, self.now + dt.timedelta(seconds=40), previous=green)
        recovery = self.now + dt.timedelta(seconds=self.window - 20)
        recovered = self.observed(succeeding_probe(10), recovery, previous=failed)
        record = recovered["providers"]["anthropic"]
        self.assertEqual(("FRESH", "GREEN"), (record["health"], record["state"]))
        self.assertEqual(qm.iso(recovery), record["telemetry"]["lastTrustworthyAt"])
        self.assertEqual("ALLOW", qm.guard_decision(self.policy, recovered, "anthropic", "new", recovery)["decision"])
        self.assertEqual([], qm.plan_active_controls(self.policy, recovered, self.consumers, recovery))
        # The grace window belonged to the failed probe, not to the recovered reading.
        past_old_window = self.now + dt.timedelta(seconds=self.window + 1)
        self.assertEqual([], qm.plan_active_controls(self.policy, recovered, self.consumers, past_old_window))

    def test_observed_red_pauses_immediately_without_a_grace_window(self):
        red = self.observed(succeeding_probe(90), self.now)
        self.assertEqual("RED", red["providers"]["anthropic"]["state"])
        plans = qm.plan_active_controls(self.policy, red, self.consumers, self.now)
        self.assertEqual(["agent-c1"], [plan["agentId"] for plan in plans])
        self.assertEqual("RED", plans[0]["quotaState"])
        self.assertEqual(["five_hour", "seven_day"], sorted(plans[0]["causingWindows"]))
        self.assertEqual("DENY", qm.guard_decision(self.policy, red, "anthropic", "new", self.now)["decision"])

    def test_a_retained_red_reading_keeps_pausing_and_stays_explainable(self):
        red = self.observed(succeeding_probe(90), self.now)
        later = self.now + dt.timedelta(seconds=60)
        failed = self.observed(failing_probe, later, previous=red)
        plans = qm.plan_active_controls(self.policy, failed, self.consumers, later)
        self.assertEqual(["agent-c1"], [plan["agentId"] for plan in plans])
        self.assertEqual("RED", plans[0]["quotaState"])
        self.assertEqual("TELEMETRY_GRACE_UNAVAILABLE", plans[0]["stateReason"])
        self.assertEqual(["five_hour", "seven_day"], sorted(plans[0]["causingWindows"]))

    def test_grace_is_not_inherited_across_a_configuration_version_change(self):
        green = self.observed(succeeding_probe(10), self.now)
        stranger = {**green, "configurationVersion": "test-v0"}
        later = self.now + dt.timedelta(seconds=60)
        failed = self.observed(failing_probe, later, previous=stranger)
        self.assertIsNone(failed["providers"]["anthropic"]["telemetry"]["lastTrustworthyAt"])
        plans = qm.plan_active_controls(self.policy, failed, self.consumers, later)
        self.assertEqual(("UNKNOWN", "STATE_STALE"), (plans[0]["quotaState"], plans[0]["stateReason"]))

    def test_incomplete_configuration_is_granted_no_grace(self):
        green = self.observed(succeeding_probe(10), self.now)
        self.policy["monitoring"]["staleAfterSeconds"] = None
        incomplete = qm.observe(self.policy, self.now + dt.timedelta(seconds=60), previous=green)
        telemetry = incomplete["providers"]["anthropic"]["telemetry"]
        self.assertEqual("CONFIGURATION_INCOMPLETE", telemetry["health"])
        self.assertIsNone(telemetry["lastTrustworthyAt"])

    def test_a_state_file_written_before_v1_1_still_fails_closed(self):
        legacy = fresh_state(self.policy, "GREEN", self.now)
        legacy["providers"]["anthropic"].update({"health": "UNAVAILABLE", "state": "UNKNOWN", "signal": None})
        plans = qm.plan_active_controls(self.policy, legacy, self.consumers, self.now)
        self.assertEqual(["agent-c1"], [plan["agentId"] for plan in plans])
        self.assertEqual("STATE_STALE", plans[0]["stateReason"])


class ActiveControlTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        self.policy = complete_policy()
        self.consumers = {
            "anthropic": [
                {"runId": "claude-1", "taskId": "task-c1", "agentId": "agent-c1", "agentName": "Claude One", "status": "running"},
                {"runId": "claude-2", "taskId": "task-c2", "agentId": "agent-c2", "agentName": "Claude Two", "status": "running"},
            ],
            "openai": [{"runId": "codex-1", "taskId": "task-o1", "agentId": "agent-o1", "agentName": "Codex One", "status": "running"}],
        }

    @patch.object(qm, "urlopen")
    def test_active_claude_and_codex_discovered_and_ollama_ignored(self, open_url):
        runs = [
            {"id": "c", "issueId": "tc", "agentId": "ca", "agentName": "Claude", "status": "running", "adapterType": "claude_local"},
            {"id": "o", "issueId": "to", "agentId": "oa", "agentName": "Codex", "status": "queued", "adapterType": "codex_local"},
            {"id": "l", "issueId": "tl", "agentId": "la", "agentName": "Local", "status": "running", "adapterType": "process"},
        ]
        response = io.StringIO(json.dumps(runs))
        open_url.return_value = response
        discovered = qm.fetch_active_consumers(self.policy)
        self.assertEqual(["c"], [item["runId"] for item in discovered["anthropic"]])
        self.assertEqual(["o"], [item["runId"] for item in discovered["openai"]])
        self.assertNotIn("ollama", discovered)

    @patch.object(qm, "urlopen")
    def test_cloud_run_without_control_identity_fails_closed(self, open_url):
        open_url.return_value = io.StringIO(json.dumps([
            {"id": "c", "agentId": None, "status": "running", "adapterType": "claude_local"},
        ]))
        with self.assertRaises(qm.QuotaError) as error:
            qm.fetch_active_consumers(self.policy)
        self.assertEqual("ACTIVE_RUN_IDENTITY_MALFORMED", error.exception.code)

    @patch.object(qm, "urlopen")
    def test_cloud_run_without_task_identity_remains_pausable_but_is_not_checkpointed(self, open_url):
        open_url.return_value = io.StringIO(json.dumps([
            {"id": "c", "agentId": "ca", "status": "running", "adapterType": "claude_local"},
        ]))
        discovered = qm.fetch_active_consumers(self.policy)
        self.assertEqual("c", discovered["anthropic"][0]["runId"])
        self.assertIsNone(discovered["anthropic"][0]["taskId"])
        state = fresh_state(self.policy, "GREEN", self.now)
        state["providers"]["anthropic"]["state"] = "RED"
        plans = qm.plan_active_controls(self.policy, state, discovered, self.now)
        self.assertEqual(["c"], plans[0]["runIds"])
        self.assertEqual([], plans[0]["interruptedRuns"])
        self.assertEqual(["c"], plans[0]["checkpointUnresolvedRunIds"])

    def test_green_and_configured_amber_none_do_not_stop(self):
        green = qm.plan_active_controls(self.policy, fresh_state(self.policy, "GREEN", self.now), self.consumers, self.now)
        amber = qm.plan_active_controls(self.policy, fresh_state(self.policy, "AMBER", self.now), self.consumers, self.now)
        self.assertEqual([], green)
        self.assertEqual([], amber)

    def test_configured_amber_pause_is_enforced(self):
        self.policy["runtimeControl"]["actions"]["amber"] = "pause_agents"
        plans = qm.plan_active_controls(self.policy, fresh_state(self.policy, "AMBER", self.now), self.consumers, self.now)
        self.assertEqual({"agent-c1", "agent-c2", "agent-o1"}, {plan["agentId"] for plan in plans})

    def test_red_stops_all_agents_in_affected_pool_only(self):
        state = fresh_state(self.policy, "GREEN", self.now)
        state["providers"]["anthropic"]["state"] = "RED"
        plans = qm.plan_active_controls(self.policy, state, self.consumers, self.now)
        self.assertEqual({"agent-c1", "agent-c2"}, {plan["agentId"] for plan in plans})
        self.assertTrue(all(plan["provider"] == "anthropic" for plan in plans))
        self.assertTrue(all(plan["causingWindows"] == ["five_hour"] for plan in plans))

    def test_unknown_stale_and_malformed_state_follow_fail_closed_policy(self):
        stale = fresh_state(self.policy, "GREEN", self.now - dt.timedelta(seconds=121))
        stale_plans = qm.plan_active_controls(self.policy, stale, self.consumers, self.now)
        self.assertEqual(3, len(stale_plans))
        self.assertTrue(all(plan["causingWindows"] == [] for plan in stale_plans))
        malformed = fresh_state(self.policy, "GREEN", self.now)
        malformed["providers"]["openai"]["health"] = "MALFORMED"
        malformed_plans = qm.plan_active_controls(self.policy, malformed, self.consumers, self.now)
        self.assertEqual(["agent-o1"], [plan["agentId"] for plan in malformed_plans])

    def test_preventive_pause_receipt_is_recoverable_and_requires_no_inference(self):
        state = fresh_state(self.policy, "GREEN", self.now)
        state["providers"]["anthropic"]["state"] = "RED"
        paused = []
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "control-events.jsonl"
            result = qm.enforce_active_controls(
                self.policy, state, events, now=self.now, consumers=self.consumers,
                pause_agent=lambda agent_id: paused.append(agent_id) or {"agentId": agent_id, "agentStatus": "paused"},
            )
            records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        self.assertEqual({"agent-c1", "agent-c2"}, set(paused))
        self.assertEqual({"planned": 2, "succeeded": 2, "failed": 0}, {key: result[key] for key in ("planned", "succeeded", "failed")})
        intents = [record for record in records if record["phase"] == "intent"]
        self.assertEqual({"claude-1", "claude-2"}, {run for record in intents for run in record["runIds"]})
        self.assertTrue(all(record["failureClassification"] == "quota_manager_preventive_stop" for record in records))
        self.assertTrue(all(record["automaticResumeRequested"] is False for record in records))
        self.assertTrue(all(record["requiresProviderInference"] is False for record in records))

    def test_preventive_pause_is_not_provider_quota_retry(self):
        state = fresh_state(self.policy, "GREEN", self.now)
        state["providers"]["openai"]["state"] = "RED"
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "control-events.jsonl"
            qm.enforce_active_controls(
                self.policy, state, events, now=self.now, consumers=self.consumers,
                pause_agent=lambda agent_id: {"agentId": agent_id, "agentStatus": "paused"},
            )
            records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(records)
        self.assertTrue(all(record["failureClassification"] != "provider_quota" for record in records))
        self.assertTrue(all("retryAt" not in record and "retryNotBefore" not in record for record in records))

    def test_checkpoint_dispatch_occurs_only_after_confirmed_pause(self):
        state = fresh_state(self.policy, "GREEN", self.now)
        state["providers"]["anthropic"]["state"] = "RED"
        consumers = {"anthropic": [self.consumers["anthropic"][0]], "openai": []}
        dispatched = []

        def dispatcher(policy, plan, event, path):
            dispatched.append((plan, event))
            return {"planned": 1, "dispatched": 1, "failed": 0}

        with tempfile.TemporaryDirectory() as directory:
            result = qm.enforce_active_controls(
                self.policy, state, Path(directory) / "events.jsonl", now=self.now,
                consumers=consumers,
                pause_agent=lambda agent_id: {"agentId": agent_id, "agentStatus": "paused"},
                checkpoint_dispatcher=dispatcher,
            )
        self.assertEqual(1, len(dispatched))
        self.assertEqual("paused", dispatched[0][1]["outcome"])
        self.assertEqual([{"runId": "claude-1", "taskId": "task-c1"}], dispatched[0][0]["interruptedRuns"])
        self.assertEqual(1, result["checkpointDispatched"])

        dispatched.clear()
        with tempfile.TemporaryDirectory() as directory:
            qm.enforce_active_controls(
                self.policy, state, Path(directory) / "events.jsonl", now=self.now,
                consumers=consumers,
                pause_agent=lambda agent_id: (_ for _ in ()).throw(RuntimeError("pause failed")),
                checkpoint_dispatcher=dispatcher,
            )
        self.assertEqual([], dispatched)

    @patch.object(qm, "urlopen")
    def test_pause_uses_supported_paperclip_control_endpoint(self, open_url):
        response = io.StringIO(json.dumps({"id": "agent-c1", "status": "paused"}))
        open_url.return_value = response
        receipt = qm.pause_paperclip_agent(self.policy, "agent-c1")
        request = open_url.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertTrue(request.full_url.endswith("/api/agents/agent-c1/pause"))
        self.assertEqual({"agentId": "agent-c1", "agentStatus": "paused"}, receipt)


class GuardedLaunchTests(unittest.TestCase):
    """The `exec` seam must launch the centrally configured provider binary."""

    def setUp(self):
        self.policy = complete_policy()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.binary = Path(self.directory.name) / "provider-cli.exe"
        self.binary.write_text("", encoding="utf-8")
        for provider in ("anthropic", "openai"):
            self.policy["providers"][provider]["source"]["command"] = str(self.binary)

    def test_launch_uses_policy_binary_and_appends_adapter_arguments(self):
        command = qm.resolve_launch_command(self.policy, "anthropic", ["--print", "--verbose"])
        self.assertEqual([str(self.binary), "--print", "--verbose"], command)

    def test_launch_never_depends_on_path_shim_resolution(self):
        # A bare name is what the wrapper used to pass; it is not executable on
        # Windows because the PATH entries are `.cmd`/`.ps1` shims.
        self.policy["providers"]["anthropic"]["source"]["command"] = "claude"
        self.assertIsNone(qm.resolve_launch_command(self.policy, "anthropic", []))

    def test_launch_unresolved_for_excluded_or_unknown_provider(self):
        self.assertIsNone(qm.resolve_launch_command(self.policy, "ollama", []))
        self.assertIsNone(qm.resolve_launch_command(self.policy, "nonexistent", []))

    def test_missing_or_blank_policy_command_is_unresolved(self):
        for value in (None, "", "   "):
            self.policy["providers"]["openai"]["source"]["command"] = value
            self.assertIsNone(qm.resolve_launch_command(self.policy, "openai", []))

    def _run_exec(self, state: dict | None, argv_extra: list[str]) -> tuple[int, list[str] | None]:
        root = Path(self.directory.name)
        policy_path, state_path = root / "policy.json", root / "state.json"
        policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        if state is not None:
            state_path.write_text(json.dumps(state), encoding="utf-8")
        launched: list[str] | None = None

        def fake_run(command, check=False):
            nonlocal launched
            launched = command
            return type("Completed", (), {"returncode": 0})()

        argv = ["exec", "--policy", str(policy_path), "--state", str(state_path), *argv_extra]
        with patch.object(qm.subprocess, "run", fake_run):
            return qm.command_main(argv), launched

    def test_allow_launches_the_provider_cli(self):
        state = fresh_state(self.policy, now=qm.utc_now())
        code, launched = self._run_exec(state, ["--provider", "anthropic", "--", "--version"])
        self.assertEqual(0, code)
        self.assertEqual([str(self.binary), "--version"], launched)

    def test_denied_launch_never_starts_the_provider_cli(self):
        code, launched = self._run_exec(None, ["--provider", "anthropic", "--", "--version"])
        self.assertEqual(75, code)
        self.assertIsNone(launched)

    def test_stale_state_never_starts_the_provider_cli(self):
        stale = fresh_state(self.policy, now=qm.utc_now() - dt.timedelta(hours=13))
        code, launched = self._run_exec(stale, ["--provider", "anthropic", "--", "--version"])
        self.assertEqual(75, code)
        self.assertIsNone(launched)

    def test_allowed_but_unresolvable_binary_does_not_fall_back_to_path(self):
        self.policy["providers"]["anthropic"]["source"]["command"] = "claude"
        state = fresh_state(self.policy, now=qm.utc_now())
        code, launched = self._run_exec(state, ["--provider", "anthropic", "--", "--version"])
        self.assertEqual(64, code)
        self.assertIsNone(launched)

class AcpGuardedLaunchTests(unittest.TestCase):
    """The ACP engine is a separate launch seam with its own central binding.

    Paperclip's `claude_local`/`codex_local` adapters default `engine` to ACP,
    which starts the provider's ACP protocol server rather than its command-line
    tool. The two engines start different programs, so a CLI binding must never
    satisfy an ACP launch or the reverse.
    """

    def setUp(self):
        self.policy = complete_policy()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.cli_binary = root / "provider-cli.exe"
        self.interpreter = root / "node.exe"
        self.module = root / "acp-server.js"
        for fixture in (self.cli_binary, self.interpreter, self.module):
            fixture.write_text("", encoding="utf-8")
        for provider in ("anthropic", "openai"):
            entry = self.policy["providers"][provider]
            entry["source"]["command"] = str(self.cli_binary)
            entry["launch"] = {"acp": {"command": str(self.interpreter), "module": str(self.module)}}

    def test_acp_launch_runs_the_bound_interpreter_against_the_bound_module(self):
        self.assertEqual(
            [str(self.interpreter), str(self.module), "--flag"],
            qm.resolve_launch_command(self.policy, "anthropic", ["--flag"], "acp"),
        )

    def test_each_engine_uses_only_its_own_binding(self):
        # The CLI engine never reaches for the ACP binding...
        self.assertEqual([str(self.cli_binary)], qm.resolve_launch_command(self.policy, "anthropic", [], "cli"))
        # ...and an agent on the ACP engine is denied rather than silently handed
        # the command-line tool, which is not an ACP server and would hang.
        del self.policy["providers"]["anthropic"]["launch"]
        self.assertIsNone(qm.resolve_launch_command(self.policy, "anthropic", [], "acp"))

    def test_cli_engine_still_launches_when_only_the_acp_binding_is_absent(self):
        del self.policy["providers"]["openai"]["launch"]
        self.assertEqual([str(self.cli_binary)], qm.resolve_launch_command(self.policy, "openai", [], "cli"))

    def test_a_moved_acp_install_is_unresolved_rather_than_retried_through_path(self):
        for key, replacement in (("command", "node"), ("module", str(self.module) + ".missing")):
            with self.subTest(key=key):
                binding = dict(self.policy["providers"]["anthropic"]["launch"]["acp"], **{key: replacement})
                self.policy["providers"]["anthropic"]["launch"] = {"acp": binding}
                self.assertIsNone(qm.resolve_launch_command(self.policy, "anthropic", [], "acp"))

    def test_blank_and_missing_acp_binding_values_are_unresolved(self):
        for binding in ({}, {"command": None, "module": None}, {"command": "   ", "module": "   "}):
            with self.subTest(binding=binding):
                self.policy["providers"]["anthropic"]["launch"] = {"acp": binding}
                self.assertIsNone(qm.resolve_launch_command(self.policy, "anthropic", [], "acp"))

    def test_an_unrecognized_engine_launches_nothing(self):
        self.assertIsNone(qm.resolve_launch_command(self.policy, "anthropic", [], "unknown-engine"))

    def test_excluded_provider_has_no_acp_launch(self):
        self.assertIsNone(qm.resolve_launch_command(self.policy, "ollama", [], "acp"))

    def _run_exec(self, state: dict | None, argv_extra: list[str], policy_text: str | None = None) -> tuple[int, list[str] | None, str]:
        root = Path(self.directory.name)
        policy_path, state_path = root / "policy.json", root / "state.json"
        policy_path.write_text(policy_text if policy_text is not None else json.dumps(self.policy), encoding="utf-8")
        if state is not None:
            state_path.write_text(json.dumps(state), encoding="utf-8")
        launched: list[str] | None = None

        def fake_run(command, check=False):
            nonlocal launched
            launched = command
            return type("Completed", (), {"returncode": 0})()

        argv = ["exec", "--policy", str(policy_path), "--state", str(state_path), *argv_extra]
        stdout = io.StringIO()
        with patch.object(qm.subprocess, "run", fake_run), patch.object(qm.sys, "stdout", stdout):
            code = qm.command_main(argv)
        return code, launched, stdout.getvalue()

    def test_allow_starts_the_acp_server(self):
        state = fresh_state(self.policy, now=qm.utc_now())
        code, launched, _ = self._run_exec(state, ["--provider", "anthropic", "--engine", "acp"])
        self.assertEqual(0, code)
        self.assertEqual([str(self.interpreter), str(self.module)], launched)

    def test_stale_state_never_starts_the_acp_server(self):
        stale = fresh_state(self.policy, now=qm.utc_now() - dt.timedelta(hours=13))
        code, launched, _ = self._run_exec(stale, ["--provider", "anthropic", "--engine", "acp"])
        self.assertEqual(75, code)
        self.assertIsNone(launched)

    def test_missing_state_never_starts_the_acp_server(self):
        code, launched, _ = self._run_exec(None, ["--provider", "anthropic", "--engine", "acp"])
        self.assertEqual(75, code)
        self.assertIsNone(launched)

    def test_exec_defaults_to_the_cli_engine(self):
        state = fresh_state(self.policy, now=qm.utc_now())
        code, launched, _ = self._run_exec(state, ["--provider", "anthropic", "--", "--version"])
        self.assertEqual(0, code)
        self.assertEqual([str(self.cli_binary), "--version"], launched)

    def test_exec_keeps_stdout_clear_so_it_cannot_corrupt_the_acp_protocol(self):
        # `exec` hands its stdout to the launched program, and for the ACP engine
        # that stream carries newline-delimited JSON-RPC. Any guard diagnostic
        # written there would be read as a protocol message.
        fresh, stale = fresh_state(self.policy, now=qm.utc_now()), fresh_state(self.policy, now=qm.utc_now() - dt.timedelta(hours=13))
        cases = (
            ("allowed", fresh, None, 0),
            ("denied", stale, None, 75),
            ("unresolved launch", fresh, json.dumps({**self.policy, "providers": {**self.policy["providers"], "anthropic": {**self.policy["providers"]["anthropic"], "launch": {}}}}), 64),
            ("malformed policy", fresh, "{ not json", 78),
        )
        for label, state, policy_text, expected_code in cases:
            with self.subTest(case=label):
                code, _, stdout = self._run_exec(state, ["--provider", "anthropic", "--engine", "acp"], policy_text)
                self.assertEqual(expected_code, code)
                self.assertEqual("", stdout)


class GuardWrapperTests(unittest.TestCase):
    """Each wrapper must keep the basename its engine recognizes.

    Paperclip's Claude adapter applies its minimum-CLI-version preflight only
    when the configured command's basename is the provider's own, and acpx
    identifies an ACP lane by basename with the extension stripped. A rename
    would silently drop that handling, so the names are asserted here.
    """

    WRAPPERS = {
        "claude.cmd": ("anthropic", "cli"),
        "codex.cmd": ("openai", "cli"),
        "claude-agent-acp.cmd": ("anthropic", "acp"),
        "codex-acp.cmd": ("openai", "acp"),
    }

    def wrapper_text(self, name: str) -> str:
        path = Path(__file__).parents[1] / "host" / "bin" / name
        self.assertTrue(path.is_file(), f"{name} is missing")
        return path.read_text(encoding="ascii")

    def test_every_wrapper_guards_its_own_provider_and_engine(self):
        for name, (provider, engine) in self.WRAPPERS.items():
            with self.subTest(wrapper=name):
                text = self.wrapper_text(name)
                self.assertIn(f"--provider {provider}", text)
                # The CLI engine is `exec`'s default, so only ACP names itself.
                self.assertEqual(engine == "acp", "--engine acp" in text)

    def test_no_wrapper_carries_a_policy_value_of_its_own(self):
        for name in self.WRAPPERS:
            with self.subTest(wrapper=name):
                text = self.wrapper_text(name)
                self.assertIn("policy.json", text)
                for policy_token in ("pollInterval", "staleAfter", "amberAtOrAbove", "redAtOrAbove", "reserve", "timeoutSeconds"):
                    self.assertNotIn(policy_token, text)


SERVICE_PATH = Path(__file__).parents[1] / "monitor-service.py"
SERVICE_SPEC = importlib.util.spec_from_file_location("monitor_service", SERVICE_PATH)
svc = importlib.util.module_from_spec(SERVICE_SPEC)
assert SERVICE_SPEC and SERVICE_SPEC.loader
SERVICE_SPEC.loader.exec_module(svc)


class MonitorServiceTests(unittest.TestCase):
    """The scheduled-task host must stay a thin, policy-free wrapper."""

    def test_argv_targets_the_canonical_company_paths(self):
        company = Path("root") / "companies" / "company-id"
        self.assertEqual(
            ["monitor", "--policy", str(company / "policy.json"), "--state", str(company / "state.json"),
             "--events", str(company / "control-events.jsonl")],
            svc.monitor_argv(company),
        )

    def test_missing_policy_exits_configuration_incomplete_without_looping(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(svc, "ROOT", Path(tmp)), patch.object(svc, "command_main", create=True) as never:
                self.assertEqual(78, svc.main(["--company", "absent-company"]))
            never.assert_not_called()

    def test_log_rotates_once_above_the_cap_and_is_left_alone_below_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "monitor.log"
            log.write_text("x" * 32, encoding="utf-8")
            svc.rotate_log(log, max_bytes=1024)
            self.assertTrue(log.is_file())
            self.assertFalse(log.with_suffix(".log.1").is_file())
            log.write_text("y" * 2048, encoding="utf-8")
            svc.rotate_log(log, max_bytes=1024)
            self.assertFalse(log.is_file())
            self.assertEqual("y" * 2048, log.with_suffix(".log.1").read_text(encoding="utf-8"))

    def test_the_service_never_supplies_a_policy_value(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        for policy_token in ("pollInterval", "staleAfter", "amberAtOrAbove", "redAtOrAbove", "reserve", "timeoutSeconds"):
            self.assertNotIn(policy_token, source)


# Every field a failed probe is permitted to retain. Anything outside this set has
# not been reviewed for secret safety, so both the implementation and the published
# state schema are held to it.
DIAGNOSTIC_KEYS = (
    "rateLimitsAvailable", "rateLimitsKind", "planWindows", "planWindowUtilization",
    "jsonLines", "controlResponses", "controlResponseSubtypes", "failureClassification",
    "successResponseKind", "exitCode", "stderr", "failureClass", "errno",
)

SECRETS = {
    "anthropic_key": "sk-ant-api03-ZmFrZUtleU5vdFJlYWxOb3RSZWFsMTIzNDU2Nzg5",
    "bearer": "Bearer fakeSessionValueNotReal0123456789",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJub3QtcmVhbCJ9.c2lnbmF0dXJlTm90UmVhbA",
    "env_token": "CLAUDE_CODE_MESSAGING_TOKEN=fake-messaging-token-not-real",
    "json_token": '"access_token": "fake-access-value-not-real"',
    "email": "investigator@fraud-investigation.invalid",
}


class RecordingStderrStream:
    """Fixture stream that exposes whether a consumer uses bounded reads."""

    def __init__(self, text, iteration_fragment_size=None, fail_after_reads=None):
        self.text = text
        self.offset = 0
        self.iterated = False
        self.iteration_fragment_size = iteration_fragment_size or len(text) or 1
        self.fail_after_reads = fail_after_reads
        self.read_sizes = []
        self.returned_sizes = []

    def __iter__(self):
        self.iterated = True
        for start in range(0, len(self.text), self.iteration_fragment_size):
            yield self.text[start:start + self.iteration_fragment_size]

    def read(self, size=-1):
        if self.fail_after_reads is not None and len(self.read_sizes) >= self.fail_after_reads:
            raise OSError("synthetic partial read")
        self.read_sizes.append(size)
        if self.offset >= len(self.text):
            self.returned_sizes.append(0)
            return ""
        end = len(self.text) if size < 0 else min(len(self.text), self.offset + size)
        result = self.text[self.offset:end]
        self.offset = end
        self.returned_sizes.append(len(result))
        return result


class FakeProbeProcess:
    """Popen stand-in that also presents the captured stderr stream."""

    def __init__(self, stdout_lines, stderr_text="", returncode=0, stderr_stream=None):
        self.stdin = io.StringIO()
        self.stdout = iter(stdout_lines)
        self.stderr = stderr_stream if stderr_stream is not None else io.StringIO(stderr_text)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass

    def wait(self):
        return self.returncode


def control_response(payload: dict | None = None, subtype: str = "success", **extra) -> dict:
    response = {"request_id": "quota-manager-get-usage", "subtype": subtype, **extra}
    if payload is not None:
        response["response"] = payload
    return {"type": "control_response", "response": response}


class ProbeProcessLaunchTests(unittest.TestCase):
    """Telemetry probes must stay windowless on Windows without changing transport."""

    CREATE_NO_WINDOW = 0x08000000

    def probe(self, provider: str, platform: str) -> tuple[list[str], dict]:
        if provider == "anthropic":
            emitted = [control_response({
                "subscription_type": "pro",
                "rate_limits_available": True,
                "rate_limits": {
                    "five_hour": {"utilization": 12, "resets_at": "2030-01-01T01:00:00Z"},
                    "seven_day": {"utilization": 34, "resets_at": "2030-01-02T00:00:00Z"},
                },
            })]
        else:
            emitted = [{
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "ordinaryUsageAllowed": True,
                    "rateLimits": {
                        "primary": {"usedPercent": 23, "windowDurationMins": 300, "resetsAt": 1},
                        "secondary": {"usedPercent": 45, "windowDurationMins": 10080, "resetsAt": 2},
                    },
                },
            }]
        captured: dict = {}

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return FakeProbeProcess([json.dumps(item) + "\n" for item in emitted])

        # A plain dict stands in for the process environment. patch.dict's teardown
        # clears os.environ and re-sets every variable through putenv, which raises
        # ValueError on Windows for any variable longer than 32767 characters - the
        # agent runtime holds one. The module only reads os.environ.copy(), so a dict
        # keeps the intent (credentials present in the parent environment) without
        # ever writing to the real environment.
        environment = dict(qm.os.environ)
        environment.update({
            "ANTHROPIC_API_KEY": "synthetic-key-that-must-not-reach-claude",
            "CLAUDE_CODE_MESSAGING_TOKEN": "synthetic-token-that-must-not-reach-claude",
        })
        with (
            patch.object(qm.sys, "platform", platform),
            patch.object(qm.subprocess, "CREATE_NO_WINDOW", self.CREATE_NO_WINDOW, create=True),
            patch.object(qm.os, "environ", environment),
            patch.object(qm.subprocess, "Popen", fake_popen),
        ):
            qm.run_probe(provider, complete_policy()["providers"][provider])
        return captured["command"], captured["kwargs"]

    def assert_transport_unchanged(self, kwargs: dict) -> None:
        self.assertIs(qm.subprocess.PIPE, kwargs["stdin"])
        self.assertIs(qm.subprocess.PIPE, kwargs["stdout"])
        self.assertIs(qm.subprocess.PIPE, kwargs["stderr"])
        self.assertIs(True, kwargs["text"])
        self.assertNotIn("shell", kwargs)

    def test_windows_probes_use_create_no_window_without_changing_transport_or_environment(self):
        expected_commands = {
            "anthropic": ["fixture-command", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
            "openai": ["fixture-command", "-s", "read-only", "-a", "never", "app-server", "--stdio"],
        }
        for provider in ("anthropic", "openai"):
            with self.subTest(provider=provider):
                command, kwargs = self.probe(provider, "win32")
                self.assertEqual(expected_commands[provider], command)
                self.assertEqual(self.CREATE_NO_WINDOW, kwargs["creationflags"])
                self.assert_transport_unchanged(kwargs)
                if provider == "anthropic":
                    self.assertEqual("fixture-profile", kwargs["env"]["CLAUDE_CONFIG_DIR"])
                    self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
                    self.assertNotIn("CLAUDE_CODE_MESSAGING_TOKEN", kwargs["env"])
                else:
                    self.assertEqual("fixture-profile", kwargs["env"]["CODEX_HOME"])

    def test_non_windows_probe_does_not_receive_windows_process_flags(self):
        _command, kwargs = self.probe("openai", "linux")
        self.assertNotIn("creationflags", kwargs)
        self.assertNotIn("startupinfo", kwargs)
        self.assert_transport_unchanged(kwargs)
        self.assertEqual("fixture-profile", kwargs["env"]["CODEX_HOME"])

    def test_the_probe_fixture_never_writes_to_the_real_process_environment(self):
        """Writing to os.environ calls putenv, which fails on Windows for a variable
        longer than 32767 characters, so the fixture must only ever read it."""

        class ReadOnlyEnviron(dict):
            def __setitem__(self, key, value):
                raise AssertionError(f"wrote {key} to the real environment")

            def __delitem__(self, key):
                raise AssertionError(f"deleted {key} from the real environment")

            def clear(self):
                raise AssertionError("cleared the real environment")

            def update(self, *args, **kwargs):
                raise AssertionError("updated the real environment")

        with patch.object(qm.os, "environ", ReadOnlyEnviron(qm.os.environ)):
            _command, kwargs = self.probe("openai", "linux")
        self.assertEqual("fixture-profile", kwargs["env"]["CODEX_HOME"])


class FailedProbeDiagnosticTests(unittest.TestCase):
    """A failed Claude usage probe must stay UNAVAILABLE while preserving enough
    structure to classify the telemetry failure, and must retain no secret, no raw
    provider response, and no unbounded text."""

    def probe(self, emitted, stderr="", returncode=0, provider="anthropic", stderr_stream=None):
        """Run one probe against a fixture process; return (outcome, popen_calls)."""
        calls: list[list[str]] = []

        def fake_popen(command, **_kwargs):
            calls.append(command)
            return FakeProbeProcess(
                [json.dumps(item) + chr(10) for item in emitted],
                stderr,
                returncode,
                stderr_stream,
            )

        config = complete_policy()["providers"][provider]
        with patch.object(qm.subprocess, "Popen", fake_popen):
            try:
                return qm.run_probe(provider, config), calls
            except qm.QuotaError as error:
                return error, calls

    def failure(self, emitted, stderr="", returncode=0):
        outcome, calls = self.probe(emitted, stderr, returncode)
        self.assertIsInstance(outcome, qm.QuotaError, "fixture was expected to fail the probe")
        return outcome, calls

    # --- structural classification of an unusable snapshot -------------------

    def test_null_rate_limits_is_unavailable_and_recorded_structurally(self):
        # The directly observed AXI-52 shape: available true, limits null.
        error, _ = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})])
        self.assertEqual("CLAUDE_LIMITS_UNAVAILABLE", error.code)
        self.assertEqual("UNAVAILABLE", error.health)
        self.assertIs(True, error.diagnostic["rateLimitsAvailable"])
        self.assertEqual("null", error.diagnostic["rateLimitsKind"])

    def test_rate_limits_shape_is_named_without_retaining_its_value(self):
        for payload, expected in (
            ({"rate_limits_available": True, "rate_limits": "not-a-snapshot"}, "string"),
            ({"rate_limits_available": True}, "absent"),
            ({"rate_limits_available": False, "rate_limits": []}, "array"),
            ({"rate_limits_available": None, "rate_limits": 7}, "number"),
        ):
            with self.subTest(expected=expected):
                error, _ = self.failure([control_response(payload)])
                self.assertEqual("CLAUDE_LIMITS_UNAVAILABLE", error.code)
                self.assertEqual(expected, error.diagnostic["rateLimitsKind"])
                self.assertNotIn("not-a-snapshot", json.dumps(error.diagnostic))

    def test_non_scalar_availability_flag_is_reduced_to_its_shape(self):
        error, _ = self.failure([control_response({"rate_limits_available": {"reason": "degraded-upstream"}, "rate_limits": None})])
        self.assertEqual("object", error.diagnostic["rateLimitsAvailable"])
        self.assertNotIn("degraded-upstream", json.dumps(error.diagnostic))

    def test_unusable_plan_windows_are_described_per_window(self):
        error, _ = self.failure([control_response({
            "rate_limits_available": True,
            "rate_limits": {"five_hour": {"utilization": None}, "seven_day": "unexpected"},
        })])
        self.assertEqual("CLAUDE_WINDOWS_MALFORMED", error.code)
        self.assertEqual("MALFORMED", error.health)
        self.assertEqual({"five_hour": "object", "seven_day": "string"}, error.diagnostic["planWindows"])
        self.assertEqual({"five_hour": "null"}, error.diagnostic["planWindowUtilization"])

    def test_transport_shape_is_counted_when_no_success_response_arrives(self):
        error, _ = self.failure([{"type": "system", "subtype": "init"}, control_response(subtype="error")])
        self.assertEqual("CLAUDE_RESPONSE_MISSING", error.code)
        self.assertEqual("MALFORMED", error.health)
        self.assertEqual(2, error.diagnostic["jsonLines"])
        self.assertEqual(1, error.diagnostic["controlResponses"])
        self.assertEqual(["error"], error.diagnostic["controlResponseSubtypes"])
        # "null" = no success response ever arrived, as distinct from one that
        # arrived with an unusable shape (covered below).
        self.assertEqual("null", error.diagnostic["successResponseKind"])

    def test_control_response_subtypes_are_capped_in_first_seen_order(self):
        subtypes = [f"failure-{index:02d}" for index in range(25)]
        stream = "\n".join(json.dumps(control_response(subtype=value)) for value in subtypes)
        with self.assertRaises(qm.QuotaError) as caught:
            qm.parse_claude_output(stream)
        retained = caught.exception.diagnostic["controlResponseSubtypes"]
        self.assertEqual(subtypes[:20], retained)

    def test_a_success_response_of_the_wrong_shape_is_distinguishable(self):
        error, _ = self.failure([control_response("rate limits unavailable")])
        self.assertEqual("CLAUDE_RESPONSE_MISSING", error.code)
        self.assertEqual("string", error.diagnostic["successResponseKind"])
        self.assertNotIn("rate limits unavailable", json.dumps(error.diagnostic))

    def test_provider_failure_classification_is_kept_bounded_and_redacted(self):
        message = f"usage fetch rejected for {SECRETS['anthropic_key']}; " + "retry later. " * 60
        error, _ = self.failure([control_response(subtype="error", error={"message": message})])
        classification = error.diagnostic["failureClassification"]
        self.assertIn("usage fetch rejected", classification)
        self.assertNotIn(SECRETS["anthropic_key"], classification)
        self.assertTrue(classification.endswith("...[truncated]"))
        self.assertLessEqual(len(classification), qm.MESSAGE_DIAGNOSTIC_LIMIT + len("...[truncated]"))

    # --- secret safety ------------------------------------------------------

    def test_stderr_diagnostic_is_redacted_of_every_credential_shape(self):
        stderr = "".join(f"usage fetch failed: {value}{chr(10)}" for value in SECRETS.values())
        error, _ = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})], stderr=stderr)
        retained = error.diagnostic["stderr"]
        self.assertIn("usage fetch failed", retained)
        for name, value in SECRETS.items():
            with self.subTest(secret=name):
                self.assertNotIn(value, retained)
        self.assertNotIn("sk-ant", retained)
        self.assertNotIn("eyJ", retained)

    def test_the_raw_provider_response_is_never_retained(self):
        error, _ = self.failure([control_response({
            "rate_limits_available": True,
            "rate_limits": None,
            "oauth_account": {"email_address": SECRETS["email"], "access_token": SECRETS["bearer"]},
            "subscription_type": "max",
        })])
        serialised = json.dumps(error.diagnostic)
        for value in (SECRETS["email"], SECRETS["bearer"], "oauth_account", "max"):
            self.assertNotIn(value, serialised)

    def test_only_allowlisted_diagnostic_keys_reach_the_record(self):
        allowed = set(DIAGNOSTIC_KEYS)
        for emitted in (
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            [control_response({"rate_limits_available": True, "rate_limits": {"five_hour": {}}})],
            [control_response(subtype="error", error={"code": "usage_unavailable"})],
        ):
            error, _ = self.failure(emitted, stderr="some warning")
            self.assertLessEqual(set(error.diagnostic), allowed, error.code)

    def test_execution_failure_keeps_only_the_error_class(self):
        def exploding_popen(_command, **_kwargs):
            raise FileNotFoundError(2, "cannot find C:\\Users\\User\\.claude\\credentials.json")

        config = complete_policy()["providers"]["anthropic"]
        with patch.object(qm.subprocess, "Popen", exploding_popen):
            with self.assertRaises(qm.QuotaError) as caught:
                qm.run_probe("anthropic", config)
        self.assertEqual("PROBE_EXECUTION_FAILED", caught.exception.code)
        self.assertEqual({"failureClass": "FileNotFoundError", "errno": 2}, caught.exception.diagnostic)

    # --- bounding -----------------------------------------------------------

    def test_stderr_diagnostic_is_truncated_to_the_retention_limit(self):
        stderr = "usage fetch failed; the CLI said nothing useful. " * 400
        error, _ = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})], stderr=stderr)
        retained = error.diagnostic["stderr"]
        self.assertTrue(retained.endswith("...[truncated]"))
        self.assertLessEqual(len(retained), qm.STDERR_DIAGNOSTIC_LIMIT + len("...[truncated]"))

    def test_stderr_capture_is_capped_before_any_retention_decision(self):
        stderr = "".join(f"quota probe warning line {index}{chr(10)}" for index in range(5000))
        self.assertGreater(len(stderr), qm.STDERR_CAPTURE_LIMIT * 10)
        with patch.object(qm, "STDERR_DIAGNOSTIC_LIMIT", 10 ** 7):
            error, _ = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})], stderr=stderr)
        self.assertLessEqual(len(error.diagnostic["stderr"]), qm.STDERR_CAPTURE_LIMIT)

    def test_oversized_unterminated_stderr_uses_only_bounded_reads(self):
        read_size = 256
        self.assertEqual(read_size, qm.STDERR_READ_CHUNK_SIZE)
        stream = RecordingStderrStream("ordinary warning " * (qm.STDERR_CAPTURE_LIMIT * 8))
        outcome, _ = self.probe(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr_stream=stream,
        )
        self.assertIsInstance(outcome, qm.QuotaError)
        self.assertFalse(stream.iterated)
        self.assertTrue(stream.read_sizes)
        self.assertTrue(all(size == read_size for size in stream.read_sizes))
        self.assertLessEqual(max(stream.returned_sizes), read_size)
        self.assertLessEqual(len(outcome.diagnostic["stderr"]), qm.STDERR_DIAGNOSTIC_LIMIT + len("...[truncated]"))

    def test_credential_crossing_an_arbitrary_read_boundary_is_redacted(self):
        read_size = 256
        target = SECRETS["anthropic_key"]
        stderr = ("." * (read_size - 5)) + target + " rejected"
        stream = RecordingStderrStream(stderr, iteration_fragment_size=read_size)
        outcome, _ = self.probe(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr_stream=stream,
        )
        self.assertIsInstance(outcome, qm.QuotaError)
        retained = outcome.diagnostic["stderr"]
        self.assertNotIn(target, retained)
        self.assertNotIn(target[:10], retained)
        self.assertNotIn(target[-10:], retained)

    def test_cross_chunk_shrinkage_cannot_expose_a_capture_boundary_fragment(self):
        read_size = 256
        target = SECRETS["anthropic_key"]
        authorization_prefix = "Bearer "
        cross_chunk_secret = (
            ("." * (read_size - len(authorization_prefix)))
            + authorization_prefix
            + ("x." * 3700)
            + " "
        )
        target_prefix_length = 10
        filler = "." * (
            qm.STDERR_CAPTURE_LIMIT
            - target_prefix_length
            - len(cross_chunk_secret)
        )
        stderr = cross_chunk_secret + filler + target + " rejected"
        stream = RecordingStderrStream(stderr, iteration_fragment_size=read_size)
        outcome, _ = self.probe(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr_stream=stream,
        )
        self.assertIsInstance(outcome, qm.QuotaError)
        retained = outcome.diagnostic["stderr"]
        self.assertNotIn(target[:target_prefix_length], retained)
        self.assertNotIn(target, retained)

    def test_partial_capture_after_read_failure_is_boundary_redacted(self):
        read_size = qm.STDERR_READ_CHUNK_SIZE
        target = SECRETS["anthropic_key"]
        shrinking_secret = "sk-" + ("A" * 500) + " "
        target_prefix_length = 10
        filler = "." * ((read_size * 3) - len(shrinking_secret) - target_prefix_length)
        stderr = shrinking_secret + filler + target + " rejected"
        stream = RecordingStderrStream(stderr, fail_after_reads=3)
        outcome, _ = self.probe(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr_stream=stream,
        )
        self.assertIsInstance(outcome, qm.QuotaError)
        retained = outcome.diagnostic["stderr"]
        self.assertNotIn(target[:target_prefix_length], retained)
        self.assertNotIn(target, retained)

    def test_a_secret_crossing_the_retained_diagnostic_boundary_is_redacted(self):
        # Redaction precedes the retained-diagnostic bound, so a credential crossing
        # that boundary is replaced rather than cut in half and kept.
        prefix = "warning. " * ((qm.STDERR_DIAGNOSTIC_LIMIT // 9) - 1)
        error, _ = self.failure(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr=prefix + SECRETS["anthropic_key"] + " rejected",
        )
        retained = error.diagnostic["stderr"]
        self.assertNotIn("sk-ant", retained)
        for length in range(12, len(SECRETS["anthropic_key"])):
            self.assertNotIn(SECRETS["anthropic_key"][:length], retained)

    def test_redaction_precedes_the_raw_capture_boundary(self):
        target = SECRETS["anthropic_key"]
        shrinking_secret = "sk-" + ("A" * 7400)
        target_prefix_length = 10
        filler = "." * (
            qm.STDERR_CAPTURE_LIMIT
            - target_prefix_length
            - len(shrinking_secret)
            - 1
        )
        stderr = shrinking_secret + " " + filler + target + " rejected\n"
        target_start = stderr.index(target)
        self.assertLess(target_start, qm.STDERR_CAPTURE_LIMIT)
        self.assertGreater(target_start + len(target), qm.STDERR_CAPTURE_LIMIT)

        error, _ = self.failure(
            [control_response({"rate_limits_available": True, "rate_limits": None})],
            stderr=stderr,
        )
        retained = error.diagnostic["stderr"]
        self.assertNotIn(target[:target_prefix_length], retained)
        self.assertNotIn(target, retained)

    def test_boundary_marker_room_is_not_created_inside_an_earlier_credential(self):
        target = "sk-ABCDEFGH"
        exposed_prefix_length = len(target) - 1
        secondary_cut = qm.STDERR_CAPTURE_LIMIT - len(qm.STDERR_CAPTURE_BOUNDARY_REPLACEMENT)
        prefix = "." * (secondary_cut - exposed_prefix_length)
        before_tail = prefix + target + " "
        captured = before_tail + (" " * (qm.STDERR_CAPTURE_LIMIT - len(before_tail) - 1)) + "x"
        self.assertEqual(qm.STDERR_CAPTURE_LIMIT, len(captured))

        with patch.object(qm, "STDERR_DIAGNOSTIC_LIMIT", 10 ** 7):
            error, _ = self.failure(
                [control_response({"rate_limits_available": True, "rate_limits": None})],
                stderr=captured + "overflow",
            )

        retained = error.diagnostic["stderr"]
        self.assertNotIn(target[:exposed_prefix_length], retained)
        self.assertNotIn(target, retained)
        self.assertLessEqual(len(retained), qm.STDERR_CAPTURE_LIMIT)

    def test_nonzero_exit_keeps_bounded_transport_evidence(self):
        error, _ = self.failure([], stderr=f"login expired {SECRETS['jwt']}", returncode=3)
        self.assertEqual("PROBE_NONZERO_EXIT", error.code)
        self.assertEqual("UNAVAILABLE", error.health)
        self.assertEqual(3, error.diagnostic["exitCode"])
        self.assertIn("login expired", error.diagnostic["stderr"])
        self.assertNotIn(SECRETS["jwt"], error.diagnostic["stderr"])

    def test_silent_stderr_is_recorded_as_absent_rather_than_empty_text(self):
        error, _ = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})], stderr="   \n")
        self.assertIsNone(error.diagnostic["stderr"])

    # --- the diagnostic changes nothing else --------------------------------

    def test_a_failed_probe_is_not_retried_or_re_probed(self):
        _, calls = self.failure([control_response({"rate_limits_available": True, "rate_limits": None})], stderr="x")
        self.assertEqual(1, len(calls), "a failed probe must not trigger a retry or recovery probe")

    @patch.object(qm, "fetch_active_consumers")
    def test_diagnostics_are_not_capacity_and_do_not_refresh_trust(self, consumers):
        policy, now = complete_policy(), dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        consumers.return_value = {"anthropic": [], "openai": []}
        with patch.object(qm, "run_probe", succeeding_probe(1.0)):
            good = qm.observe(policy, now)
        diagnosed = qm.QuotaError(
            "CLAUDE_LIMITS_UNAVAILABLE", "Claude rate limits were not available",
            diagnostic={"rateLimitsAvailable": True, "rateLimitsKind": "null"},
        )
        with patch.object(qm, "run_probe", lambda *_args: (_ for _ in ()).throw(diagnosed)):
            after = qm.observe(policy, now + dt.timedelta(seconds=60), previous=good)
        record = after["providers"]["anthropic"]
        self.assertEqual("UNKNOWN", record["state"])
        self.assertEqual("UNAVAILABLE", record["health"])
        self.assertEqual("null", record["error"]["diagnostic"]["rateLimitsKind"])
        # The retained reading still dates from the successful probe, not this one.
        self.assertEqual(good["providers"]["anthropic"]["observedAt"], record["telemetry"]["lastTrustworthyAt"])
        self.assertIsNone(record["signal"])
        self.assertEqual("DENY", qm.guard_decision(policy, after, "anthropic", "new", now + dt.timedelta(seconds=60))["decision"])

    def test_a_diagnosed_failure_still_follows_the_approved_grace_window(self):
        policy, now = complete_policy(), dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        state = fresh_state(policy, "GREEN", now)
        state["providers"]["anthropic"].update({
            "health": "UNAVAILABLE", "state": "UNKNOWN", "signal": None,
            "error": {"code": "CLAUDE_LIMITS_UNAVAILABLE", "message": "Claude rate limits were not available",
                      "diagnostic": {"rateLimitsAvailable": True, "rateLimitsKind": "null", "stderr": None}},
            "telemetry": {"probedAt": qm.iso(now), "health": "UNAVAILABLE", "lastTrustworthyAt": qm.iso(now),
                          "lastTrustworthyState": "GREEN", "lastTrustworthyCausingWindows": ["five_hour"]},
        })
        inside = qm.guard_decision(policy, state, "anthropic", "active", now + dt.timedelta(seconds=60))
        self.assertEqual("ALLOW", inside["decision"])
        outside = qm.guard_decision(policy, state, "anthropic", "active", now + dt.timedelta(seconds=121))
        self.assertEqual("CHECKPOINT_STOP", outside["decision"])
        self.assertEqual("STATE_STALE", outside["reason"])

    def test_the_published_schema_matches_the_implemented_bounds(self):
        schema = json.loads((MODULE_PATH.parent / "shared-state.schema.json").read_text(encoding="utf-8"))
        diagnostic = schema["$defs"]["provider"]["properties"]["error"]["properties"]["diagnostic"]["properties"]
        self.assertEqual(set(DIAGNOSTIC_KEYS), set(diagnostic))
        marker = len("...[truncated]")
        self.assertEqual(qm.STDERR_DIAGNOSTIC_LIMIT + marker, diagnostic["stderr"]["maxLength"])
        self.assertEqual(qm.MESSAGE_DIAGNOSTIC_LIMIT + marker, diagnostic["failureClassification"]["maxLength"])
        self.assertEqual(20, qm.CONTROL_RESPONSE_SUBTYPES_LIMIT)
        self.assertEqual(qm.CONTROL_RESPONSE_SUBTYPES_LIMIT, diagnostic["controlResponseSubtypes"]["maxItems"])

    def test_a_successful_probe_carries_no_diagnostic(self):
        outcome, _ = self.probe([control_response({
            "rate_limits_available": True,
            "rate_limits": {"five_hour": {"utilization": 12.5}, "seven_day": {"utilization": 3}},
        })])
        self.assertNotIsInstance(outcome, qm.QuotaError)
        self.assertEqual([12.5, 3.0], [window["value"] for window in outcome["windows"]])


if __name__ == "__main__":
    unittest.main()
