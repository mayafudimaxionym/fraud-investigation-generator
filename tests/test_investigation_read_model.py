"""Focused persisted-state projection coverage for V0.5."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from generator.dev.package_case import export_development_investigation_package
from investigation.case_catalog import ConfiguredCaseCatalog, ConfiguredCasePackage
from investigation.models import AnalyticalActionProposal, HumanDecision, InvestigationDirection, InvestigationRecord
from investigation.persistence import DeclineReconsiderationResult, SQLiteInvestigationStore
from investigation.read_model import AttentionReason, InvestigationReadProjector, PersistedLifecycleState, ProjectionIntegrityError


TIME = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)


def _catalog(package: Path) -> ConfiguredCaseCatalog:
    return ConfiguredCaseCatalog((ConfiguredCasePackage("case-42", "development-case-42", package, "payments"),))


def _investigation(identifier: str = "investigation-001", objective: str | None = "", association: str | None = "case-42") -> InvestigationRecord:
    return InvestigationRecord(identifier, "development-case-42", TIME, TIME, objective, association)


def _proposal(identifier: str = "proposal-001", created: datetime = TIME) -> AnalyticalActionProposal:
    return AnalyticalActionProposal(identifier, "Review visible events.", "Assess explanations.", "Review is needed now.", "visible_events.csv", "A bounded summary.", "PROPOSED", created)


def _direction(investigation_id: str = "investigation-001") -> InvestigationDirection:
    return InvestigationDirection("direction-001", investigation_id, 1, ("Misuse is plausible.", "Shared access is plausible."), ("Review events.",), TIME, "INITIAL")


def _projector(tmp_path: Path) -> tuple[SQLiteInvestigationStore, InvestigationReadProjector]:
    store = SQLiteInvestigationStore(tmp_path / "investigations.sqlite")
    package = export_development_investigation_package(tmp_path / "package")
    return store, InvestigationReadProjector(store, _catalog(package))


def test_active_proposal_projects_needs_review_with_safe_context_and_direction(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, proposal = _investigation(), _proposal()
    store.add_investigation(investigation)
    store.add_direction(_direction())
    store.add_proposal(investigation.investigation_id, proposal)
    detail = projector.detail(investigation.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW
    assert detail.active_proposal == proposal and detail.current_direction == _direction()
    assert detail.case is not None and detail.case.domain == "payments"
    assert detail.context is not None and "evaluator_only" not in repr(detail.context)
    assert not hasattr(projector, "generate") and not hasattr(projector, "execute")
    store.close()


def test_approved_ready_and_legacy_attention_states_are_derived_from_facts(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    approved, proposal = _investigation("approved"), _proposal("approved-proposal")
    store.add_investigation(approved)
    store.add_proposal(approved.investigation_id, proposal)
    store.persist_human_decision(proposal, HumanDecision("approved-decision", proposal.proposal_id, "APPROVE", TIME + timedelta(minutes=1)))
    assert projector.detail(approved.investigation_id).lifecycle_state is PersistedLifecycleState.APPROVED

    ready = _investigation("ready")
    store.add_investigation(ready)
    ready_detail = projector.detail(ready.investigation_id)
    assert ready_detail.lifecycle_state is PersistedLifecycleState.READY
    assert ready_detail.lifecycle_state is not PersistedLifecycleState.AGENT_WORKING

    missing_package = _investigation("missing-package", association=None)
    store.add_investigation(missing_package)
    detail = projector.detail(missing_package.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert detail.attention_reason is AttentionReason.MISSING_PACKAGE_ASSOCIATION

    missing_objective = _investigation("missing-objective", objective=None)
    store.add_investigation(missing_objective)
    assert projector.detail(missing_objective.investigation_id).attention_reason is AttentionReason.MISSING_OBJECTIVE
    store.close()


def test_attention_precedes_active_or_approved_actions_when_safe_continuation_is_blocked(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    missing_package, active = _investigation("missing-package", association=None), _proposal("active")
    store.add_investigation(missing_package)
    store.add_proposal(missing_package.investigation_id, active)
    package_detail = projector.detail(missing_package.investigation_id)
    assert package_detail.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert package_detail.active_proposal == active

    investigation, approved = _investigation("approved-then-declined"), _proposal("approved")
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, approved)
    store.persist_human_decision(
        approved, HumanDecision("approve-001", approved.proposal_id, "APPROVE", TIME + timedelta(minutes=1))
    )
    later = _proposal("later", TIME + timedelta(minutes=2))
    store.add_proposal(investigation.investigation_id, later)
    store.persist_human_decision(
        later, HumanDecision("decline-001", later.proposal_id, "DECLINE", TIME + timedelta(minutes=3))
    )
    decline_detail = projector.detail(investigation.investigation_id)
    assert decline_detail.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert decline_detail.attention_reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE
    assert decline_detail.current_or_last_proposal is not None
    assert decline_detail.current_or_last_proposal.proposal_id == later.proposal_id
    store.close()


def test_unlinked_decline_is_attention_even_when_an_unrelated_proposal_exists(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, declined = _investigation(), _proposal()
    unrelated = _proposal("unrelated", TIME + timedelta(minutes=2))
    decline = HumanDecision("decline-001", declined.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, declined)
    store.persist_human_decision(declined, decline)
    store.add_proposal(investigation.investigation_id, unrelated)
    detail = projector.detail(investigation.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert detail.attention_reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE
    assert detail.active_proposal == unrelated
    assert detail.current_or_last_proposal is not None
    assert detail.current_or_last_proposal.proposal_id == declined.proposal_id
    assert detail.current_or_last_proposal.status == "DECLINED"
    store.close()


def test_decline_attention_and_linked_replacement_use_persisted_association(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, original = _investigation(), _proposal()
    decline = HumanDecision("decline-001", original.proposal_id, "DECLINE", TIME + timedelta(minutes=1), "Try a different direction.")
    store.add_investigation(investigation)
    store.add_direction(_direction())
    store.add_proposal(investigation.investigation_id, original)
    store.persist_human_decision(original, decline)
    attention = projector.detail(investigation.investigation_id)
    assert attention.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert attention.attention_reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE
    assert attention.current_or_last_proposal.proposal_id == original.proposal_id  # type: ignore[union-attr]

    replacement = _proposal("replacement", TIME + timedelta(minutes=2))
    result = DeclineReconsiderationResult(decline.decision_id, replacement.proposal_id, TIME + timedelta(minutes=3))
    store.add_decline_reconsideration_result(investigation.investigation_id, None, replacement, result)
    recovered = projector.detail(investigation.investigation_id)
    assert recovered.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW
    assert recovered.active_proposal == replacement
    assert recovered.decline_reconsideration_results == (result,)
    store.close()


def test_historical_resolved_decline_does_not_keep_an_approved_replacement_in_attention(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, original = _investigation(), _proposal()
    decline = HumanDecision("decline-001", original.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
    replacement = _proposal("replacement", TIME + timedelta(minutes=2))
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, original)
    store.persist_human_decision(original, decline)
    store.add_decline_reconsideration_result(
        investigation.investigation_id, None, replacement,
        DeclineReconsiderationResult(decline.decision_id, replacement.proposal_id, TIME + timedelta(minutes=3)),
    )
    approval = HumanDecision("approve-001", replacement.proposal_id, "APPROVE", TIME + timedelta(minutes=4))
    store.persist_human_decision(replacement, approval)
    detail = projector.detail(investigation.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.APPROVED
    assert detail.attention_reason is None
    assert detail.current_or_last_proposal is not None
    assert detail.current_or_last_proposal.proposal_id == replacement.proposal_id
    assert detail.current_or_last_proposal.status == "APPROVED"
    store.close()


def test_multiple_active_proposals_and_invalid_result_are_not_projected_as_plausible_state(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation = _investigation()
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, _proposal())
    store.add_proposal(investigation.investigation_id, _proposal("proposal-002"))
    with pytest.raises(ProjectionIntegrityError, match="multiple PROPOSED"):
        projector.detail(investigation.investigation_id)
    store.close()


def test_history_preserves_direction_order_modify_lineage_and_decision_instruction(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, original = _investigation(), _proposal()
    store.add_investigation(investigation)
    initial = _direction()
    store.add_direction(initial)
    store.add_proposal(investigation.investigation_id, original)
    decision = HumanDecision("modify-001", original.proposal_id, "MODIFY", TIME + timedelta(minutes=1), "Use a narrower review.")
    revised = _proposal("revision-001", TIME + timedelta(minutes=2))
    revised = AnalyticalActionProposal(
        revised.proposal_id, revised.action, revised.purpose, revised.why_now,
        revised.data_to_be_used, revised.expected_output, revised.status,
        revised.created_at, original.proposal_id,
    )
    next_direction = InvestigationDirection(
        "direction-002", investigation.investigation_id, 2,
        ("Alternative explanation first.", "Misuse remains plausible."),
        ("Review relationships.", "Review events."), TIME + timedelta(minutes=1),
        "MODIFY", decision.decision_id,
    )
    store.persist_modify_with_optional_direction(original, decision, revised, next_direction)
    detail = projector.detail(investigation.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW
    assert detail.current_direction == next_direction
    assert detail.direction_history == (initial, next_direction)
    assert detail.proposal_history[0].status == "MODIFIED"
    assert detail.proposal_history[1].revised_from_proposal_id == original.proposal_id
    assert detail.decision_history == (decision,)
    assert detail.decision_history[0].instruction_or_reason == "Use a narrower review."
    store.close()


def test_invalid_decline_reconsideration_relationship_fails_projection(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, original = _investigation(), _proposal()
    decline = HumanDecision("decline-001", original.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, original)
    store.persist_human_decision(original, decline)
    invalid_replacement = _proposal("invalid-replacement", TIME + timedelta(minutes=2))
    store.add_decline_reconsideration_result(
        investigation.investigation_id, None, invalid_replacement,
        DeclineReconsiderationResult(decline.decision_id, invalid_replacement.proposal_id, TIME + timedelta(minutes=3)),
    )
    with store._connection:
        store._connection.execute(
            "UPDATE proposals SET revised_from_proposal_id = ? WHERE proposal_id = ?",
            (original.proposal_id, invalid_replacement.proposal_id),
        )
    with pytest.raises(ProjectionIntegrityError, match="invalid replacement"):
        projector.detail(investigation.investigation_id)
    store.close()


def test_decision_status_mismatch_fails_instead_of_projecting_approved(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, proposal = _investigation(), _proposal()
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, proposal)
    approval = HumanDecision("approve-001", proposal.proposal_id, "APPROVE", TIME + timedelta(minutes=1))
    store.persist_human_decision(proposal, approval)
    with store._connection:
        store._connection.execute(
            "UPDATE proposals SET status = 'PROPOSED' WHERE proposal_id = ?", (proposal.proposal_id,)
        )
    with pytest.raises(ProjectionIntegrityError, match="decision does not match"):
        projector.detail(investigation.investigation_id)
    store.close()


def test_noncontiguous_direction_history_fails_instead_of_selecting_a_current_direction(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation = _investigation()
    store.add_investigation(investigation)
    store.add_direction(_direction())
    with store._connection:
        store._connection.execute(
            "UPDATE investigation_directions SET version = 3 WHERE direction_id = 'direction-001'"
        )
    with pytest.raises(ProjectionIntegrityError, match="inconsistent versions"):
        projector.detail(investigation.investigation_id)
    store.close()


def test_summary_order_and_last_activity_use_persisted_timestamps(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    earlier = _investigation("earlier")
    later = _investigation("later")
    store.add_investigation(earlier)
    store.add_investigation(later)
    later_proposal = _proposal("later-proposal", TIME + timedelta(minutes=10))
    store.add_proposal(later.investigation_id, later_proposal)
    summaries = projector.list_investigations()
    assert [item.investigation_id for item in summaries] == ["later", "earlier"]
    assert summaries[0].last_activity == later_proposal.created_at
    assert str(tmp_path) not in repr(summaries)
    store.close()


def test_summary_ties_break_deterministically_by_investigation_id(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    store.add_investigation(_investigation("investigation-a"))
    store.add_investigation(_investigation("investigation-b"))
    assert [item.investigation_id for item in projector.list_investigations()] == [
        "investigation-b", "investigation-a"
    ]
    store.close()


def test_safe_context_unavailability_is_transient_and_not_persisted(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation = _investigation()
    store.add_investigation(investigation)
    unavailable = InvestigationReadProjector(store, ConfiguredCaseCatalog(()))
    detail = unavailable.detail(investigation.investigation_id)
    assert detail.lifecycle_state is PersistedLifecycleState.ATTENTION
    assert detail.attention_reason is AttentionReason.SAFE_CONTEXT_UNAVAILABLE
    assert store.get_investigation(investigation.investigation_id) == investigation
    assert projector.detail(investigation.investigation_id).attention_reason is None
    store.close()


def test_last_activity_uses_each_relevant_persisted_timestamp_type(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, proposal = _investigation(), _proposal()
    store.add_investigation(investigation)
    store.add_direction(_direction())
    store.add_proposal(investigation.investigation_id, proposal)
    assert projector.detail(investigation.investigation_id).last_activity == TIME
    approval = HumanDecision("approve-001", proposal.proposal_id, "APPROVE", TIME + timedelta(minutes=1))
    store.persist_human_decision(proposal, approval)
    assert projector.detail(investigation.investigation_id).last_activity == approval.decided_at

    declined = _proposal("declined", TIME + timedelta(minutes=2))
    store.add_proposal(investigation.investigation_id, declined)
    assert projector.detail(investigation.investigation_id).last_activity == declined.created_at
    decline = HumanDecision("decline-001", declined.proposal_id, "DECLINE", TIME + timedelta(minutes=3))
    store.persist_human_decision(declined, decline)
    replacement = _proposal("replacement", TIME + timedelta(minutes=4))
    result = DeclineReconsiderationResult(decline.decision_id, replacement.proposal_id, TIME + timedelta(minutes=5))
    store.add_decline_reconsideration_result(investigation.investigation_id, None, replacement, result)
    assert projector.detail(investigation.investigation_id).last_activity == result.created_at
    final_direction = InvestigationDirection(
        "direction-002", investigation.investigation_id, 2,
        ("A second explanation.",), ("Review the visible events.",),
        TIME + timedelta(minutes=6), "DECLINE_REDIRECT", decline.decision_id,
    )
    store.add_direction(final_direction)
    assert projector.detail(investigation.investigation_id).last_activity == final_direction.created_at

    record_with_later_update = InvestigationRecord(
        "updated-latest", "development-case-42", TIME, TIME + timedelta(minutes=7), "", "case-42"
    )
    store.add_investigation(record_with_later_update)
    assert projector.detail(record_with_later_update.investigation_id).last_activity == record_with_later_update.updated_at
    store.close()


def test_decline_reconsideration_history_is_scoped_to_its_investigation(tmp_path: Path) -> None:
    store, _ = _projector(tmp_path)
    first, first_proposal = _investigation("first"), _proposal("first-proposal")
    second, second_proposal = _investigation("second"), _proposal("second-proposal")
    store.add_investigation(first)
    store.add_investigation(second)
    store.add_proposal(first.investigation_id, first_proposal)
    store.add_proposal(second.investigation_id, second_proposal)
    first_decline = HumanDecision("first-decline", first_proposal.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
    second_decline = HumanDecision("second-decline", second_proposal.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
    store.persist_human_decision(first_proposal, first_decline)
    store.persist_human_decision(second_proposal, second_decline)
    first_replacement, second_replacement = _proposal("first-replacement"), _proposal("second-replacement")
    first_result = DeclineReconsiderationResult(first_decline.decision_id, first_replacement.proposal_id, TIME + timedelta(minutes=2))
    second_result = DeclineReconsiderationResult(second_decline.decision_id, second_replacement.proposal_id, TIME + timedelta(minutes=2))
    store.add_decline_reconsideration_result(first.investigation_id, None, first_replacement, first_result)
    store.add_decline_reconsideration_result(second.investigation_id, None, second_replacement, second_result)
    assert store.list_decline_reconsideration_results(first.investigation_id) == (first_result,)
    assert store.list_decline_reconsideration_results(second.investigation_id) == (second_result,)
    store.close()


def test_projection_is_identical_after_sqlite_restart(tmp_path: Path) -> None:
    database = tmp_path / "investigations.sqlite"
    package = export_development_investigation_package(tmp_path / "package")
    with SQLiteInvestigationStore(database) as store:
        investigation, proposal = _investigation(), _proposal()
        store.add_investigation(investigation)
        store.add_direction(_direction())
        store.add_proposal(investigation.investigation_id, proposal)
        before = InvestigationReadProjector(store, _catalog(package)).detail(investigation.investigation_id)
    with SQLiteInvestigationStore(database) as store:
        after = InvestigationReadProjector(store, _catalog(package)).detail("investigation-001")
    assert after == before


def test_persisted_lifecycle_projections_survive_restart_for_terminal_and_decline_paths(tmp_path: Path) -> None:
    database = tmp_path / "investigations.sqlite"
    package = export_development_investigation_package(tmp_path / "package")
    with SQLiteInvestigationStore(database) as store:
        approved, approved_proposal = _investigation("approved"), _proposal("approved-proposal")
        incomplete, incomplete_proposal = _investigation("incomplete"), _proposal("incomplete-proposal")
        replacement_case, original = _investigation("replacement"), _proposal("original-proposal")
        modified, modification_source = _investigation("modified"), _proposal("modify-source")
        for investigation, proposal in (
            (approved, approved_proposal), (incomplete, incomplete_proposal),
            (replacement_case, original), (modified, modification_source),
        ):
            store.add_investigation(investigation)
            store.add_proposal(investigation.investigation_id, proposal)
        store.persist_human_decision(
            approved_proposal, HumanDecision("approve-001", approved_proposal.proposal_id, "APPROVE", TIME + timedelta(minutes=1))
        )
        incomplete_decline = HumanDecision("incomplete-decline", incomplete_proposal.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
        store.persist_human_decision(incomplete_proposal, incomplete_decline)
        replacement_decline = HumanDecision("replacement-decline", original.proposal_id, "DECLINE", TIME + timedelta(minutes=1))
        store.persist_human_decision(original, replacement_decline)
        replacement = _proposal("replacement-proposal", TIME + timedelta(minutes=2))
        store.add_decline_reconsideration_result(
            replacement_case.investigation_id, None, replacement,
            DeclineReconsiderationResult(replacement_decline.decision_id, replacement.proposal_id, TIME + timedelta(minutes=3)),
        )
        modification = HumanDecision("modify-001", modification_source.proposal_id, "MODIFY", TIME + timedelta(minutes=1), "Refine the action.")
        revision = AnalyticalActionProposal(
            "revision", "Review visible events.", "Assess explanations.", "Review is needed now.",
            "visible_events.csv", "A bounded summary.", "PROPOSED", TIME + timedelta(minutes=2), modification_source.proposal_id,
        )
        store.persist_modify_with_optional_direction(modification_source, modification, revision)
        before = {
            identifier: InvestigationReadProjector(store, _catalog(package)).detail(identifier)
            for identifier in ("approved", "incomplete", "replacement", "modified")
        }
    with SQLiteInvestigationStore(database) as store:
        projector = InvestigationReadProjector(store, _catalog(package))
        after = {identifier: projector.detail(identifier) for identifier in before}
    assert after == before
    assert after["approved"].lifecycle_state is PersistedLifecycleState.APPROVED
    assert after["incomplete"].attention_reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE
    assert after["replacement"].lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW
    assert after["modified"].proposal_history[1].revised_from_proposal_id == "modify-source"


def test_safe_context_is_catalog_resolved_and_contains_no_package_path_or_raw_row_value(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation = _investigation()
    store.add_investigation(investigation)
    package = tmp_path / "package" / "development-case-42"
    events = package / "investigator" / "data" / "visible_events.csv"
    rows = events.read_text(encoding="utf-8").splitlines()
    marker = "task6-raw-row-marker"
    rows[1] = rows[1].replace("event-", f"{marker}-", 1)
    events.write_text("\n".join(rows) + "\n", encoding="utf-8")
    detail = projector.detail(investigation.investigation_id)
    assert detail.context is not None
    rendered = repr(detail)
    assert marker not in rendered
    assert str(package) not in rendered
    assert "evaluator_only" not in rendered
    store.close()


def test_projector_performs_no_database_writes(tmp_path: Path) -> None:
    store, projector = _projector(tmp_path)
    investigation, proposal = _investigation(), _proposal()
    store.add_investigation(investigation)
    store.add_proposal(investigation.investigation_id, proposal)
    before_changes = store._connection.total_changes
    before_dump = "\n".join(store._connection.iterdump())
    projector.detail(investigation.investigation_id)
    projector.list_investigations()
    assert store._connection.total_changes == before_changes
    assert "\n".join(store._connection.iterdump()) == before_dump
    store.close()
