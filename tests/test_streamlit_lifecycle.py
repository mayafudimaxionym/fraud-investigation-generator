"""Real Streamlit rerun/session lifecycle coverage for V0.5 remediation."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import element_tree

from investigation.approval_loop import InvestigatorReadyApprovalLoopService
from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import (
    ProposalModelError,
    ProposalModelFailureCategory,
)


class _LifecycleProposalClient:
    """Controllable local-model transport shared across AppTest reruns."""

    def __init__(self) -> None:
        self.preflight_calls = 0
        self.prompts: list[str] = []
        self.failure: ProposalModelError | None = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.call_durations: list[float] = []

    def delay_next_generation(self) -> None:
        self.started.clear()
        self.release.clear()

    def preflight(self) -> None:
        self.preflight_calls += 1

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.started.set()
        started_at = time.monotonic()
        if not self.release.wait(timeout=10):
            raise AssertionError("test model release was not signalled")
        self.call_durations.append(time.monotonic() - started_at)
        if self.failure is not None:
            raise self.failure
        if "Generation mode: MODIFY" in prompt:
            suffix = "revised"
            action = "Review visible event timing using the saved modification instruction."
        elif "Generation mode: DECLINE_REDIRECT" in prompt:
            suffix = "redirected"
            action = (
                "Use another governed approach to review visible relationship evidence "
                "instead."
            )
        else:
            suffix = "initial"
            action = "Review visible event timing for the reported activity."
        if suffix == "redirected":
            explanations = [
                "A broader multi-entity pattern may indicate coordinated misuse.",
                "Shared infrastructure may reflect legitimate network or household access.",
            ]
            plan_steps = [
                "Scope: Define the broader governed entity and relationship boundary.",
                "Evidence review: Review visible links, events, and shared attributes across entities.",
                "Comparison: Contrast coordinated misuse with legitimate shared-infrastructure patterns.",
                "Validation and limitations: Check coverage gaps and benign network explanations.",
                "Synthesis and conclusion: Summarize the supported network-level explanation and limits.",
            ]
        else:
            explanations = [
                f"Coordinated activity remains plausible ({suffix}).",
                f"Legitimate shared access remains plausible ({suffix}).",
            ]
            plan_steps = [
                f"Scope: Define the governed investigation boundary ({suffix}).",
                f"Evidence review: Review visible event and relationship evidence ({suffix}).",
                "Comparison: Compare evidence across the competing explanations.",
                "Validation and limitations: Check gaps and alternative interpretations.",
                "Synthesis and conclusion: Summarize support and limitations before concluding.",
            ]
        return json.dumps(
            {
                "competing_explanations": explanations,
                "plan_steps": plan_steps,
                "proposal": {
                    "action": action,
                    "purpose": "Distinguish the plausible explanations.",
                    "why_now": "The governed context supports this bounded next step.",
                    "data_to_be_used": "visible_events.csv and visible_relationships.csv",
                    "expected_output": "A bounded investigator-readable comparison.",
                },
            }
        )


def _run_lifecycle_app(
    database_path: str, client: object, runner_instance_id: str
) -> None:
    """Run the real app with only its local model transport replaced."""
    import importlib
    from pathlib import Path

    import investigation.app as app
    from investigation.approval_loop import InvestigatorReadyApprovalLoopService
    from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG
    from investigation.persistence import SQLiteInvestigationStore
    from investigation.proposal_agent import LocalProposalAgent
    from investigation.read_model import InvestigationReadProjector

    app = importlib.reload(app)
    app.process_runner_instance_id = lambda: runner_instance_id

    def build_dependencies():
        store = SQLiteInvestigationStore(Path(database_path))
        catalog = DEFAULT_LOCAL_CASE_CATALOG
        projector = InvestigationReadProjector(store, catalog)
        service = InvestigatorReadyApprovalLoopService(
            store, catalog, LocalProposalAgent(client), client
        )
        return store, catalog, projector, service, None

    app._build_dependencies = build_dependencies
    app.main()


def _app(
    database_path: Path,
    client: _LifecycleProposalClient,
    runner_instance_id: str = "lifecycle-test-runner",
) -> AppTest:
    return AppTest.from_function(
        _run_lifecycle_app,
        args=(str(database_path), client, runner_instance_id),
        default_timeout=15,
    )


def _button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def _text_area(app: AppTest, label: str):
    return next(item for item in app.text_area if item.label == label)


def _operation(database_path: Path, investigation_id: str, *, latest: bool = True):
    with SQLiteInvestigationStore(database_path) as store:
        operations = store.list_agent_operations(investigation_id)
    return operations[-1] if latest else operations[0]


def _only_investigation_id(database_path: Path) -> str:
    with SQLiteInvestigationStore(database_path) as store:
        (investigation,) = store.list_investigations()
    return investigation.investigation_id


def _acknowledgement_state(operation_id: str):
    original = element_tree.get_widget_state

    def get_widget_state(node):
        if (
            isinstance(node, element_tree.UnknownElement)
            and node.type == "bidi_component"
        ):
            return WidgetState(
                id=node.proto.id,
                json_trigger_value=json.dumps(
                    {"acknowledged_operation_id": operation_id}
                ),
            )
        return original(node)

    return original, get_widget_state


def _run_with_acknowledgement(
    app: AppTest, operation_id: str, *, timeout: float = 15
) -> AppTest:
    original, acknowledged = _acknowledgement_state(operation_id)
    element_tree.get_widget_state = acknowledged
    try:
        return app.run(timeout=timeout)
    finally:
        element_tree.get_widget_state = original


def _start_pending_investigation(
    app: AppTest, database_path: Path, objective: str = "Investigate the report."
) -> tuple[str, str]:
    app.run()
    _button(app, "+ New investigation").click().run()
    _text_area(app, "Investigation objective").set_value(objective).run()
    _button(app, "Start investigation").click().run()
    investigation_id = _only_investigation_id(database_path)
    operation = _operation(database_path, investigation_id)
    assert operation.status == "PENDING_RENDER"
    return investigation_id, operation.operation_id


def _complete_start(
    app: AppTest,
    database_path: Path,
    client: _LifecycleProposalClient,
) -> str:
    investigation_id, operation_id = _start_pending_investigation(
        app, database_path
    )
    _run_with_acknowledgement(app, operation_id)
    assert _operation(database_path, investigation_id).status == "COMPLETED"
    assert "Proposed next analytical action" in [item.value for item in app.subheader]
    assert len(client.prompts) == 1
    return investigation_id


def test_start_renders_working_before_delayed_dispatch_and_survives_navigation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "start-lifecycle.sqlite"
    client = _LifecycleProposalClient()
    app = _app(database_path, client)
    investigation_id, operation_id = _start_pending_investigation(
        app, database_path, "Persisted objective."
    )

    assert "Preparing investigation approach" in [item.value for item in app.subheader]
    assert client.prompts == []

    app.run()
    assert _operation(database_path, investigation_id).status == "PENDING_RENDER"
    assert client.prompts == []

    _button(app, "← Back to Investigations").click().run()
    assert app.title[0].value == "Investigations"
    assert _operation(database_path, investigation_id).status == "PENDING_RENDER"
    _button(app, "Resume").click().run()
    assert "Preparing investigation approach" in [item.value for item in app.subheader]

    client.delay_next_generation()
    timer = threading.Timer(0.3, client.release.set)
    timer.start()
    try:
        _run_with_acknowledgement(app, operation_id)
    finally:
        timer.cancel()

    assert client.started.is_set()
    assert client.call_durations[0] >= 0.2
    assert _operation(database_path, investigation_id).status == "COMPLETED"
    assert "Proposed next analytical action" in [item.value for item in app.subheader]

    app.run()
    assert len(client.prompts) == 1
    with SQLiteInvestigationStore(database_path) as store:
        assert len(store.list_proposals(investigation_id)) == 1


def test_modify_and_decline_each_dispatch_once_and_render_authoritative_result(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "decision-lifecycle.sqlite"
    client = _LifecycleProposalClient()
    app = _app(database_path, client)
    investigation_id = _complete_start(app, database_path, client)

    with SQLiteInvestigationStore(database_path) as store:
        original = next(
            item
            for item in store.list_proposals(investigation_id)
            if item.status == "PROPOSED"
        )
    _text_area(app, "Modification instruction").set_value(
        "Focus on event timing."
    ).run()
    with SQLiteInvestigationStore(database_path) as store:
        assert len(store.list_decisions(investigation_id)) == 0
        assert len(store.list_agent_operations(investigation_id)) == 1
    _button(app, "Modify").click().run()
    modify_operation = _operation(database_path, investigation_id)
    assert modify_operation.operation_type == "MODIFY"
    assert modify_operation.status == "PENDING_RENDER"
    assert "Revising proposed action" in [item.value for item in app.subheader]
    assert len(client.prompts) == 1
    with SQLiteInvestigationStore(database_path) as store:
        assert store.list_proposals(investigation_id)[0].status == "MODIFIED"
        assert len(store.list_decisions(investigation_id)) == 1

    _run_with_acknowledgement(app, modify_operation.operation_id)
    assert len(client.prompts) == 2
    with SQLiteInvestigationStore(database_path) as store:
        revised = next(
            item
            for item in store.list_proposals(investigation_id)
            if item.status == "PROPOSED"
        )
        assert revised.revised_from_proposal_id == original.proposal_id
        assert len(store.list_decisions(investigation_id)) == 1
    rendered_text = "\n".join(
        item.value
        for collection in (app.markdown, app.info, app.subheader)
        for item in collection
    )
    assert "Human semantic review" in rendered_text
    assert "Effective objective:" in rendered_text
    assert "Investigate the report." in rendered_text
    assert "Persisted Modify instruction:" in rendered_text
    assert "Focus on event timing." in rendered_text
    assert "Previous direction for comparison" in rendered_text
    assert "Generated direction" in rendered_text
    assert "provisional" in rendered_text
    assert "No action is authorized until you approve it." in rendered_text
    app.run()
    assert len(client.prompts) == 2

    _text_area(app, "Optional decline guidance").set_value(
        "Review relationships instead."
    ).run()
    _button(app, "Adjust investigation plan").click().run()
    decline_operation = _operation(database_path, investigation_id)
    assert decline_operation.operation_type == "DECLINE_REDIRECT"
    assert decline_operation.status == "PENDING_RENDER"
    assert "Adjusting investigation plan" in [item.value for item in app.subheader]
    assert len(client.prompts) == 2
    with SQLiteInvestigationStore(database_path) as store:
        assert revised.proposal_id in {
            item.proposal_id
            for item in store.list_proposals(investigation_id)
            if item.status == "DECLINED"
        }
        assert len(store.list_decisions(investigation_id)) == 2

    _run_with_acknowledgement(app, decline_operation.operation_id)
    assert len(client.prompts) == 3
    with SQLiteInvestigationStore(database_path) as store:
        proposals = store.list_proposals(investigation_id)
        replacement = next(item for item in proposals if item.status == "PROPOSED")
        assert replacement.revised_from_proposal_id is None
        assert len(store.list_decisions(investigation_id)) == 2
        assert len(store.list_decline_reconsideration_results(investigation_id)) == 1
    rendered_text = "\n".join(
        item.value
        for collection in (app.markdown, app.info, app.subheader)
        for item in collection
    )
    assert "Persisted Decline guidance:" in rendered_text
    assert "Review relationships instead." in rendered_text
    assert "Previous direction for comparison" in rendered_text
    app.run()
    assert len(client.prompts) == 3
    assert "Proposed next analytical action" in [item.value for item in app.subheader]


def test_decline_failure_attention_and_explicit_retry_do_not_duplicate_decision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "failure-retry.sqlite"
    client = _LifecycleProposalClient()
    app = _app(database_path, client)
    investigation_id = _complete_start(app, database_path, client)

    _text_area(app, "Optional decline guidance").set_value(
        "Use another governed approach."
    ).run()
    _button(app, "Adjust investigation plan").click().run()
    failed_operation = _operation(database_path, investigation_id)
    client.failure = ProposalModelError(
        ProposalModelFailureCategory.REQUEST_TIMEOUT, "simulated timeout"
    )
    _run_with_acknowledgement(app, failed_operation.operation_id)

    assert _operation(database_path, investigation_id).status == "FAILED"
    assert "The local model request timed out." in [item.value for item in app.error]
    assert "Try again" in [item.label for item in app.button]
    with SQLiteInvestigationStore(database_path) as store:
        assert len(store.list_decisions(investigation_id)) == 1
        assert not any(
            item.status == "PROPOSED"
            for item in store.list_proposals(investigation_id)
        )

    client.failure = None
    _button(app, "Try again").click().run()
    retry = _operation(database_path, investigation_id)
    assert retry.status == "PENDING_RENDER"
    assert retry.operation_id != failed_operation.operation_id
    assert retry.prior_attempt_operation_id == failed_operation.operation_id
    with SQLiteInvestigationStore(database_path) as store:
        assert len(store.list_decisions(investigation_id)) == 1

    _run_with_acknowledgement(app, retry.operation_id)
    assert len(client.prompts) == 3
    with SQLiteInvestigationStore(database_path) as store:
        assert len(store.list_decisions(investigation_id)) == 1
        assert len(store.list_decline_reconsideration_results(investigation_id)) == 1
    assert "Proposed next analytical action" in [item.value for item in app.subheader]


def test_running_refresh_does_not_redispatch_and_prior_process_work_is_interrupted(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "interrupted.sqlite"
    client = _LifecycleProposalClient()
    with SQLiteInvestigationStore(database_path) as store:
        service = InvestigatorReadyApprovalLoopService(
            store, DEFAULT_LOCAL_CASE_CATALOG, object(), object()
        )
        operation = service.prepare_start_investigation(
            "development-case-42", "Persisted objective."
        )
        assert store.claim_pending_operation(
            operation.operation_id, "previous-process", operation.updated_at
        )

    app = _app(database_path, client)
    app.session_state["v05_active_id"] = operation.investigation_id
    app.session_state["v05_view"] = "detail"
    app.session_state["v05_error"] = None
    app.session_state["v05_new_objective"] = "Persisted objective."
    app.run()

    interrupted = _operation(database_path, operation.investigation_id)
    assert interrupted.status == "INTERRUPTED"
    assert client.prompts == []
    assert "The previous processing attempt was interrupted." in [
        item.value for item in app.warning
    ]
    _button(app, "Try again").click().run()
    retry = _operation(database_path, operation.investigation_id)
    assert retry.status == "PENDING_RENDER"
    assert retry.prior_attempt_operation_id == operation.operation_id
    assert client.prompts == []

    with SQLiteInvestigationStore(database_path) as store:
        service = InvestigatorReadyApprovalLoopService(
            store, DEFAULT_LOCAL_CASE_CATALOG, object(), object()
        )
        same_process = service.prepare_start_investigation(
            "development-case-42", "Another persisted objective."
        )
        assert store.claim_pending_operation(
            same_process.operation_id,
            "lifecycle-test-runner",
            same_process.updated_at,
        )

    refreshed = _app(database_path, client)
    refreshed.session_state["v05_active_id"] = same_process.investigation_id
    refreshed.session_state["v05_view"] = "detail"
    refreshed.session_state["v05_error"] = None
    refreshed.session_state["v05_new_objective"] = "Another persisted objective."
    refreshed.run()

    assert _operation(database_path, same_process.investigation_id).status == "RUNNING"
    assert "Preparing investigation approach" in [
        item.value for item in refreshed.subheader
    ]
    assert client.prompts == []
