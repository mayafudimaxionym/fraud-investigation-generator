from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from investigation.app import _build_service, optional_decline_reason, select_active_proposal
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


def test_service_factory_creates_a_fresh_store_for_each_ui_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("investigation.app.DATABASE_PATH", tmp_path / "investigations.sqlite")

    first_service, first_store = _build_service()
    second_service, second_store = _build_service()
    try:
        assert first_service is not second_service
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
    assert app.title[0].value == "V0 Fraud Investigation Approval Loop"
    assert {item.label for item in app.text_input} >= {
        "Case reference",
        "Investigator package directory",
        "Existing investigation ID",
        "Package directory for existing investigation",
    }
    assert {item.label for item in app.text_area} >= {"Investigator instruction"}
    assert {item.label for item in app.button} >= {
        "Start investigation",
        "Load investigation",
    }
