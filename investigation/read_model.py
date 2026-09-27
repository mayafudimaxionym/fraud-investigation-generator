"""Side-effect-free V0.5 projections from authoritative persisted facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from investigation.case_catalog import AvailableInvestigatorCase, ConfiguredCaseCatalog
from investigation.models import (
    AgentOperation,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
    InvestigationRecord,
)
from investigation.package_access import InvestigatorPackageContext
from investigation.persistence import DeclineReconsiderationResult, SQLiteInvestigationStore


class PersistedLifecycleState(str, Enum):
    READY = "READY"
    AGENT_WORKING = "AGENT_WORKING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    ATTENTION = "ATTENTION"


class AttentionReason(str, Enum):
    MISSING_PACKAGE_ASSOCIATION = "MISSING_PACKAGE_ASSOCIATION"
    MISSING_OBJECTIVE = "MISSING_OBJECTIVE"
    DECLINE_RECONSIDERATION_INCOMPLETE = "DECLINE_RECONSIDERATION_INCOMPLETE"
    SAFE_CONTEXT_UNAVAILABLE = "SAFE_CONTEXT_UNAVAILABLE"
    OPERATION_FAILED = "OPERATION_FAILED"
    OPERATION_INTERRUPTED = "OPERATION_INTERRUPTED"


class ProjectionIntegrityError(ValueError):
    """Persisted facts cannot safely be projected as one investigator lifecycle."""


@dataclass(frozen=True)
class InvestigatorOperation:
    """Investigator-safe operation state without runner/process implementation details."""

    operation_id: str
    operation_type: str
    status: str
    failure_category: str | None


@dataclass(frozen=True)
class InvestigationSummary:
    investigation_id: str
    case_reference: str
    package_association: str | None
    domain: str | None
    lifecycle_state: PersistedLifecycleState
    attention_reason: AttentionReason | None
    current_or_latest_action: str | None
    last_activity: datetime
    latest_operation: InvestigatorOperation | None


@dataclass(frozen=True)
class InvestigationDetail:
    investigation: InvestigationRecord
    case: AvailableInvestigatorCase | None
    context: InvestigatorPackageContext | None
    lifecycle_state: PersistedLifecycleState
    attention_reason: AttentionReason | None
    current_direction: InvestigationDirection | None
    direction_history: tuple[InvestigationDirection, ...]
    active_proposal: AnalyticalActionProposal | None
    current_or_last_proposal: AnalyticalActionProposal | None
    proposal_history: tuple[AnalyticalActionProposal, ...]
    decision_history: tuple[HumanDecision, ...]
    decline_reconsideration_results: tuple[DeclineReconsiderationResult, ...]
    last_activity: datetime
    latest_operation: InvestigatorOperation | None


class InvestigationReadProjector:
    """Projects persisted investigation facts without mutations, models, or UI state."""

    def __init__(self, store: SQLiteInvestigationStore, catalog: ConfiguredCaseCatalog) -> None:
        self._store = store
        self._catalog = catalog

    def list_investigations(self) -> tuple[InvestigationSummary, ...]:
        """Return one current associated summary plus each legacy recovery entry."""
        associated: dict[str, InvestigationSummary] = {}
        unassociated: list[InvestigationSummary] = []
        for investigation in self._store.list_investigations():
            summary = self._summary(self.detail(investigation.investigation_id))
            if summary.package_association is None:
                unassociated.append(summary)
                continue
            current = associated.get(summary.package_association)
            if current is None or self._activity_key(summary) > self._activity_key(current):
                associated[summary.package_association] = summary
        summaries = (*associated.values(), *unassociated)
        return tuple(sorted(summaries, key=self._activity_key, reverse=True))

    def detail(self, investigation_id: str) -> InvestigationDetail:
        """Reconstruct one complete investigator-safe read projection."""
        investigation = self._store.get_investigation(investigation_id)
        directions = self._store.list_directions(investigation_id)
        self._validate_direction_history(directions)
        proposals = self._store.list_proposals(investigation_id)
        decisions = self._store.list_decisions(investigation_id)
        results = self._store.list_decline_reconsideration_results(investigation_id)
        operations = self._store.list_agent_operations(investigation_id)
        proposal_by_id = {proposal.proposal_id: proposal for proposal in proposals}
        decision_by_id = {decision.decision_id: decision for decision in decisions}
        self._validate_active_operations(operations)
        self._validate_decision_lifecycle(decisions, proposal_by_id, operations)
        self._validate_reconsideration_results(results, proposal_by_id, decision_by_id)

        attention_reason, case, context = self._context_state(investigation)
        active = self._active_proposal(proposals)
        incomplete_decline = self._incomplete_decline(decisions, results)
        latest_operation = self._latest_operation(operations)
        if attention_reason is None:
            if latest_operation is not None and latest_operation.status == "FAILED":
                attention_reason = AttentionReason.OPERATION_FAILED
            elif latest_operation is not None and latest_operation.status == "INTERRUPTED":
                attention_reason = AttentionReason.OPERATION_INTERRUPTED
            elif (
                latest_operation is None or latest_operation.status == "COMPLETED"
            ) and incomplete_decline is not None:
                attention_reason = AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE

        linked_replacement = self._linked_active_replacement(results, proposal_by_id)
        if linked_replacement is not None:
            active = linked_replacement
        lifecycle = self._lifecycle(attention_reason, latest_operation, active, decisions)
        current_or_last = self._current_or_last(
            lifecycle, active, proposals, decisions, incomplete_decline, proposal_by_id
        )
        return InvestigationDetail(
            investigation, case, context, lifecycle, attention_reason,
            directions[-1] if directions else None, directions, active, current_or_last,
            proposals, decisions, results,
            self._last_activity(
                investigation, directions, proposals, decisions, results, operations
            ),
            self._operation_projection(latest_operation),
        )

    def _context_state(
        self, investigation: InvestigationRecord
    ) -> tuple[AttentionReason | None, AvailableInvestigatorCase | None, InvestigatorPackageContext | None]:
        if investigation.package_association is None:
            return AttentionReason.MISSING_PACKAGE_ASSOCIATION, None, None
        if investigation.objective is None:
            return AttentionReason.MISSING_OBJECTIVE, None, None
        try:
            case, context = self._catalog.load_case(investigation.package_association)
        except ValueError:
            return AttentionReason.SAFE_CONTEXT_UNAVAILABLE, None, None
        return None, case, context

    @staticmethod
    def _active_proposal(
        proposals: tuple[AnalyticalActionProposal, ...]
    ) -> AnalyticalActionProposal | None:
        active = tuple(proposal for proposal in proposals if proposal.status == "PROPOSED")
        if len(active) > 1:
            raise ProjectionIntegrityError("persisted workflow state contains multiple PROPOSED proposals")
        return active[0] if active else None

    @staticmethod
    def _validate_direction_history(directions: tuple[InvestigationDirection, ...]) -> None:
        if directions and tuple(item.version for item in directions) != tuple(range(1, len(directions) + 1)):
            raise ProjectionIntegrityError("persisted direction history has inconsistent versions")

    @staticmethod
    def _validate_reconsideration_results(
        results: tuple[DeclineReconsiderationResult, ...],
        proposals: dict[str, AnalyticalActionProposal],
        decisions: dict[str, HumanDecision],
    ) -> None:
        for result in results:
            decision = decisions.get(result.decline_decision_id)
            proposal = proposals.get(result.replacement_proposal_id)
            if decision is None or decision.decision_type != "DECLINE":
                raise ProjectionIntegrityError("decline reconsideration result has an invalid decision")
            if proposal is None or proposal.revised_from_proposal_id is not None:
                raise ProjectionIntegrityError("decline reconsideration result has an invalid replacement")

    @staticmethod
    def _validate_decision_lifecycle(
        decisions: tuple[HumanDecision, ...],
        proposals: dict[str, AnalyticalActionProposal],
        operations: tuple[AgentOperation, ...],
    ) -> None:
        expected_status = {
            "APPROVE": "APPROVED",
            "DECLINE": "DECLINED",
            "MODIFY": "MODIFIED",
        }
        for decision in decisions:
            proposal = proposals.get(decision.proposal_id)
            if proposal is None or proposal.status != expected_status[decision.decision_type]:
                raise ProjectionIntegrityError("decision does not match its persisted proposal lifecycle")
        for decision in decisions:
            if decision.decision_type != "MODIFY":
                continue
            revisions = tuple(
                proposal for proposal in proposals.values()
                if proposal.revised_from_proposal_id == decision.proposal_id
            )
            if len(revisions) > 1:
                raise ProjectionIntegrityError("MODIFY decision has multiple persisted revisions")
            attempts = tuple(
                operation
                for operation in operations
                if operation.operation_type == "MODIFY"
                and operation.triggering_decision_id == decision.decision_id
            )
            has_completed_attempt = any(
                operation.status == "COMPLETED" for operation in attempts
            )
            if has_completed_attempt and len(revisions) != 1:
                raise ProjectionIntegrityError(
                    "completed MODIFY operation does not have exactly one persisted revision"
                )
            if attempts and not has_completed_attempt and revisions:
                raise ProjectionIntegrityError(
                    "incomplete MODIFY operation cannot have a persisted revision"
                )
            if not attempts and len(revisions) != 1:
                raise ProjectionIntegrityError(
                    "legacy MODIFY decision does not have exactly one persisted revision"
                )

    @staticmethod
    def _validate_active_operations(operations: tuple[AgentOperation, ...]) -> None:
        active = tuple(
            operation
            for operation in operations
            if operation.status in ("PENDING_RENDER", "RUNNING")
        )
        if len(active) > 1:
            raise ProjectionIntegrityError(
                "persisted workflow state contains multiple active agent operations"
            )

    @staticmethod
    def _latest_operation(
        operations: tuple[AgentOperation, ...]
    ) -> AgentOperation | None:
        return (
            max(operations, key=lambda item: (item.created_at, item.operation_id))
            if operations
            else None
        )

    @staticmethod
    def _operation_projection(
        operation: AgentOperation | None,
    ) -> InvestigatorOperation | None:
        if operation is None:
            return None
        return InvestigatorOperation(
            operation.operation_id,
            operation.operation_type,
            operation.status,
            operation.failure_category,
        )

    @staticmethod
    def _incomplete_decline(
        decisions: tuple[HumanDecision, ...], results: tuple[DeclineReconsiderationResult, ...]
    ) -> HumanDecision | None:
        completed = {result.decline_decision_id for result in results}
        pending = tuple(
            decision for decision in decisions
            if decision.decision_type == "DECLINE" and decision.decision_id not in completed
        )
        return max(pending, key=lambda item: (item.decided_at, item.decision_id)) if pending else None

    @staticmethod
    def _linked_active_replacement(
        results: tuple[DeclineReconsiderationResult, ...],
        proposals: dict[str, AnalyticalActionProposal],
    ) -> AnalyticalActionProposal | None:
        if not results:
            return None
        active = tuple(
            proposals[result.replacement_proposal_id]
            for result in results
            if proposals[result.replacement_proposal_id].status == "PROPOSED"
        )
        if len(active) > 1:
            raise ProjectionIntegrityError("multiple decline replacements are PROPOSED")
        return active[0] if active else None

    @staticmethod
    def _lifecycle(
        attention_reason: AttentionReason | None,
        latest_operation: AgentOperation | None,
        active: AnalyticalActionProposal | None,
        decisions: tuple[HumanDecision, ...],
    ) -> PersistedLifecycleState:
        if attention_reason is not None:
            return PersistedLifecycleState.ATTENTION
        if latest_operation is not None and latest_operation.status in (
            "PENDING_RENDER",
            "RUNNING",
        ):
            return PersistedLifecycleState.AGENT_WORKING
        if active is not None:
            return PersistedLifecycleState.NEEDS_REVIEW
        if decisions and max(decisions, key=lambda item: (item.decided_at, item.decision_id)).decision_type == "APPROVE":
            return PersistedLifecycleState.APPROVED
        return PersistedLifecycleState.READY

    @staticmethod
    def _current_or_last(
        lifecycle: PersistedLifecycleState,
        active: AnalyticalActionProposal | None,
        proposals: tuple[AnalyticalActionProposal, ...],
        decisions: tuple[HumanDecision, ...],
        incomplete_decline: HumanDecision | None,
        proposal_by_id: dict[str, AnalyticalActionProposal],
    ) -> AnalyticalActionProposal | None:
        if lifecycle is PersistedLifecycleState.NEEDS_REVIEW:
            return active
        if lifecycle is PersistedLifecycleState.ATTENTION and incomplete_decline is not None:
            return proposal_by_id[incomplete_decline.proposal_id]
        if lifecycle is PersistedLifecycleState.APPROVED:
            approved = max(
                (decision for decision in decisions if decision.decision_type == "APPROVE"),
                key=lambda item: (item.decided_at, item.decision_id),
            )
            return proposal_by_id[approved.proposal_id]
        return max(proposals, key=lambda item: (item.created_at, item.proposal_id)) if proposals else None

    @staticmethod
    def _last_activity(
        investigation: InvestigationRecord,
        directions: tuple[InvestigationDirection, ...],
        proposals: tuple[AnalyticalActionProposal, ...],
        decisions: tuple[HumanDecision, ...],
        results: tuple[DeclineReconsiderationResult, ...],
        operations: tuple[AgentOperation, ...],
    ) -> datetime:
        return max(
            investigation.created_at, investigation.updated_at,
            *(item.created_at for item in directions),
            *(item.created_at for item in proposals),
            *(item.decided_at for item in decisions),
            *(item.created_at for item in results),
            *(item.created_at for item in operations),
            *(item.updated_at for item in operations),
        )

    @staticmethod
    def _activity_key(summary: InvestigationSummary) -> tuple[datetime, str]:
        return summary.last_activity, summary.investigation_id

    @staticmethod
    def _summary(detail: InvestigationDetail) -> InvestigationSummary:
        return InvestigationSummary(
            detail.investigation.investigation_id,
            detail.investigation.case_reference,
            detail.investigation.package_association,
            detail.case.domain if detail.case is not None else None,
            detail.lifecycle_state,
            detail.attention_reason,
            detail.current_or_last_proposal.action if detail.current_or_last_proposal else None,
            detail.last_activity,
            detail.latest_operation,
        )
