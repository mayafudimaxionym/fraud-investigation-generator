from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from investigation.models import (
    DIRECTION_PROVENANCE,
    PROPOSAL_STATUSES,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
    InvestigationRecord,
    apply_human_decision,
)


CREATED_AT = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
DECIDED_AT = datetime(2026, 9, 17, 9, 1, tzinfo=timezone.utc)


def _proposal(**overrides: object) -> AnalyticalActionProposal:
    fields: dict[str, object] = {
        "proposal_id": "proposal-001",
        "action": "Compare login and transfer sequences.",
        "purpose": "Assess whether the visible sequence merits further review.",
        "why_now": "The investigator requested an initial evidence review.",
        "data_to_be_used": "investigation request and visible_events.csv inventory",
        "expected_output": "A bounded sequence-comparison result.",
        "status": "PROPOSED",
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return AnalyticalActionProposal(**fields)  # type: ignore[arg-type]


def _decision(decision_type: str, **overrides: object) -> HumanDecision:
    fields: dict[str, object] = {
        "decision_id": "decision-001",
        "proposal_id": "proposal-001",
        "decision_type": decision_type,
        "decided_at": DECIDED_AT,
    }
    fields.update(overrides)
    return HumanDecision(**fields)  # type: ignore[arg-type]


def _direction(**overrides: object) -> InvestigationDirection:
    fields: dict[str, object] = {
        "direction_id": "direction-001",
        "investigation_id": "investigation-001",
        "version": 1,
        "competing_explanations": (
            "The activity may reflect coordinated account takeover.",
            "The activity may reflect legitimate shared access.",
        ),
        "plan_steps": (
            "Review visible login and transfer records.",
            "Compare the available relationship evidence.",
        ),
        "created_at": CREATED_AT,
        "provenance": "INITIAL",
    }
    fields.update(overrides)
    return InvestigationDirection(**fields)  # type: ignore[arg-type]


def test_investigation_record_requires_identity_context_and_timestamps() -> None:
    record = InvestigationRecord(
        "investigation-001", "development-case-42", CREATED_AT, DECIDED_AT
    )

    assert record.case_reference == "development-case-42"

    try:
        InvestigationRecord("", "development-case-42", CREATED_AT, DECIDED_AT)
    except ValueError as error:
        assert "investigation_id" in str(error)
    else:
        raise AssertionError("an investigation ID is required")


def test_investigation_record_distinguishes_legacy_metadata_from_blank_objective() -> None:
    legacy = InvestigationRecord(
        "investigation-legacy", "development-case-42", CREATED_AT, DECIDED_AT
    )
    v05 = InvestigationRecord(
        "investigation-v05", "development-case-42", CREATED_AT, DECIDED_AT, "", "case-42"
    )

    assert legacy.objective is None
    assert legacy.package_association is None
    assert v05.objective == ""
    assert v05.package_association == "case-42"


def test_direction_accepts_an_ordered_initial_snapshot() -> None:
    direction = _direction()

    assert direction.competing_explanations == (
        "The activity may reflect coordinated account takeover.",
        "The activity may reflect legitimate shared access.",
    )
    assert direction.plan_steps == (
        "Review visible login and transfer records.",
        "Compare the available relationship evidence.",
    )
    assert direction.provenance == "INITIAL"


def test_direction_requires_identity_positive_version_and_nonblank_text() -> None:
    for field_name, value in (
        ("direction_id", " "),
        ("investigation_id", " "),
        ("competing_explanations", (" ",)),
        ("plan_steps", (" ",)),
    ):
        try:
            _direction(**{field_name: value})
        except ValueError as error:
            assert field_name in str(error)
        else:
            raise AssertionError(f"{field_name} must be valid")

    for version in (0, -1):
        try:
            _direction(version=version)
        except ValueError as error:
            assert "version" in str(error)
        else:
            raise AssertionError("version must be positive")


def test_direction_requires_tuples_and_approved_provenance() -> None:
    assert DIRECTION_PROVENANCE == ("INITIAL", "MODIFY", "DECLINE_REDIRECT")

    try:
        _direction(competing_explanations=["Not an immutable tuple"])
    except ValueError as error:
        assert "competing_explanations" in str(error)
    else:
        raise AssertionError("competing explanations must be immutable")

    try:
        _direction(provenance="RETRY")
    except ValueError as error:
        assert "provenance" in str(error)
    else:
        raise AssertionError("unapproved direction provenance must be rejected")


def test_direction_rejects_blank_trigger_reference_and_is_immutable() -> None:
    try:
        _direction(trigger_reference_id=" ")
    except ValueError as error:
        assert "trigger_reference_id" in str(error)
    else:
        raise AssertionError("a supplied trigger reference must be nonblank")

    direction = _direction(
        provenance="MODIFY", trigger_reference_id="proposal-001"
    )
    try:
        direction.version = 2  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("direction records must be immutable")


def test_proposal_requires_all_five_approved_fields() -> None:
    for field_name in (
        "action",
        "purpose",
        "why_now",
        "data_to_be_used",
        "expected_output",
    ):
        try:
            _proposal(**{field_name: " "})
        except ValueError as error:
            assert field_name in str(error)
        else:
            raise AssertionError(f"{field_name} must be required")


def test_proposal_accepts_only_approved_statuses() -> None:
    assert PROPOSAL_STATUSES == ("PROPOSED", "APPROVED", "DECLINED", "MODIFIED")

    try:
        _proposal(status="PENDING")
    except ValueError as error:
        assert "status" in str(error)
    else:
        raise AssertionError("unapproved proposal statuses must be rejected")


def test_decision_must_link_to_the_proposed_action() -> None:
    try:
        apply_human_decision(_proposal(), _decision("APPROVE", proposal_id="proposal-002"))
    except ValueError as error:
        assert "must match" in str(error)
    else:
        raise AssertionError("a decision must link to its proposal")


def test_decision_accepts_only_approved_types_and_permitted_content() -> None:
    try:
        _decision("DEFER")
    except ValueError as error:
        assert "decision_type" in str(error)
    else:
        raise AssertionError("unapproved decision types must be rejected")

    try:
        _decision("MODIFY")
    except ValueError as error:
        assert "instruction" in str(error)
    else:
        raise AssertionError("MODIFY requires an instruction")

    try:
        _decision("APPROVE", instruction_or_reason="Proceed with this action.")
    except ValueError as error:
        assert "APPROVE" in str(error)
    else:
        raise AssertionError("APPROVE must not include an instruction or reason")


def test_approve_marks_only_the_exact_proposal_approved() -> None:
    proposal = _proposal()

    (approved,) = apply_human_decision(proposal, _decision("APPROVE"))

    assert approved.status == "APPROVED"
    assert approved.proposal_id == proposal.proposal_id
    assert proposal.status == "PROPOSED"


def test_decline_marks_proposal_declined_with_or_without_a_reason() -> None:
    (without_reason,) = apply_human_decision(_proposal(), _decision("DECLINE"))
    (with_reason,) = apply_human_decision(
        _proposal(),
        _decision("DECLINE", instruction_or_reason="Review only customer correspondence."),
    )

    assert without_reason.status == "DECLINED"
    assert with_reason.status == "DECLINED"


def test_modify_preserves_decision_and_creates_a_proposed_revision_with_lineage() -> None:
    original = _proposal()
    modification = _decision(
        "MODIFY", instruction_or_reason="Focus the action on visible events."
    )
    revised = _proposal(
        proposal_id="proposal-002",
        action="Compare visible login and transfer events.",
        revised_from_proposal_id=original.proposal_id,
    )

    modified_original, proposed_revision = apply_human_decision(
        original, modification, revised
    )

    assert modification.instruction_or_reason == "Focus the action on visible events."
    assert modified_original.status == "MODIFIED"
    assert proposed_revision.status == "PROPOSED"
    assert proposed_revision.revised_from_proposal_id == original.proposal_id
    assert original.status == "PROPOSED"


def test_modify_requires_instruction_and_correct_revision_lineage() -> None:
    original = _proposal()
    revised = _proposal(proposal_id="proposal-002", revised_from_proposal_id="proposal-003")

    try:
        apply_human_decision(
            original,
            _decision("MODIFY", instruction_or_reason="Change the evidence focus."),
            revised,
        )
    except ValueError as error:
        assert "lineage" in str(error)
    else:
        raise AssertionError("a revised proposal must retain lineage")


def test_domain_records_are_immutable() -> None:
    proposal = _proposal()

    try:
        proposal.status = "APPROVED"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("proposal records must be immutable")
