from datetime import datetime, timedelta, timezone
from pathlib import Path

from investigation.models import (
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationRecord,
)
from investigation.persistence import SQLiteInvestigationStore


BASE_TIME = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def _investigation() -> InvestigationRecord:
    return InvestigationRecord(
        "investigation-001",
        "development-case-42",
        BASE_TIME,
        BASE_TIME + timedelta(minutes=5),
    )


def _proposal(
    proposal_id: str = "proposal-001", *, created_at: datetime = BASE_TIME
) -> AnalyticalActionProposal:
    return AnalyticalActionProposal(
        proposal_id,
        "Compare login and transfer sequences.",
        "Assess the visible sequence.",
        "The investigator requested an initial review.",
        "investigation request and visible_events.csv inventory",
        "A bounded sequence-comparison result.",
        "PROPOSED",
        created_at,
    )


def _decision(
    decision_type: str,
    *,
    proposal_id: str = "proposal-001",
    decision_id: str = "decision-001",
    instruction_or_reason: str | None = None,
    decided_at: datetime = BASE_TIME + timedelta(minutes=1),
) -> HumanDecision:
    return HumanDecision(
        decision_id,
        proposal_id,
        decision_type,
        decided_at,
        instruction_or_reason,
    )


def test_store_reloads_investigation_across_a_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    investigation = _investigation()

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(investigation)

    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.get_investigation(investigation.investigation_id) == investigation


def test_store_reloads_all_proposal_fields_and_final_status(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()
    decision = _decision("APPROVE")

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", proposal)
        (approved,) = store.persist_human_decision(proposal, decision)

        assert store.list_proposals("investigation-001") == (approved,)


def test_store_reloads_human_decisions(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()
    decision = _decision(
        "DECLINE", instruction_or_reason="Review customer correspondence first."
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", proposal)
        (declined,) = store.persist_human_decision(proposal, decision)

        assert store.list_decisions("investigation-001") == (decision,)


def test_store_preserves_modify_lineage_and_restart_state(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    original = _proposal()
    decision = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = AnalyticalActionProposal(
        "proposal-002",
        "Compare only visible login and transfer events.",
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        "PROPOSED",
        BASE_TIME + timedelta(minutes=2),
        original.proposal_id,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", original)
        modified_original, proposed_revision = store.persist_human_decision(
            original, decision, revised
        )

    with SQLiteInvestigationStore(database_path) as reopened:
        assert reopened.list_proposals("investigation-001") == (
            modified_original,
            proposed_revision,
        )
        assert reopened.list_decisions("investigation-001") == (decision,)
        assert reopened.list_history("investigation-001") == (
            modified_original,
            decision,
            proposed_revision,
        )


def test_history_is_deterministically_ordered_by_timestamp_then_identity(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    later = _proposal("proposal-later", created_at=BASE_TIME + timedelta(minutes=2))
    earlier = _proposal("proposal-earlier", created_at=BASE_TIME)

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", later)
        store.add_proposal("investigation-001", earlier)

        assert store.list_proposals("investigation-001") == (earlier, later)
        assert store.list_history("investigation-001") == (earlier, later)


def test_store_rejects_proposals_without_a_persisted_investigation(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    proposal = _proposal()

    with SQLiteInvestigationStore(database_path) as store:
        try:
            store.add_proposal("investigation-001", proposal)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("proposals require a persisted investigation")


def test_initial_investigation_and_proposal_write_rolls_back_on_proposal_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    target_investigation = _investigation()
    duplicate_proposal = _proposal("proposal-duplicate")
    target_proposal = _proposal("proposal-duplicate")
    existing_investigation = InvestigationRecord(
        "investigation-existing",
        "other-case",
        BASE_TIME,
        BASE_TIME,
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(existing_investigation)
        store.add_proposal(existing_investigation.investigation_id, duplicate_proposal)

        try:
            store.add_investigation_with_initial_proposal(
                target_investigation, target_proposal
            )
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate initial proposal IDs must fail inside the transaction")

        try:
            store.get_investigation(target_investigation.investigation_id)
        except ValueError as error:
            assert "does not exist" in str(error)
        else:
            raise AssertionError("investigation insertion must roll back with proposal failure")
        assert store.list_proposals(target_investigation.investigation_id) == ()


def test_final_decision_writes_roll_back_when_decision_insert_fails(tmp_path: Path) -> None:
    for decision_type in ("APPROVE", "DECLINE"):
        database_path = tmp_path / f"{decision_type.lower()}.sqlite"
        existing_proposal = _proposal(f"proposal-existing-{decision_type}")
        existing_decision = _decision(
            decision_type,
            proposal_id=existing_proposal.proposal_id,
            decision_id="decision-duplicate",
        )
        target_proposal = _proposal(f"proposal-target-{decision_type}")
        duplicate_decision = _decision(
            decision_type,
            proposal_id=target_proposal.proposal_id,
            decision_id="decision-duplicate",
        )

        with SQLiteInvestigationStore(database_path) as store:
            store.add_investigation(_investigation())
            store.add_proposal("investigation-001", existing_proposal)
            store.persist_human_decision(existing_proposal, existing_decision)
            store.add_proposal("investigation-001", target_proposal)

            try:
                store.persist_human_decision(target_proposal, duplicate_decision)
            except ValueError as error:
                assert "integrity" in str(error)
            else:
                raise AssertionError("duplicate decision IDs must fail inside the transaction")

            statuses = {
                proposal.proposal_id: proposal.status
                for proposal in store.list_proposals("investigation-001")
            }
            assert statuses[target_proposal.proposal_id] == "PROPOSED"
            assert store.list_decisions("investigation-001") == (existing_decision,)


def test_modify_writes_roll_back_when_revised_proposal_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "modify.sqlite"
    original = _proposal()
    duplicate = _proposal("proposal-duplicate")
    decision = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = AnalyticalActionProposal(
        duplicate.proposal_id,
        "Compare only visible login and transfer events.",
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        "PROPOSED",
        BASE_TIME + timedelta(minutes=2),
        original.proposal_id,
    )

    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(_investigation())
        store.add_proposal("investigation-001", original)
        store.add_proposal("investigation-001", duplicate)
        try:
            store.persist_human_decision(original, decision, revised)
        except ValueError as error:
            assert "integrity" in str(error)
        else:
            raise AssertionError("duplicate revised proposal IDs must fail inside the transaction")

        statuses = {
            proposal.proposal_id: proposal.status
            for proposal in store.list_proposals("investigation-001")
        }
        assert statuses == {
            original.proposal_id: "PROPOSED",
            duplicate.proposal_id: "PROPOSED",
        }
        assert store.list_decisions("investigation-001") == ()
