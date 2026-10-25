from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


collector = load_module("checkpoint_collector", ROOT / "checkpoint_collector.py")
qm = load_module("quota_manager_checkpoint_tests", ROOT / "quota_manager.py")


TASK_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
AGENT_ID = "33333333-3333-4333-8333-333333333333"
PROJECT_ID = "44444444-4444-4444-8444-444444444444"
EVENT_ID = "55555555-5555-4555-8555-555555555555"
RECORDED_AT = "2030-01-01T00:00:00Z"


def fixture_evidence(confirmed: bool = True) -> dict:
    event = {
        "schemaVersion": 1,
        "companyId": "test-company",
        "eventId": EVENT_ID,
        "recordedAt": RECORDED_AT,
        "action": "pause_agent",
        "provider": "anthropic",
        "poolId": "anthropic",
        "quotaState": "RED",
        "stateReason": "RED",
        "causingWindows": ["five_hour"],
        "agentId": AGENT_ID,
        "runIds": [RUN_ID],
        "phase": "result",
        "outcome": "paused" if confirmed else "failed",
    }
    if confirmed:
        event["receipt"] = {"agentId": AGENT_ID, "agentStatus": "paused"}
    return {
        "schemaVersion": 1,
        "interruptionId": collector.interruption_id(
            "test-company", "anthropic", AGENT_ID, [{"taskId": TASK_ID, "runId": RUN_ID}]
        ),
        "controlEvent": event,
        "run": {
            "id": RUN_ID,
            "agentId": AGENT_ID,
            "status": "cancelled",
            "errorCode": "agent_paused",
            "startedAt": "2029-12-31T23:00:00Z",
            "finishedAt": RECORDED_AT,
            "contextSnapshot": {
                "issueId": TASK_ID,
                "projectId": PROJECT_ID,
                "paperclipContinuationSummary": {
                    "body": "Persisted summary text; quoted without interpretation.",
                },
            },
        },
        "issue": {
            "id": TASK_ID,
            "identifier": "AXI-TEST",
            "title": "Fixture cloud task",
            "status": "in_progress",
            "projectId": PROJECT_ID,
        },
        "verifiedCompletedWork": [],
    }


class CheckpointCollectorTests(unittest.TestCase):
    def test_confirmed_pause_preserves_exact_identity_and_leaves_missing_claims_unknown(self):
        value = collector.build_checkpoint(
            fixture_evidence(), task_id=TASK_ID, run_id=RUN_ID, agent_id=AGENT_ID
        )
        self.assertEqual(
            {"taskId": TASK_ID, "runId": RUN_ID, "agentId": AGENT_ID},
            {key: value["interruption"][key] for key in ("taskId", "runId", "agentId")},
        )
        self.assertEqual("confirmed", value["pause"]["status"])
        self.assertEqual("unknown", value["completedWork"]["status"])
        self.assertEqual("unknown", value["nextWork"]["status"])
        self.assertEqual("unknown", value["workspaceChanges"]["status"])
        self.assertFalse(value["requiresProviderInference"])

    def test_unconfirmed_pause_is_explicit(self):
        value = collector.build_checkpoint(
            fixture_evidence(False), task_id=TASK_ID, run_id=RUN_ID, agent_id=AGENT_ID
        )
        self.assertEqual("pause_unconfirmed", value["pause"]["status"])
        self.assertIsNone(value["pause"]["receipt"])

    def test_completed_work_requires_an_existing_stable_evidence_reference(self):
        evidence = fixture_evidence()
        continuation_ref = f"paperclip-run:{RUN_ID}#/contextSnapshot/paperclipContinuationSummary/body"
        evidence["verifiedCompletedWork"] = [
            {"description": "Supported item", "evidenceRefs": [continuation_ref]},
            {"description": "Unsupported item", "evidenceRefs": ["invented:reference"]},
            {"description": "Missing references", "evidenceRefs": []},
        ]
        value = collector.build_checkpoint(evidence, task_id=TASK_ID, run_id=RUN_ID, agent_id=AGENT_ID)
        self.assertEqual("evidence_supported", value["completedWork"]["status"])
        self.assertEqual(["Supported item"], [item["description"] for item in value["completedWork"]["items"]])
        self.assertIn(
            continuation_ref,
            {entry["ref"] for entry in value["evidenceReferences"]},
        )

    def test_repeated_collection_is_byte_stable_and_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path, output_path = root / "evidence.json", root / "checkpoint.json"
            evidence_path.write_text(json.dumps(fixture_evidence()), encoding="utf-8")
            first = collector.collect(evidence_path, output_path, TASK_ID, RUN_ID, AGENT_ID)
            first_bytes, first_mtime = output_path.read_bytes(), output_path.stat().st_mtime_ns
            second = collector.collect(evidence_path, output_path, TASK_ID, RUN_ID, AGENT_ID)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(first_bytes, output_path.read_bytes())
            self.assertEqual(first_mtime, output_path.stat().st_mtime_ns)


class CheckpointDispatchTests(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "companyId": "test-company",
            "paperclip": {"baseUrl": "http://paperclip.invalid", "activeRunsTimeoutSeconds": 2},
            "runtimeControl": {"requestTimeoutSeconds": 2},
        }
        self.plan = {
            "provider": "anthropic",
            "poolId": "anthropic",
            "agentId": AGENT_ID,
            "interruptedRuns": [{"taskId": TASK_ID, "runId": RUN_ID}],
        }
        self.event = fixture_evidence()["controlEvent"]

    def _responses(self, deduplicated: bool):
        evidence = fixture_evidence()
        created = {
            "id": "66666666-6666-4666-8666-666666666666",
            "identifier": "AXI-CHECKPOINT",
            "assigneeAgentId": qm.LOCAL_WORKER_AGENT_ID,
            "deduplicated": deduplicated,
        }
        return [
            io.StringIO(json.dumps(evidence["run"])),
            io.StringIO(json.dumps(evidence["issue"])),
            io.StringIO(json.dumps(created)),
        ]

    def test_dispatch_contract_is_bounded_and_idempotent(self):
        requests = []

        def fake_open(request, timeout):
            requests.append(request)
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "control-events.jsonl"
            responses = self._responses(False) + self._responses(True)
            with patch.object(qm, "urlopen", fake_open):
                first = qm.dispatch_checkpoint_tasks(self.policy, self.plan, self.event, events)
                second = qm.dispatch_checkpoint_tasks(self.policy, self.plan, self.event, events)

            self.assertEqual({"planned": 1, "dispatched": 1, "failed": 0}, first)
            self.assertEqual({"planned": 1, "dispatched": 1, "failed": 0}, second)
            posts = [request for request in requests if request.get_method() == "POST"]
            self.assertEqual(2, len(posts))
            payloads = [json.loads(request.data) for request in posts]
            self.assertEqual(payloads[0]["idempotencyKey"], payloads[1]["idempotencyKey"])
            self.assertEqual(qm.LOCAL_WORKER_AGENT_ID, payloads[0]["assigneeAgentId"])
            self.assertIn("```local-worker-run", payloads[0]["description"])
            spec_text = payloads[0]["description"].split("```local-worker-run\n", 1)[1].split("\n```", 1)[0]
            spec = json.loads(spec_text)
            self.assertEqual(0, spec["expectedExitCode"])
            self.assertEqual(qm.CHECKPOINT_COLLECTOR_TIMEOUT_SECONDS, spec["timeoutSeconds"])
            self.assertEqual(1, len(spec["expectedArtifacts"]))
            for value in (TASK_ID, RUN_ID, AGENT_ID):
                self.assertIn(value, spec["args"])
            records = [json.loads(line) for line in events.with_name("checkpoint-dispatches.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([False, True], [record["deduplicated"] for record in records])
            self.assertTrue(all(record["requiresProviderInference"] is False for record in records))

    def test_missing_task_identity_is_recorded_as_unknown_and_not_inferred(self):
        plan = dict(self.plan, interruptedRuns=[], checkpointUnresolvedRunIds=[RUN_ID])
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "control-events.jsonl"
            with patch.object(qm, "urlopen") as never:
                result = qm.dispatch_checkpoint_tasks(self.policy, plan, self.event, events)
            never.assert_not_called()
            self.assertEqual({"planned": 1, "dispatched": 0, "failed": 1}, result)
            record = json.loads(events.with_name("checkpoint-dispatches.jsonl").read_text(encoding="utf-8"))
            self.assertIsNone(record["taskId"])
            self.assertEqual("CHECKPOINT_TASK_ID_UNKNOWN", record["error"]["code"])
            self.assertFalse(record["requiresProviderInference"])

if __name__ == "__main__":
    unittest.main()
