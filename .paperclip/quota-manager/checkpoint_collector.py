#!/usr/bin/env python3
"""Create a deterministic continuation checkpoint from persisted pause evidence.

This collector never calls a model or interprets free-form run output.  It copies
explicitly persisted identity and status facts, carries existing continuation
text as quoted evidence, and leaves unsupported conclusions as ``unknown``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


class CheckpointError(Exception):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def interruption_id(company_id: str, provider: str, agent_id: str, runs: list[dict[str, str]]) -> str:
    identities = sorted(
        {f"{item['taskId']}:{item['runId']}" for item in runs},
    )
    material = "\n".join(["quota-pause-v1", company_id, provider, agent_id, *identities])
    return "quota-pause-v1-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _nonempty(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _evidence_ref(kind: str, identity: str, pointer: str = "") -> str:
    return f"{kind}:{identity}{pointer}"


def build_checkpoint(
    evidence: dict[str, Any], *, task_id: str, run_id: str, agent_id: str
) -> dict[str, Any]:
    event = evidence.get("controlEvent")
    run = evidence.get("run")
    issue = evidence.get("issue")
    if not all(isinstance(item, dict) for item in (event, run, issue)):
        raise CheckpointError("evidence must contain controlEvent, run, and issue objects")

    observed_task_id = _nonempty(issue.get("id"))
    observed_run_id = _nonempty(run.get("id"))
    observed_agent_id = _nonempty(run.get("agentId"))
    event_agent_id = _nonempty(event.get("agentId"))
    if observed_task_id != task_id:
        raise CheckpointError("task identity does not match persisted issue evidence")
    if observed_run_id != run_id:
        raise CheckpointError("run identity does not match persisted run evidence")
    if observed_agent_id != agent_id or event_agent_id != agent_id:
        raise CheckpointError("agent identity does not match persisted run/control evidence")

    context = run.get("contextSnapshot") if isinstance(run.get("contextSnapshot"), dict) else {}
    context_task_id = _nonempty(context.get("issueId")) or _nonempty(context.get("taskId"))
    if context_task_id != task_id:
        raise CheckpointError("run context does not identify the supplied task")

    receipt = event.get("receipt") if isinstance(event.get("receipt"), dict) else {}
    pause_confirmed = (
        event.get("phase") == "result"
        and event.get("outcome") == "paused"
        and receipt.get("agentId") == agent_id
        and receipt.get("agentStatus") == "paused"
    )

    refs = [
        {
            "kind": "quota_control_event",
            "ref": _evidence_ref("quota-control-event", str(event.get("eventId")), "#/result"),
        },
        {"kind": "paperclip_run", "ref": _evidence_ref("paperclip-run", run_id)},
        {"kind": "paperclip_issue", "ref": _evidence_ref("paperclip-issue", task_id)},
    ]

    continuation = context.get("paperclipContinuationSummary")
    observed_continuation: dict[str, Any]
    if isinstance(continuation, dict) and _nonempty(continuation.get("body")):
        continuation_ref = _evidence_ref(
            "paperclip-run", run_id, "#/contextSnapshot/paperclipContinuationSummary/body"
        )
        refs.append({"kind": "paperclip_continuation_summary", "ref": continuation_ref})
        observed_continuation = {
            "status": "observed",
            "text": continuation["body"],
            "evidenceRef": continuation_ref,
            "interpretation": "none",
        }
    else:
        observed_continuation = {
            "status": "unknown",
            "text": None,
            "evidenceRef": None,
            "reason": "No persisted Paperclip continuation summary was present.",
        }

    allowed_refs = {entry["ref"] for entry in refs}
    completed_items = []
    raw_completed = evidence.get("verifiedCompletedWork")
    if isinstance(raw_completed, list):
        for item in raw_completed:
            if not isinstance(item, dict):
                continue
            description = _nonempty(item.get("description"))
            item_refs = item.get("evidenceRefs")
            if (
                description
                and isinstance(item_refs, list)
                and item_refs
                and all(ref in allowed_refs for ref in item_refs)
            ):
                completed_items.append({"description": description, "evidenceRefs": sorted(set(item_refs))})

    completed_work = (
        {"status": "evidence_supported", "items": completed_items}
        if completed_items
        else {
            "status": "unknown",
            "items": [],
            "reason": "Persisted evidence contains no mechanically verified completed-work records.",
        }
    )

    identity_runs = [{"taskId": task_id, "runId": run_id}]
    expected_checkpoint_id = interruption_id(
        str(event.get("companyId")), str(event.get("provider")), agent_id, identity_runs
    )
    supplied_checkpoint_id = evidence.get("interruptionId")
    if supplied_checkpoint_id is not None and supplied_checkpoint_id != expected_checkpoint_id:
        raise CheckpointError("interruption identity does not match persisted evidence")
    checkpoint_id = expected_checkpoint_id
    return {
        "schemaVersion": 1,
        "checkpointId": checkpoint_id,
        "interruption": {
            "taskId": task_id,
            "runId": run_id,
            "agentId": agent_id,
            "provider": event.get("provider"),
            "poolId": event.get("poolId"),
            "quotaState": event.get("quotaState"),
            "stateReason": event.get("stateReason"),
            "causingWindows": event.get("causingWindows") if isinstance(event.get("causingWindows"), list) else [],
            "recordedAt": event.get("recordedAt"),
        },
        "pause": {
            "status": "confirmed" if pause_confirmed else "pause_unconfirmed",
            "receipt": receipt if pause_confirmed else None,
            "evidenceRef": refs[0]["ref"],
        },
        "sourceTask": {
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "statusAtCollection": issue.get("status"),
            "projectId": issue.get("projectId"),
        },
        "sourceRun": {
            "statusAtCollection": run.get("status"),
            "errorCode": run.get("errorCode"),
            "startedAt": run.get("startedAt"),
            "finishedAt": run.get("finishedAt"),
        },
        "completedWork": completed_work,
        "observedContinuation": observed_continuation,
        "nextWork": {
            "status": "unknown",
            "reason": "The deterministic collector does not infer what the cloud agent should do next.",
        },
        "workspaceChanges": {
            "status": "unknown",
            "reason": "No persisted, mechanically verified workspace-change manifest was supplied.",
        },
        "evidenceReferences": refs,
        "requiresProviderInference": False,
        "automaticResumeRequested": False,
    }


def write_if_changed(path: Path, value: dict[str, Any]) -> bool:
    payload = canonical_bytes(value)
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def collect(evidence_path: Path, output_path: Path, task_id: str, run_id: str, agent_id: str) -> dict[str, Any]:
    with evidence_path.open("r", encoding="utf-8-sig") as handle:
        evidence = json.load(handle)
    checkpoint = build_checkpoint(evidence, task_id=task_id, run_id=run_id, agent_id=agent_id)
    changed = write_if_changed(output_path, checkpoint)
    return {"checkpointId": checkpoint["checkpointId"], "changed": changed, "output": str(output_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--agent-id", required=True)
    args = parser.parse_args(argv)
    result = collect(args.evidence, args.output, args.task_id, args.run_id, args.agent_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
