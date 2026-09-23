"""V0 orchestration of governed proposal generation and human decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from investigation.models import AnalyticalActionProposal, HumanDecision, InvestigationRecord
from investigation.package_access import load_investigator_package
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import LocalProposalAgent


@dataclass(frozen=True)
class ApprovalLoopState:
    """The persisted V0 records the future UI needs to display."""

    investigation: InvestigationRecord
    proposals: tuple[AnalyticalActionProposal, ...]
    decisions: tuple[HumanDecision, ...]


@dataclass(frozen=True)
class ProposalGenerationResult:
    """An unpersisted plan paired with the resulting persisted workflow state."""

    provisional_plan: str
    state: ApprovalLoopState


class ApprovalLoopService:
    """Compose Tasks 1-4 without executing proposed analytical actions."""

    def __init__(
        self, store: SQLiteInvestigationStore, proposal_agent: LocalProposalAgent
    ) -> None:
        self._store = store
        self._proposal_agent = proposal_agent

    def start_investigation(
        self,
        case_reference: str,
        package_directory: Path,
        investigator_instruction: str,
    ) -> ProposalGenerationResult:
        """Generate and persist the first proposed action for one investigation."""
        context = load_investigator_package(package_directory)
        created_at = _utc_now()
        investigation = InvestigationRecord(
            _new_identifier("investigation"), case_reference, created_at, created_at
        )
        generated = self._proposal_agent.propose(
            context,
            investigator_instruction,
            _new_identifier("proposal"),
            _utc_now(),
        )
        self._store.add_investigation_with_initial_proposal(
            investigation, generated.proposal
        )
        return ProposalGenerationResult(
            generated.provisional_plan, self.get_state(investigation.investigation_id)
        )

    def approve(self, investigation_id: str, proposal_id: str) -> ApprovalLoopState:
        """Persist approval of exactly one existing proposed action."""
        proposal = self._persisted_proposal(investigation_id, proposal_id)
        self._store.persist_human_decision(
            proposal,
            HumanDecision(
                _new_identifier("decision"), proposal_id, "APPROVE", _utc_now()
            ),
        )
        return self.get_state(investigation_id)

    def decline(
        self,
        investigation_id: str,
        proposal_id: str,
        instruction_or_reason: str | None = None,
    ) -> ApprovalLoopState:
        """Persist decline of exactly one existing proposed action."""
        proposal = self._persisted_proposal(investigation_id, proposal_id)
        self._store.persist_human_decision(
            proposal,
            HumanDecision(
                _new_identifier("decision"),
                proposal_id,
                "DECLINE",
                _utc_now(),
                instruction_or_reason,
            ),
        )
        return self.get_state(investigation_id)

    def modify(
        self,
        investigation_id: str,
        proposal_id: str,
        package_directory: Path,
        modification_instruction: str,
    ) -> ProposalGenerationResult:
        """Generate and atomically persist one lineage-preserving proposal revision."""
        original = self._persisted_proposal(investigation_id, proposal_id)
        decision = HumanDecision(
            _new_identifier("decision"),
            proposal_id,
            "MODIFY",
            _utc_now(),
            modification_instruction,
        )
        generated = self._proposal_agent.propose(
            load_investigator_package(package_directory),
            _build_revision_instruction(original, modification_instruction),
            _new_identifier("proposal"),
            _utc_now(),
        )
        revised = replace(
            generated.proposal,
            status="PROPOSED",
            revised_from_proposal_id=original.proposal_id,
        )
        self._store.persist_human_decision(original, decision, revised)
        return ProposalGenerationResult(
            generated.provisional_plan, self.get_state(investigation_id)
        )

    def get_state(self, investigation_id: str) -> ApprovalLoopState:
        """Return only the approved persisted V0 workflow records."""
        return ApprovalLoopState(
            self._store.get_investigation(investigation_id),
            self._store.list_proposals(investigation_id),
            self._store.list_decisions(investigation_id),
        )

    def _persisted_proposal(
        self, investigation_id: str, proposal_id: str
    ) -> AnalyticalActionProposal:
        for proposal in self._store.list_proposals(investigation_id):
            if proposal.proposal_id == proposal_id:
                return proposal
        raise ValueError("proposal does not belong to investigation")


def _build_revision_instruction(
    original: AnalyticalActionProposal, modification_instruction: str
) -> str:
    """Provide only the current visible proposal and human modification request."""
    return (
        "Revise the existing proposed next analytical action in response to the "
        "human modification instruction below. Return a revised proposal that "
        "responds to that instruction.\n\n"
        f"Original action: {original.action}\n"
        f"Original purpose: {original.purpose}\n"
        f"Original why now: {original.why_now}\n"
        f"Original data to be used: {original.data_to_be_used}\n"
        f"Original expected output: {original.expected_output}\n\n"
        f"Human modification instruction: {modification_instruction}"
    )


def _new_identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
