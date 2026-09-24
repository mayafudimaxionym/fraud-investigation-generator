"""V0 and V0.5 orchestration of governed proposal generation and human decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from investigation.case_catalog import ConfiguredCaseCatalog
from investigation.models import (
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
    InvestigationRecord,
)
from investigation.package_access import load_investigator_package
from investigation.persistence import (
    DeclineReconsiderationResult,
    SQLiteInvestigationStore,
)
from investigation.proposal_agent import (
    LocalProposalAgent,
    ProposalAgentResult,
    ProposalGenerationRequest,
    ProposalModelError,
    ProposalModelFailureCategory,
)


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


@dataclass(frozen=True)
class InvestigatorReadyState:
    """Authoritative V0.5 records needed for later lifecycle and UI projection."""

    investigation: InvestigationRecord
    current_direction: InvestigationDirection | None
    directions: tuple[InvestigationDirection, ...]
    proposals: tuple[AnalyticalActionProposal, ...]
    decisions: tuple[HumanDecision, ...]


class InvestigatorReadyServiceError(RuntimeError):
    """A recoverable V0.5 orchestration failure with an explicit phase."""

    def __init__(
        self,
        phase: str,
        category: ProposalModelFailureCategory | str,
        message: str,
        *,
        decline_committed: bool = False,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.category = category
        self.decline_committed = decline_committed


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


class InvestigatorReadyApprovalLoopService:
    """V0.5 orchestration with governed context and no analytical execution."""

    def __init__(
        self,
        store: SQLiteInvestigationStore,
        catalog: ConfiguredCaseCatalog,
        proposal_agent: LocalProposalAgent,
        preflight_client: object,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._proposal_agent = proposal_agent
        self._preflight_client = preflight_client

    def start_investigation(
        self,
        association_id: str,
        objective: str,
        investigator_instruction: str | None = None,
    ) -> InvestigatorReadyState:
        """Create the first V0.5 direction and proposal in one atomic write."""
        try:
            case, context = self._catalog.load_case(association_id)
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                "INITIAL", "SAFE_CONTEXT_UNAVAILABLE", "configured case is unavailable"
            ) from error
        if not isinstance(objective, str):
            raise InvestigatorReadyServiceError(
                "INITIAL", "OBJECTIVE_UNAVAILABLE", "investigation objective must be a string"
            )

        self._preflight("INITIAL", decline_committed=False)
        investigation_id = _new_identifier("investigation")
        created_at = _utc_now()
        generated = self._generate(
            ProposalGenerationRequest(
                context=context,
                objective=objective,
                proposal_id=_new_identifier("proposal"),
                created_at=_utc_now(),
                mode="INITIAL",
                investigator_instruction=investigator_instruction,
            ),
            "INITIAL",
            decline_committed=False,
        )
        investigation = InvestigationRecord(
            investigation_id,
            case.case_reference,
            created_at,
            created_at,
            objective,
            association_id,
        )
        direction = self._direction_from_result(
            investigation_id,
            1,
            generated,
            "INITIAL",
            None,
        )
        try:
            self._store.add_investigation_with_initial_direction_and_proposal(
                investigation, direction, generated.proposal
            )
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                "INITIAL", "PERSISTENCE_ERROR", "initial investigation state was not persisted"
            ) from error
        return self.get_state(investigation_id)

    def approve(self, investigation_id: str, proposal_id: str) -> InvestigatorReadyState:
        """Persist approval only; V0.5 never executes the approved action."""
        proposal = self._active_proposal(investigation_id, proposal_id)
        self._store.persist_human_decision(
            proposal,
            HumanDecision(_new_identifier("decision"), proposal_id, "APPROVE", _utc_now()),
        )
        return self.get_state(investigation_id)

    def modify(
        self, investigation_id: str, proposal_id: str, instruction: str
    ) -> InvestigatorReadyState:
        """Atomically persist a Modify decision, optional direction, and revision."""
        original = self._active_proposal(investigation_id, proposal_id)
        investigation, context, direction = self._reasoning_inputs(investigation_id, "MODIFY")
        if direction is None:
            raise InvestigatorReadyServiceError(
                "MODIFY", "DIRECTION_UNAVAILABLE", "current investigation direction is unavailable"
            )
        decision = HumanDecision(
            _new_identifier("decision"), proposal_id, "MODIFY", _utc_now(), instruction
        )
        self._preflight("MODIFY", decline_committed=False)
        generated = self._generate(
            ProposalGenerationRequest(
                context=context,
                objective=investigation.objective,
                proposal_id=_new_identifier("proposal"),
                created_at=_utc_now(),
                mode="MODIFY",
                investigator_instruction=instruction,
                current_direction=direction,
                source_proposal=original,
            ),
            "MODIFY",
            decline_committed=False,
        )
        next_direction = self._changed_direction(
            investigation_id, direction, generated, "MODIFY", decision.decision_id
        )
        revised = replace(
            generated.proposal,
            revised_from_proposal_id=original.proposal_id,
        )
        try:
            self._store.persist_modify_with_optional_direction(
                original, decision, revised, next_direction
            )
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                "MODIFY", "PERSISTENCE_ERROR", "modified investigation state was not persisted"
            ) from error
        return self.get_state(investigation_id)

    def decline(
        self,
        investigation_id: str,
        proposal_id: str,
        guidance: str | None = None,
    ) -> InvestigatorReadyState:
        """Commit Decline first, then perform the separate reconsideration phase."""
        proposal = self._active_proposal(investigation_id, proposal_id)
        decision = HumanDecision(
            _new_identifier("decision"), proposal_id, "DECLINE", _utc_now(), guidance
        )
        try:
            self._store.persist_human_decision(proposal, decision)
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                "DECLINE_COMMIT", "PERSISTENCE_ERROR", "decline decision was not persisted"
            ) from error
        return self._reconsider_decline(investigation_id, proposal_id, decision)

    def retry_decline_reconsideration(
        self, investigation_id: str, declined_proposal_id: str
    ) -> InvestigatorReadyState:
        """Retry only the post-decline phase; it never creates another decline decision."""
        proposal = self._proposal_for_investigation(investigation_id, declined_proposal_id)
        if proposal.status != "DECLINED":
            raise ValueError("reconsideration requires a DECLINED proposal")
        decision = self._decline_decision(investigation_id, declined_proposal_id)
        return self._reconsider_decline(investigation_id, declined_proposal_id, decision)

    def get_state(self, investigation_id: str) -> InvestigatorReadyState:
        """Reconstruct V0.5 authoritative state without Streamlit session data."""
        return InvestigatorReadyState(
            investigation=self._store.get_investigation(investigation_id),
            current_direction=self._store.get_current_direction(investigation_id),
            directions=self._store.list_directions(investigation_id),
            proposals=self._store.list_proposals(investigation_id),
            decisions=self._store.list_decisions(investigation_id),
        )

    def set_legacy_objective_if_missing(
        self, investigation_id: str, objective: str
    ) -> InvestigatorReadyState:
        """Complete missing legacy metadata once without agent reasoning or history changes."""
        self._store.set_objective_if_missing(investigation_id, objective)
        return self.get_state(investigation_id)

    def set_legacy_package_association_if_missing(
        self, investigation_id: str, association_id: str
    ) -> InvestigatorReadyState:
        """Attach only an explicitly selected configured case to a legacy investigation."""
        self._catalog.load_context(association_id)
        self._store.set_package_association_if_missing(investigation_id, association_id)
        return self.get_state(investigation_id)

    def _reconsider_decline(
        self,
        investigation_id: str,
        declined_proposal_id: str,
        decision: HumanDecision,
    ) -> InvestigatorReadyState:
        if self._store.get_decline_reconsideration_result(decision.decision_id) is not None:
            raise ValueError("decline decision already has a persisted replacement")
        if any(proposal.status == "PROPOSED" for proposal in self._store.list_proposals(investigation_id)):
            raise ValueError("investigation already has another active PROPOSED proposal")
        declined = self._proposal_for_investigation(investigation_id, declined_proposal_id)
        investigation, context, direction = self._reasoning_inputs(
            investigation_id, "DECLINE_RECONSIDERATION", decline_committed=True
        )
        if direction is None:
            raise InvestigatorReadyServiceError(
                "DECLINE_RECONSIDERATION",
                "DIRECTION_UNAVAILABLE",
                "current investigation direction is unavailable",
                decline_committed=True,
            )
        self._preflight("DECLINE_RECONSIDERATION", decline_committed=True)
        generated = self._generate(
            ProposalGenerationRequest(
                context=context,
                objective=investigation.objective,
                proposal_id=_new_identifier("proposal"),
                created_at=_utc_now(),
                mode="DECLINE_REDIRECT",
                current_direction=direction,
                source_proposal=declined,
                decline_guidance=decision.instruction_or_reason,
            ),
            "DECLINE_RECONSIDERATION",
            decline_committed=True,
        )
        next_direction = self._changed_direction(
            investigation_id,
            direction,
            generated,
            "DECLINE_REDIRECT",
            decision.decision_id,
        )
        result = DeclineReconsiderationResult(
            decision.decision_id, generated.proposal.proposal_id, _utc_now()
        )
        try:
            self._store.add_decline_reconsideration_result(
                investigation_id, next_direction, generated.proposal, result
            )
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                "DECLINE_RECONSIDERATION",
                "PERSISTENCE_ERROR",
                "reconsidered investigation state was not persisted",
                decline_committed=True,
            ) from error
        return self.get_state(investigation_id)

    def _reasoning_inputs(
        self,
        investigation_id: str,
        phase: str,
        *,
        decline_committed: bool = False,
    ) -> tuple[InvestigationRecord, object, InvestigationDirection | None]:
        investigation = self._store.get_investigation(investigation_id)
        if investigation.package_association is None:
            raise InvestigatorReadyServiceError(
                phase,
                "PACKAGE_ASSOCIATION_UNAVAILABLE",
                "investigation requires an explicit safe package association",
                decline_committed=decline_committed,
            )
        if investigation.objective is None:
            raise InvestigatorReadyServiceError(
                phase,
                "OBJECTIVE_UNAVAILABLE",
                "investigation requires an explicitly persisted objective",
                decline_committed=decline_committed,
            )
        try:
            _, context = self._catalog.load_case(investigation.package_association)
        except ValueError as error:
            raise InvestigatorReadyServiceError(
                phase,
                "SAFE_CONTEXT_UNAVAILABLE",
                "configured case is unavailable",
                decline_committed=decline_committed,
            ) from error
        return investigation, context, self._store.get_current_direction(investigation_id)

    def _preflight(self, phase: str, *, decline_committed: bool) -> None:
        try:
            self._preflight_client.preflight()
        except ProposalModelError as error:
            raise InvestigatorReadyServiceError(
                phase, error.category, str(error), decline_committed=decline_committed
            ) from error

    def _generate(
        self,
        request: ProposalGenerationRequest,
        phase: str,
        *,
        decline_committed: bool,
    ) -> ProposalAgentResult:
        try:
            return self._proposal_agent.generate(request)
        except ProposalModelError as error:
            raise InvestigatorReadyServiceError(
                phase, error.category, str(error), decline_committed=decline_committed
            ) from error

    def _changed_direction(
        self,
        investigation_id: str,
        current: InvestigationDirection,
        generated: ProposalAgentResult,
        provenance: str,
        trigger_reference_id: str,
    ) -> InvestigationDirection | None:
        if (
            generated.direction.competing_explanations == current.competing_explanations
            and generated.direction.plan_steps == current.plan_steps
        ):
            return None
        return self._direction_from_result(
            investigation_id,
            current.version + 1,
            generated,
            provenance,
            trigger_reference_id,
        )

    def _direction_from_result(
        self,
        investigation_id: str,
        version: int,
        generated: ProposalAgentResult,
        provenance: str,
        trigger_reference_id: str | None,
    ) -> InvestigationDirection:
        return InvestigationDirection(
            _new_identifier("direction"),
            investigation_id,
            version,
            generated.direction.competing_explanations,
            generated.direction.plan_steps,
            _utc_now(),
            provenance,
            trigger_reference_id,
        )

    def _active_proposal(
        self, investigation_id: str, proposal_id: str
    ) -> AnalyticalActionProposal:
        proposal = self._proposal_for_investigation(investigation_id, proposal_id)
        if proposal.status != "PROPOSED":
            raise ValueError("only a PROPOSED proposal may receive a decision")
        proposed = tuple(
            item for item in self._store.list_proposals(investigation_id) if item.status == "PROPOSED"
        )
        if len(proposed) != 1 or proposed[0].proposal_id != proposal_id:
            raise ValueError("persisted workflow state contains multiple PROPOSED proposals")
        return proposal

    def _proposal_for_investigation(
        self, investigation_id: str, proposal_id: str
    ) -> AnalyticalActionProposal:
        for proposal in self._store.list_proposals(investigation_id):
            if proposal.proposal_id == proposal_id:
                return proposal
        raise ValueError("proposal does not belong to investigation")

    def _decline_decision(
        self, investigation_id: str, proposal_id: str
    ) -> HumanDecision:
        for decision in self._store.list_decisions(investigation_id):
            if decision.proposal_id == proposal_id and decision.decision_type == "DECLINE":
                return decision
        raise ValueError("declined proposal has no persisted decline decision")


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
