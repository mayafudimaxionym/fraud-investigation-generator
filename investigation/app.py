"""Investigator-facing V0.5 Streamlit presentation/controller layer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Mapping, Sequence
from uuid import uuid4

import streamlit as _streamlit

from investigation.approval_loop import InvestigatorReadyApprovalLoopService, InvestigatorReadyServiceError
from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG, ConfiguredCaseCatalog
from investigation.models import (
    AgentOperation,
    AnalyticalActionProposal,
    HumanDecision,
    InvestigationDirection,
)
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import (
    LocalProposalAgent,
    OllamaProposalClient,
    ProposalModelError,
    ProposalModelFailureCategory,
    ProposalOllamaConfig,
)
from investigation.read_model import AttentionReason, InvestigationDetail, InvestigationReadProjector, PersistedLifecycleState

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DATABASE_PATH_ENVIRONMENT_VARIABLE = "INVESTIGATION_DATABASE_PATH"
INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE = (
    "The local model configuration is invalid. Ask the application administrator "
    "to verify the deployment settings."
)
INVALID_DEPLOYMENT_CONFIGURATION_MESSAGE = (
    "The application configuration is invalid. Ask the application administrator "
    "to verify the deployment settings."
)
DEFAULT_OBJECTIVE = "Investigate the reported suspicious activity, identify relevant patterns and relationships, and assess the plausible explanations without assuming any explanation is established in advance."

_RENDER_ACKNOWLEDGEMENT = _streamlit.components.v2.component(
    "agent_operation_render_acknowledgement",
    js="""
    export default function(component) {
        const { data, setTriggerValue } = component;
        let cancelled = false;
        requestAnimationFrame(() => requestAnimationFrame(() => {
            if (!cancelled) {
                setTriggerValue("acknowledged_operation_id", data.operationId);
            }
        }));
        return () => { cancelled = true; };
    }
    """,
)

_RUNNING_OPERATION_REFRESH = _streamlit.components.v2.component(
    "running_operation_refresh",
    js="""
    export default function(component) {
        const { data, setTriggerValue } = component;
        const timeoutId = setTimeout(() => {
            setTriggerValue(
                "refresh_nonce",
                `${data.operationId}:${Date.now()}`,
            );
        }, data.delayMs);
        return () => { clearTimeout(timeoutId); };
    }
    """,
)


def configured_database_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return an absolute deployment path with a repository-root default."""
    values = os.environ if environment is None else environment
    configured = values.get(_DATABASE_PATH_ENVIRONMENT_VARIABLE)
    if configured is None or not configured.strip():
        return _REPOSITORY_ROOT / "investigations.sqlite"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"{_DATABASE_PATH_ENVIRONMENT_VARIABLE} must be an absolute path"
        )
    return path.resolve()


try:
    DATABASE_PATH = configured_database_path()
    _DATABASE_CONFIGURATION_ERROR: str | None = None
except (OSError, ValueError):
    DATABASE_PATH = _REPOSITORY_ROOT / "investigations.sqlite"
    _DATABASE_CONFIGURATION_ERROR = INVALID_DEPLOYMENT_CONFIGURATION_MESSAGE


class _UnavailableProposalClient:
    """Preserve durable failure handling when deployment configuration is invalid."""

    def preflight(self) -> None:
        raise ProposalModelError(
            ProposalModelFailureCategory.MODEL_UNAVAILABLE,
            INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE,
        )

    def generate(self, _: str) -> str:
        self.preflight()
        raise AssertionError("unreachable")


def select_active_proposal(proposals: Sequence[AnalyticalActionProposal]) -> AnalyticalActionProposal | None:
    proposed = tuple(item for item in proposals if item.status == "PROPOSED")
    if len(proposed) > 1:
        raise ValueError("persisted workflow state contains multiple PROPOSED proposals")
    return proposed[0] if proposed else None


def optional_decline_reason(value: str) -> str | None:
    return value if value.strip() else None


def _build_dependencies() -> tuple[SQLiteInvestigationStore, ConfiguredCaseCatalog, InvestigationReadProjector, InvestigatorReadyApprovalLoopService | None, str | None]:
    """Create thread-local SQLite-backed dependencies for one Streamlit execution."""
    store = SQLiteInvestigationStore(DATABASE_PATH)
    catalog = DEFAULT_LOCAL_CASE_CATALOG
    projector = InvestigationReadProjector(store, catalog)
    try:
        client = OllamaProposalClient(ProposalOllamaConfig.from_environment())
    except ValueError:
        client = _UnavailableProposalClient()
        return (
            store,
            catalog,
            projector,
            InvestigatorReadyApprovalLoopService(
                store, catalog, LocalProposalAgent(client), client
            ),
            INVALID_LOCAL_MODEL_CONFIGURATION_MESSAGE,
        )
    return store, catalog, projector, InvestigatorReadyApprovalLoopService(store, catalog, LocalProposalAgent(client), client), None


def _render_context(st: object, context: object) -> None:
    st.subheader("Investigation context")
    st.markdown("**Investigation request**")
    st.write(context.investigation_request)
    with st.expander("Customer/support context"):
        st.write(context.customer_support_statement)
    with st.expander("Prior analyst note"):
        st.write(context.prior_analyst_note)
    st.markdown("**Available structured datasets**")
    for dataset in context.datasets:
        st.write(f"{dataset.dataset_name}: {dataset.row_count} rows; fields: {', '.join(dataset.field_names)}")


def _render_proposal(st: object, proposal: AnalyticalActionProposal, heading: str = "Proposed next analytical action") -> None:
    st.subheader(heading)
    for label, value in (("Action", proposal.action), ("Purpose", proposal.purpose), ("Why now", proposal.why_now), ("Data to be used", proposal.data_to_be_used), ("Expected output", proposal.expected_output)):
        st.write(f"**{label}:** {value}")


def _failure_message(error: Exception) -> str:
    category = getattr(error, "category", None)
    return operation_failure_message(str(getattr(category, "value", category)))


def operation_working_label(operation: str) -> str:
    """Return the only transient investigator-facing label for an explicit request."""
    return {
        "START": "Preparing investigation approach",
        "MODIFY": "Revising proposed action",
        "DECLINE_REDIRECT": "Adjusting investigation plan",
        "DECLINE_RECONSIDER": "Adjusting investigation plan",
    }[operation]


def operation_failure_message(category: str | None) -> str:
    """Translate one persisted safe failure category into investigator language."""
    return {
        "SERVICE_UNAVAILABLE": "The local model service is unavailable.",
        "MODEL_UNAVAILABLE": "The configured local model is unavailable.",
        "REQUEST_TIMEOUT": "The local model request timed out.",
        "GENERATION_ERROR": (
            "The agent response did not satisfy the required response contract."
        ),
        "PERSISTENCE_ERROR": "The generated investigation state could not be saved safely.",
        "SAFE_CONTEXT_UNAVAILABLE": "The configured case context is unavailable.",
        "PACKAGE_ASSOCIATION_UNAVAILABLE": "The investigation case association is unavailable.",
        "OBJECTIVE_UNAVAILABLE": "The persisted investigation objective is unavailable.",
        "DIRECTION_UNAVAILABLE": "The current investigation direction is unavailable.",
        "UNKNOWN_FAILURE": "The agent request ended with an unknown safe failure category.",
    }.get(category, "The investigation request could not be completed.")


def operation_recovery_message(operation_type: str) -> str:
    """Describe only the authoritative state left by an incomplete operation."""
    return {
        "START": "No new proposal was saved. No action was authorized.",
        "MODIFY": (
            "The original proposal remains MODIFIED. No new revision proposal was "
            "saved and no action was authorized."
        ),
        "DECLINE_REDIRECT": (
            "The original proposal remains DECLINED. No new replacement proposal was "
            "saved and no action was authorized."
        ),
        "DECLINE_RECONSIDER": (
            "The original proposal remains DECLINED. No new replacement proposal was "
            "saved and no action was authorized."
        ),
    }[operation_type]


@_streamlit.cache_resource(show_spinner=False)
def process_runner_instance_id() -> str:
    """Return one stable identity for the lifetime of this Streamlit process."""
    return f"runner-{uuid4()}"


def _initialize(st: object) -> None:
    for key, value in {"v05_view": "list", "v05_active_id": None, "v05_error": None, "v05_new_objective": DEFAULT_OBJECTIVE}.items():
        st.session_state.setdefault(key, value)


def _show_investigation(st: object, investigation_id: str) -> None:
    st.session_state.v05_active_id = investigation_id
    st.session_state.v05_view = "detail"
    st.session_state.v05_error = None
    st.rerun()


def _prepare_and_show(
    st: object, prepare: Callable[[], AgentOperation]
) -> None:
    try:
        operation = prepare()
    except (InvestigatorReadyServiceError, ValueError, RuntimeError, OSError) as error:
        st.session_state.v05_error = _failure_message(error)
        st.rerun()
    else:
        _show_investigation(st, operation.investigation_id)


def _render_back(st: object) -> None:
    if st.button("← Back to Investigations"):
        st.session_state.v05_active_id = None
        st.session_state.v05_view = "list"
        st.session_state.v05_error = None
        st.rerun()


def _render_acknowledged(operation_id: str) -> bool:
    result = _RENDER_ACKNOWLEDGEMENT(
        data={"operationId": operation_id},
        key=f"operation-render-ack-{operation_id}",
        on_acknowledged_operation_id_change=lambda: None,
    )
    return result.acknowledged_operation_id == operation_id


def _schedule_running_refresh(operation_id: str) -> None:
    _RUNNING_OPERATION_REFRESH(
        data={"operationId": operation_id, "delayMs": 1000},
        key=f"operation-refresh-{operation_id}",
        on_refresh_nonce_change=lambda: None,
    )


def _render_list(st: object, projector: InvestigationReadProjector) -> None:
    st.title("Investigations")
    if st.button("+ New investigation", type="primary"):
        st.session_state.v05_view = "new"
        st.rerun()
    st.subheader("Recent investigations")
    for summary in projector.list_investigations():
        st.write(f"**{summary.case_reference}**" + (f" — {summary.domain}" if summary.domain else ""))
        st.write(f"{summary.lifecycle_state.value.replace('_', ' ').title()} · {summary.current_or_latest_action or 'No action yet'} · {summary.last_activity.isoformat()}")
        if st.button("Resume", key=f"resume-{summary.investigation_id}"):
            st.session_state.v05_active_id, st.session_state.v05_view = summary.investigation_id, "detail"
            st.rerun()


def _render_new(st: object, catalog: ConfiguredCaseCatalog, service: InvestigatorReadyApprovalLoopService | None) -> None:
    _render_back(st)
    st.title("New investigation")
    cases = catalog.available_cases()
    labels = {case.case_reference + (f" — {case.domain}" if case.domain else ""): case for case in cases}
    selected = labels[st.selectbox("Case", tuple(labels))]
    _, context = catalog.load_case(selected.association_id)
    _render_context(st, context)
    objective = st.text_area("Investigation objective", value=st.session_state.v05_new_objective, key="new-objective")
    if st.button("Start investigation", type="primary", disabled=service is None):
        st.session_state.v05_new_objective = objective
        _prepare_and_show(
            st,
            lambda: service.prepare_start_investigation(
                selected.association_id, objective
            ),
        )
    if service is None:
        st.info("Local model configuration is required before investigation reasoning can start.")


def _render_history(st: object, detail: InvestigationDetail) -> None:
    with st.expander("History"):
        for direction in detail.direction_history:
            st.write(f"Direction version {direction.version} · {direction.provenance} · {direction.created_at.isoformat()}")
        for proposal in detail.proposal_history:
            st.write(f"Proposal: {proposal.status}" + (" (revision of an earlier proposal)" if proposal.revised_from_proposal_id else ""))
        for decision in detail.decision_history:
            st.write(f"{decision.decision_type.title()} · {decision.decided_at.isoformat()}" + (f" — {decision.instruction_or_reason}" if decision.instruction_or_reason else ""))
        for result in detail.decline_reconsideration_results:
            st.write(f"Decline reconsideration completed · {result.created_at.isoformat()} · independent replacement proposed")


def _decision_for_active_review(
    detail: InvestigationDetail,
) -> HumanDecision | None:
    proposal = detail.active_proposal
    if proposal is None:
        return None
    if proposal.revised_from_proposal_id is not None:
        return next(
            (
                decision
                for decision in detail.decision_history
                if decision.decision_type == "MODIFY"
                and decision.proposal_id == proposal.revised_from_proposal_id
            ),
            None,
        )
    result = next(
        (
            item
            for item in detail.decline_reconsideration_results
            if item.replacement_proposal_id == proposal.proposal_id
        ),
        None,
    )
    if result is None:
        return None
    return next(
        (
            decision
            for decision in detail.decision_history
            if decision.decision_id == result.decline_decision_id
        ),
        None,
    )


def _previous_direction_for_review(
    detail: InvestigationDetail, decision: HumanDecision | None
) -> InvestigationDirection | None:
    current = detail.current_direction
    if (
        decision is None
        or current is None
        or current.version <= 1
        or current.trigger_reference_id != decision.decision_id
    ):
        return None
    return next(
        (
            direction
            for direction in detail.direction_history
            if direction.version == current.version - 1
        ),
        None,
    )


def _render_direction(
    st: object, direction: InvestigationDirection, heading: str
) -> None:
    st.subheader(heading)
    st.markdown("**Working explanations — none is currently established as a finding.**")
    for item in direction.competing_explanations:
        st.write(f"- {item}")
    st.markdown("**Provisional plan**")
    for item in direction.plan_steps:
        st.write(f"- {item}")


def _render_semantic_review_context(st: object, detail: InvestigationDetail) -> None:
    st.subheader("Human semantic review")
    objective = (
        detail.investigation.objective
        if detail.investigation.objective is not None
        else "Not recorded"
    )
    st.write(f"**Effective objective:** {objective}")
    decision = _decision_for_active_review(detail)
    if decision is not None:
        label = (
            "Persisted Modify instruction"
            if decision.decision_type == "MODIFY"
            else "Persisted Decline guidance"
        )
        value = decision.instruction_or_reason or "No additional guidance was provided."
        st.write(f"**{label}:** {value}")
    st.info(
        "This AI-generated direction and proposal are provisional. Verify that they "
        "follow the objective and any saved instruction, are appropriately scoped, "
        "and use the permitted evidence before approval. No action is authorized "
        "until you approve it."
    )
    previous = _previous_direction_for_review(detail, decision)
    if previous is not None:
        _render_direction(st, previous, "Previous direction for comparison")


def _render_attention(st: object, store: SQLiteInvestigationStore, catalog: ConfiguredCaseCatalog, detail: InvestigationDetail, service: InvestigatorReadyApprovalLoopService | None) -> None:
    reason = detail.attention_reason
    if reason in (AttentionReason.OPERATION_FAILED, AttentionReason.OPERATION_INTERRUPTED):
        operation = detail.latest_operation
        if operation is None:
            st.error("The persisted operation state is unavailable.")
            return
        if reason is AttentionReason.OPERATION_FAILED:
            st.error(operation_failure_message(operation.failure_category))
        else:
            st.warning("The previous processing attempt was interrupted.")
        st.write(operation_recovery_message(operation.operation_type))
        if st.button("Try again", disabled=service is None):
            _prepare_and_show(
                st, lambda: service.prepare_retry(operation.operation_id)
            )
    elif reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE:
        st.error("THE AGENT COULD NOT COMPLETE THE PLAN ADJUSTMENT")
        declined = next((item for item in detail.decision_history if item.decision_type == "DECLINE" and detail.current_or_last_proposal and item.proposal_id == detail.current_or_last_proposal.proposal_id), None)
        st.write("Your instruction is saved." if declined and declined.instruction_or_reason else "The previous proposal was declined without additional guidance.")
        st.write("The previous proposal remains DECLINED. No new proposal was created and no action was authorized.")
        if (
            declined is not None
            and detail.current_or_last_proposal is not None
            and st.button("Try again", disabled=service is None)
        ):
            _prepare_and_show(
                st,
                lambda: service.prepare_legacy_decline_reconsideration(
                    detail.investigation.investigation_id,
                    detail.current_or_last_proposal.proposal_id,
                ),
            )
    elif reason is AttentionReason.MISSING_PACKAGE_ASSOCIATION:
        st.error("This older investigation needs its case re-associated before it can continue.")
        cases = catalog.available_cases()
        labels = {case.case_reference: case for case in cases}
        selected = labels[st.selectbox("Case", tuple(labels), key="legacy-case")]
        if st.button("Associate case"):
            if service is not None:
                service.set_legacy_package_association_if_missing(detail.investigation.investigation_id, selected.association_id)
                st.rerun()
    elif reason is AttentionReason.MISSING_OBJECTIVE:
        st.error("This older investigation does not yet have a recorded investigation objective.")
        objective = st.text_area("Investigation objective", value=DEFAULT_OBJECTIVE, key="legacy-objective")
        if st.button("Save investigation objective", disabled=service is None):
            service.set_legacy_objective_if_missing(detail.investigation.investigation_id, objective)
            st.rerun()
    else:
        st.error("The configured case context is currently unavailable.")


def _render_working(
    st: object,
    detail: InvestigationDetail,
    service: InvestigatorReadyApprovalLoopService | None,
    runner_instance_id: str,
) -> None:
    operation = detail.latest_operation
    if operation is None:
        st.error("The persisted operation state is unavailable.")
        return
    st.subheader(operation_working_label(operation.operation_type))
    st.info("The agent is working. No new action is authorized during processing.")
    if operation.status == "RUNNING":
        _schedule_running_refresh(operation.operation_id)
        return
    if operation.status != "PENDING_RENDER":
        return
    if service is None:
        st.error("Local model configuration is required before processing can continue.")
        return
    if not _render_acknowledged(operation.operation_id):
        return
    try:
        service.claim_and_execute_operation(operation.operation_id, runner_instance_id)
    except (InvestigatorReadyServiceError, ValueError, RuntimeError, OSError):
        pass
    st.rerun()


def _render_detail(st: object, store: SQLiteInvestigationStore, catalog: ConfiguredCaseCatalog, projector: InvestigationReadProjector, service: InvestigatorReadyApprovalLoopService | None, runner_instance_id: str) -> None:
    detail = projector.detail(st.session_state.v05_active_id)
    _render_back(st)
    st.title(detail.investigation.case_reference)
    st.write(f"**Investigation objective:** {detail.investigation.objective if detail.investigation.objective is not None else 'Not recorded'}")
    if detail.context is not None:
        _render_context(st, detail.context)
    if detail.lifecycle_state is PersistedLifecycleState.ATTENTION:
        _render_attention(st, store, catalog, detail, service)
        _render_history(st, detail)
        return
    if detail.lifecycle_state is PersistedLifecycleState.AGENT_WORKING:
        _render_working(st, detail, service, runner_instance_id)
        _render_history(st, detail)
        return
    if detail.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW:
        _render_semantic_review_context(st, detail)
    if detail.current_direction:
        _render_direction(st, detail.current_direction, "Generated direction")
    if detail.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW and detail.active_proposal:
        _render_proposal(st, detail.active_proposal)
        if st.button("Approve", disabled=service is None):
            service.approve(
                detail.investigation.investigation_id,
                detail.active_proposal.proposal_id,
            )
            st.rerun()
        st.write("Keep the basic proposed action, but change it according to your instruction.")
        modification = st.text_area("Modification instruction", key="modify-instruction")
        if st.button("Modify", disabled=service is None):
            if not modification.strip(): st.error("Modification instruction must be non-empty.")
            else:
                _prepare_and_show(
                    st,
                    lambda: service.prepare_modify(
                        detail.investigation.investigation_id,
                        detail.active_proposal.proposal_id,
                        modification,
                    ),
                )
        guidance = st.text_area("Optional decline guidance", key="decline-guidance")
        st.write("The current proposal will be declined. The agent will reconsider the investigation plan using your instruction and return with a new proposed next action for your approval.")
        if st.button("Adjust investigation plan" if guidance.strip() else "Decline without guidance", disabled=service is None):
            _prepare_and_show(
                st,
                lambda: service.prepare_decline(
                    detail.investigation.investigation_id,
                    detail.active_proposal.proposal_id,
                    optional_decline_reason(guidance),
                ),
            )
    elif detail.lifecycle_state is PersistedLifecycleState.APPROVED and detail.current_or_last_proposal:
        st.success("ACTION APPROVED")
        st.write("This analytical action is authorized.\nAnalytical execution is not implemented in this version.")
        _render_proposal(st, detail.current_or_last_proposal, "Approved analytical action")
    _render_history(st, detail)


def main() -> None:
    import streamlit as st
    st.set_page_config(page_title="Fraud Investigation", layout="wide")
    _initialize(st)
    if _DATABASE_CONFIGURATION_ERROR is not None:
        st.error(_DATABASE_CONFIGURATION_ERROR)
        return
    store, catalog, projector, service, configuration_error = _build_dependencies()
    try:
        runner_instance_id = process_runner_instance_id()
        if service is not None:
            service.interrupt_previous_process_operations(runner_instance_id)
        if st.session_state.v05_error: st.error(st.session_state.v05_error)
        if st.session_state.v05_view == "new": _render_new(st, catalog, service)
        elif st.session_state.v05_active_id: _render_detail(st, store, catalog, projector, service, runner_instance_id)
        else: _render_list(st, projector)
        if configuration_error:
            with st.expander("Local model details"): st.write(configuration_error)
    finally:
        store.close()


if __name__ == "__main__":
    main()
