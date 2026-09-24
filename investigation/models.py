"""Minimal, persistence-independent V0 and V0.5 investigation domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


PROPOSAL_STATUSES = ("PROPOSED", "APPROVED", "DECLINED", "MODIFIED")
DECISION_TYPES = ("APPROVE", "MODIFY", "DECLINE")
DIRECTION_PROVENANCE = ("INITIAL", "MODIFY", "DECLINE_REDIRECT")


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_timestamp(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")


def _require_text_tuple(value: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    for item in value:
        _require_non_blank(item, field_name)


@dataclass(frozen=True)
class InvestigationRecord:
    """The V0.5 identity, context, and optional governed package metadata."""

    investigation_id: str
    case_reference: str
    created_at: datetime
    updated_at: datetime
    objective: str | None = None
    package_association: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.investigation_id, "investigation_id")
        _require_non_blank(self.case_reference, "case_reference")
        _require_timestamp(self.created_at, "created_at")
        _require_timestamp(self.updated_at, "updated_at")
        if self.objective is not None and not isinstance(self.objective, str):
            raise ValueError("objective must be a string or None")
        if self.package_association is not None:
            _require_non_blank(self.package_association, "package_association")


@dataclass(frozen=True)
class InvestigationDirection:
    """One versioned, provisional V0.5 investigation-direction snapshot."""

    direction_id: str
    investigation_id: str
    version: int
    competing_explanations: tuple[str, ...]
    plan_steps: tuple[str, ...]
    created_at: datetime
    provenance: str
    trigger_reference_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.direction_id, "direction_id")
        _require_non_blank(self.investigation_id, "investigation_id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version <= 0:
            raise ValueError("version must be a positive integer")
        _require_text_tuple(self.competing_explanations, "competing_explanations")
        _require_text_tuple(self.plan_steps, "plan_steps")
        _require_timestamp(self.created_at, "created_at")
        if self.provenance not in DIRECTION_PROVENANCE:
            raise ValueError(f"provenance must be one of {DIRECTION_PROVENANCE}")
        if self.trigger_reference_id is not None:
            _require_non_blank(self.trigger_reference_id, "trigger_reference_id")


@dataclass(frozen=True)
class AnalyticalActionProposal:
    """One human-reviewable next analytical action in V0."""

    proposal_id: str
    action: str
    purpose: str
    why_now: str
    data_to_be_used: str
    expected_output: str
    status: str
    created_at: datetime
    revised_from_proposal_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "proposal_id",
            "action",
            "purpose",
            "why_now",
            "data_to_be_used",
            "expected_output",
        ):
            _require_non_blank(getattr(self, field_name), field_name)
        if self.status not in PROPOSAL_STATUSES:
            raise ValueError(f"status must be one of {PROPOSAL_STATUSES}")
        _require_timestamp(self.created_at, "created_at")
        if self.revised_from_proposal_id is not None:
            _require_non_blank(self.revised_from_proposal_id, "revised_from_proposal_id")
            if self.revised_from_proposal_id == self.proposal_id:
                raise ValueError("revised_from_proposal_id must differ from proposal_id")


@dataclass(frozen=True)
class HumanDecision:
    """An immutable human decision associated with one proposal."""

    decision_id: str
    proposal_id: str
    decision_type: str
    decided_at: datetime
    instruction_or_reason: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.decision_id, "decision_id")
        _require_non_blank(self.proposal_id, "proposal_id")
        if self.decision_type not in DECISION_TYPES:
            raise ValueError(f"decision_type must be one of {DECISION_TYPES}")
        _require_timestamp(self.decided_at, "decided_at")
        if self.instruction_or_reason is not None:
            _require_non_blank(self.instruction_or_reason, "instruction_or_reason")
        if self.decision_type == "MODIFY" and self.instruction_or_reason is None:
            raise ValueError("MODIFY requires an instruction")
        if self.decision_type == "APPROVE" and self.instruction_or_reason is not None:
            raise ValueError("APPROVE must not include an instruction or reason")


def apply_human_decision(
    proposal: AnalyticalActionProposal,
    decision: HumanDecision,
    revised_proposal: AnalyticalActionProposal | None = None,
) -> tuple[AnalyticalActionProposal, ...]:
    """Represent the approved V0 decision lifecycle without side effects."""
    if proposal.status != "PROPOSED":
        raise ValueError("only a PROPOSED proposal may receive a decision")
    if decision.proposal_id != proposal.proposal_id:
        raise ValueError("decision proposal_id must match the proposal")

    if decision.decision_type == "APPROVE":
        if revised_proposal is not None:
            raise ValueError("APPROVE must not include a revised proposal")
        return (replace(proposal, status="APPROVED"),)

    if decision.decision_type == "DECLINE":
        if revised_proposal is not None:
            raise ValueError("DECLINE must not include a revised proposal")
        return (replace(proposal, status="DECLINED"),)

    if revised_proposal is None:
        raise ValueError("MODIFY requires a revised proposal")
    if revised_proposal.status != "PROPOSED":
        raise ValueError("revised proposal must have PROPOSED status")
    if revised_proposal.revised_from_proposal_id != proposal.proposal_id:
        raise ValueError("revised proposal must preserve lineage to the original proposal")

    return (replace(proposal, status="MODIFIED"), revised_proposal)
