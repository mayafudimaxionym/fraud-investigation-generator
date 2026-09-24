from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from investigation.app import DEFAULT_OBJECTIVE, _build_dependencies, operation_working_label, optional_decline_reason, select_active_proposal
from investigation.models import AnalyticalActionProposal


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


def test_initial_streamlit_screen_renders_without_invoking_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
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
    assert operation_working_label("start") == "Preparing investigation approach"
    for operation in ("modify", "decline", "retry", "approve"):
        assert operation_working_label(operation) == "Adjusting investigation plan"


def test_investigator_ui_uses_safe_boundaries_and_no_execution_path() -> None:
    source = (Path(__file__).parents[1] / "investigation" / "app.py").read_text(encoding="utf-8").casefold()
    assert "evaluator_only" not in source
    assert "ground_truth" not in source
    assert "csv.reader" not in source
    assert ".execute(" not in source
    assert "def execute" not in source
    assert "try again" in source and "retry_decline_reconsideration" in source
