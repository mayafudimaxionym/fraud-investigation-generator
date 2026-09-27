from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from investigation.app import (
    DEFAULT_OBJECTIVE,
    INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE,
    _UnavailableProposalClient,
    _build_dependencies,
    _render_attention,
    _render_back,
    _render_working,
    configured_database_path,
    operation_failure_message,
    operation_recovery_message,
    operation_working_label,
    optional_decline_reason,
    process_runner_instance_id,
    select_active_proposal,
)
from investigation.models import AnalyticalActionProposal
from investigation.proposal_agent import ProposalModelError
from investigation.read_model import AttentionReason, InvestigatorOperation


class _RerunRequested(RuntimeError):
    pass


class _SessionState(dict[str, object]):
    def __getattr__(self, name: str) -> object:
        return self[name]

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeStreamlit:
    def __init__(self, clicked: set[str] | None = None) -> None:
        self.session_state = _SessionState(
            v05_active_id="investigation-001",
            v05_view="detail",
            v05_error=None,
        )
        self.clicked = clicked or set()
        self.rendered: list[tuple[str, str]] = []

    def button(self, label: str, **_: object) -> bool:
        return label in self.clicked

    def subheader(self, value: str) -> None:
        self.rendered.append(("subheader", value))

    def info(self, value: str) -> None:
        self.rendered.append(("info", value))

    def error(self, value: str) -> None:
        self.rendered.append(("error", value))

    def warning(self, value: str) -> None:
        self.rendered.append(("warning", value))

    def write(self, value: str) -> None:
        self.rendered.append(("write", value))

    def rerun(self) -> None:
        raise _RerunRequested


def _proposal(proposal_id: str, status: str) -> AnalyticalActionProposal:
    return AnalyticalActionProposal(
        proposal_id,
        "Review visible events.",
        "Assess the reported concern.",
        "The investigator asked for a review.",
        "visible_events.csv",
        "A bounded summary.",
        status,
        datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


def test_select_active_proposal_returns_only_a_proposed_proposal() -> None:
    approved = _proposal("proposal-approved", "APPROVED")
    proposed = _proposal("proposal-proposed", "PROPOSED")
    modified = _proposal("proposal-modified", "MODIFIED")

    assert select_active_proposal((approved, proposed, modified)) == proposed


def test_select_active_proposal_returns_none_without_a_proposed_proposal() -> None:
    assert select_active_proposal(
        (_proposal("proposal-approved", "APPROVED"), _proposal("proposal-declined", "DECLINED"))
    ) is None


def test_select_active_proposal_rejects_multiple_proposed_proposals() -> None:
    with pytest.raises(ValueError, match="multiple PROPOSED proposals"):
        select_active_proposal(
            (_proposal("proposal-first", "PROPOSED"), _proposal("proposal-second", "PROPOSED"))
        )


def test_optional_decline_reason_converts_blank_input_to_none() -> None:
    assert optional_decline_reason("") is None
    assert optional_decline_reason("   ") is None
    assert optional_decline_reason("Use another source first.") == "Use another source first."


def test_dependency_factory_creates_a_fresh_store_for_each_ui_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("investigation.app.DATABASE_PATH", tmp_path / "investigations.sqlite")

    first_store, _, _, _, _ = _build_dependencies()
    second_store, _, _, _, _ = _build_dependencies()
    try:
        assert first_store is not second_store
    finally:
        first_store.close()
        second_store.close()


def test_invalid_numeric_model_configuration_uses_fixed_safe_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_value = "not-a-number-sensitive-deployment-value"
    monkeypatch.setattr(
        "investigation.app.DATABASE_PATH", tmp_path / "investigations.sqlite"
    )
    monkeypatch.setenv("OLLAMA_MODEL", "configured-model")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", raw_value)

    store, _, _, service, configuration_error = _build_dependencies()
    try:
        assert service is not None
        assert configuration_error == INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE
        assert raw_value not in configuration_error
        assert "could not convert string to float" not in configuration_error
    finally:
        store.close()

    client = _UnavailableProposalClient()
    with pytest.raises(ProposalModelError) as unavailable:
        client.preflight()
    assert str(unavailable.value) == INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE
    assert raw_value not in str(unavailable.value)


def test_invalid_numeric_model_configuration_does_not_leak_into_streamlit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_value = "not-a-number-investigator-secret"
    monkeypatch.setenv(
        "INVESTIGATION_DATABASE_PATH", str(tmp_path / "investigations.sqlite")
    )
    monkeypatch.setenv("OLLAMA_MODEL", "configured-model")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", raw_value)
    app = AppTest.from_file(Path(__file__).parents[1] / "investigation" / "app.py")

    app.run()

    rendered = "\n".join(
        str(item.value)
        for collection in (app.markdown, app.error, app.info, app.warning)
        for item in collection
    )
    assert not app.exception
    assert INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE in rendered
    assert raw_value not in rendered
    assert "could not convert string to float" not in rendered


def test_initial_streamlit_screen_renders_without_invoking_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "INVESTIGATION_DATABASE_PATH", str(tmp_path / "investigations.sqlite")
    )
    app = AppTest.from_file(Path(__file__).parents[1] / "investigation" / "app.py")

    app.run()

    assert not app.exception
    assert app.title[0].value == "Investigations"
    assert {item.label for item in app.button} >= {"+ New investigation"}
    assert "package directory" not in str(app).casefold()


def test_default_objective_is_exact_and_blank_is_preserved() -> None:
    assert DEFAULT_OBJECTIVE == (
        "Investigate the reported suspicious activity, identify relevant patterns and relationships, "
        "and assess the plausible explanations without assuming any explanation is established in advance."
    )
    assert optional_decline_reason("") is None


def test_working_labels_are_transient_operation_labels_without_progress_or_eta() -> None:
    assert operation_working_label("START") == "Preparing investigation approach"
    assert operation_working_label("MODIFY") == "Revising proposed action"
    for operation in ("DECLINE_REDIRECT", "DECLINE_RECONSIDER"):
        assert operation_working_label(operation) == "Adjusting investigation plan"


def test_database_path_has_deterministic_default_and_absolute_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = Path(__file__).parents[1] / "investigations.sqlite"
    monkeypatch.chdir(tmp_path)
    assert configured_database_path({}) == expected
    override = tmp_path / "state" / "investigations.sqlite"
    assert configured_database_path(
        {"INVESTIGATION_DATABASE_PATH": str(override)}
    ) == override
    with pytest.raises(ValueError, match="must be an absolute path"):
        configured_database_path(
            {"INVESTIGATION_DATABASE_PATH": "relative/investigations.sqlite"}
        )


def test_process_runner_identity_is_stable_for_the_process() -> None:
    assert process_runner_instance_id() == process_runner_instance_id()


def test_back_navigation_changes_only_presentation_state() -> None:
    st = _FakeStreamlit({"← Back to Investigations"})

    with pytest.raises(_RerunRequested):
        _render_back(st)

    assert st.session_state.v05_active_id is None
    assert st.session_state.v05_view == "list"
    assert st.session_state.v05_error is None


def test_pending_work_renders_before_browser_acknowledgement_and_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    st = _FakeStreamlit()
    detail = SimpleNamespace(
        latest_operation=InvestigatorOperation(
            "operation-001", "START", "PENDING_RENDER", None
        )
    )
    calls: list[tuple[str, str]] = []
    service = SimpleNamespace(
        claim_and_execute_operation=lambda operation_id, runner_id: calls.append(
            (operation_id, runner_id)
        )
    )
    monkeypatch.setattr("investigation.app._render_acknowledged", lambda _: False)

    _render_working(st, detail, service, "runner-process")

    assert calls == []
    assert ("subheader", "Preparing investigation approach") in st.rendered
    assert any("No new action is authorized" in value for _, value in st.rendered)

    monkeypatch.setattr("investigation.app._render_acknowledged", lambda _: True)
    with pytest.raises(_RerunRequested):
        _render_working(st, detail, service, "runner-process")
    assert calls == [("operation-001", "runner-process")]


def test_running_work_never_attempts_another_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    st = _FakeStreamlit()
    detail = SimpleNamespace(
        latest_operation=InvestigatorOperation(
            "operation-001", "MODIFY", "RUNNING", None
        )
    )
    service = SimpleNamespace(
        claim_and_execute_operation=lambda *_: pytest.fail("must not redispatch RUNNING")
    )
    monkeypatch.setattr(
        "investigation.app._render_acknowledged",
        lambda _: pytest.fail("RUNNING must not request another acknowledgement"),
    )
    refreshes: list[str] = []
    monkeypatch.setattr(
        "investigation.app._schedule_running_refresh", refreshes.append
    )

    _render_working(st, detail, service, "runner-process")

    assert ("subheader", "Revising proposed action") in st.rendered
    assert refreshes == ["operation-001"]


@pytest.mark.parametrize(
    ("reason", "status", "category", "message_kind"),
    (
        (
            AttentionReason.OPERATION_FAILED,
            "FAILED",
            "REQUEST_TIMEOUT",
            "error",
        ),
        (
            AttentionReason.OPERATION_INTERRUPTED,
            "INTERRUPTED",
            None,
            "warning",
        ),
    ),
)
def test_operation_attention_is_actionable_and_retry_is_prepared(
    reason: AttentionReason,
    status: str,
    category: str | None,
    message_kind: str,
) -> None:
    st = _FakeStreamlit({"Try again"})
    detail = SimpleNamespace(
        attention_reason=reason,
        latest_operation=InvestigatorOperation(
            "operation-prior", "START", status, category
        ),
    )
    calls: list[str] = []
    service = SimpleNamespace(
        prepare_retry=lambda operation_id: (
            calls.append(operation_id)
            or SimpleNamespace(investigation_id="investigation-001")
        )
    )

    with pytest.raises(_RerunRequested):
        _render_attention(st, None, None, detail, service)

    assert calls == ["operation-prior"]
    assert any(kind == message_kind for kind, _ in st.rendered)


@pytest.mark.parametrize(
    ("operation_type", "expected"),
    (
        (
            "START",
            "No new proposal was saved. No action was authorized.",
        ),
        (
            "MODIFY",
            "The original proposal remains MODIFIED. No new revision proposal was saved and no action was authorized.",
        ),
        (
            "DECLINE_REDIRECT",
            "The original proposal remains DECLINED. No new replacement proposal was saved and no action was authorized.",
        ),
        (
            "DECLINE_RECONSIDER",
            "The original proposal remains DECLINED. No new replacement proposal was saved and no action was authorized.",
        ),
    ),
)
def test_operation_recovery_copy_matches_authoritative_state(
    operation_type: str, expected: str
) -> None:
    assert operation_recovery_message(operation_type) == expected


def test_legacy_incomplete_decline_attention_prepares_first_durable_attempt() -> None:
    st = _FakeStreamlit({"Try again"})
    declined = _proposal("proposal-declined", "DECLINED")
    decision = SimpleNamespace(
        proposal_id=declined.proposal_id,
        decision_type="DECLINE",
        instruction_or_reason="Review relationships instead.",
    )
    detail = SimpleNamespace(
        attention_reason=AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE,
        investigation=SimpleNamespace(investigation_id="investigation-001"),
        current_or_last_proposal=declined,
        decision_history=(decision,),
    )
    calls: list[tuple[str, str]] = []
    service = SimpleNamespace(
        prepare_legacy_decline_reconsideration=lambda investigation_id, proposal_id: (
            calls.append((investigation_id, proposal_id))
            or SimpleNamespace(investigation_id=investigation_id)
        )
    )

    with pytest.raises(_RerunRequested):
        _render_attention(st, None, None, detail, service)

    assert calls == [("investigation-001", "proposal-declined")]
    assert ("write", "Your instruction is saved.") in st.rendered


def test_every_persisted_failure_category_has_safe_investigator_copy() -> None:
    categories = (
        "SERVICE_UNAVAILABLE",
        "MODEL_UNAVAILABLE",
        "REQUEST_TIMEOUT",
        "GENERATION_ERROR",
        "PERSISTENCE_ERROR",
        "SAFE_CONTEXT_UNAVAILABLE",
        "PACKAGE_ASSOCIATION_UNAVAILABLE",
        "OBJECTIVE_UNAVAILABLE",
        "DIRECTION_UNAVAILABLE",
        "UNKNOWN_FAILURE",
    )
    assert all(
        operation_failure_message(category)
        != "The investigation request could not be completed."
        for category in categories
    )
    assert operation_failure_message("GENERATION_ERROR") == (
        "The agent response did not satisfy the required response contract."
    )


def test_investigator_ui_uses_safe_boundaries_and_no_execution_path() -> None:
    source = (Path(__file__).parents[1] / "investigation" / "app.py").read_text(encoding="utf-8").casefold()
    assert "evaluator_only" not in source
    assert "ground_truth" not in source
    assert "csv.reader" not in source
    assert ".execute(" not in source
    assert "def execute" not in source
    assert "try again" in source and "prepare_retry" in source
    assert "prepare_start_investigation" in source
    assert "prepare_modify" in source and "prepare_decline" in source
    assert "service.start_investigation(" not in source
    assert "service.modify(" not in source and "service.decline(" not in source
    assert "retry_decline_reconsideration" not in source
