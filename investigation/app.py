"""Investigator-facing V0.5 Streamlit presentation/controller layer."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from investigation.approval_loop import InvestigatorReadyApprovalLoopService, InvestigatorReadyServiceError
from investigation.case_catalog import DEFAULT_LOCAL_CASE_CATALOG, ConfiguredCaseCatalog
from investigation.models import AnalyticalActionProposal
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import LocalProposalAgent, OllamaProposalClient, ProposalOllamaConfig
from investigation.read_model import AttentionReason, InvestigationDetail, InvestigationReadProjector, PersistedLifecycleState

DATABASE_PATH = Path("investigations.sqlite")
DEFAULT_OBJECTIVE = "Investigate the reported suspicious activity, identify relevant patterns and relationships, and assess the plausible explanations without assuming any explanation is established in advance."


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
    except ValueError as error:
        return store, catalog, projector, None, str(error)
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
    return {
        "SERVICE_UNAVAILABLE": "The local model service is unavailable.",
        "MODEL_UNAVAILABLE": "The configured local model is unavailable.",
        "REQUEST_TIMEOUT": "The local model request timed out.",
        "GENERATION_ERROR": "The agent could not produce a valid investigation proposal.",
    }.get(str(getattr(category, "value", category)), "The investigation request could not be completed.")


def operation_working_label(operation: str) -> str:
    """Return the only transient investigator-facing label for an explicit request."""
    return "Preparing investigation approach" if operation == "start" else "Adjusting investigation plan"


def _initialize(st: object) -> None:
    for key, value in {"v05_view": "list", "v05_active_id": None, "v05_pending": None, "v05_error": None, "v05_new_objective": DEFAULT_OBJECTIVE, "v05_new_instruction": ""}.items():
        st.session_state.setdefault(key, value)


def _queue(st: object, operation: str, **payload: str) -> None:
    st.session_state.v05_pending = {"operation": operation, **payload}
    st.rerun()


def _perform_pending(st: object, service: InvestigatorReadyApprovalLoopService | None) -> None:
    pending = st.session_state.v05_pending
    if pending is None:
        return
    if service is None:
        st.session_state.v05_error, st.session_state.v05_pending = "Local model configuration is unavailable.", None
        return
    operation = pending["operation"]
    wording = operation_working_label(operation)
    try:
        with st.status(wording, expanded=True):
            st.write("The agent is working. No new action is authorized during processing.")
            if operation == "start":
                state = service.start_investigation(pending["association"], pending["objective"], pending.get("instruction") or None)
            elif operation == "modify":
                state = service.modify(pending["investigation_id"], pending["proposal_id"], pending["instruction"])
            elif operation == "decline":
                state = service.decline(pending["investigation_id"], pending["proposal_id"], pending.get("guidance") or None)
            elif operation == "retry":
                state = service.retry_decline_reconsideration(pending["investigation_id"], pending["proposal_id"])
            elif operation == "approve":
                state = service.approve(pending["investigation_id"], pending["proposal_id"])
            else:
                raise ValueError("unknown UI operation")
        st.session_state.v05_active_id, st.session_state.v05_view, st.session_state.v05_error = state.investigation.investigation_id, "detail", None
    except (InvestigatorReadyServiceError, ValueError, RuntimeError, OSError) as error:
        st.session_state.v05_error = _failure_message(error)
    finally:
        st.session_state.v05_pending = None
    st.rerun()


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
    st.title("New investigation")
    cases = catalog.available_cases()
    labels = {case.case_reference + (f" — {case.domain}" if case.domain else ""): case for case in cases}
    selected = labels[st.selectbox("Case", tuple(labels))]
    _, context = catalog.load_case(selected.association_id)
    _render_context(st, context)
    objective = st.text_area("Investigation objective", value=st.session_state.v05_new_objective, key="new-objective")
    instruction = st.text_area("Additional investigator instruction (optional)", value=st.session_state.v05_new_instruction, key="new-instruction")
    if st.button("Start investigation", type="primary", disabled=service is None):
        st.session_state.v05_new_objective, st.session_state.v05_new_instruction = objective, instruction
        _queue(st, "start", association=selected.association_id, objective=objective, instruction=instruction)
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


def _render_attention(st: object, store: SQLiteInvestigationStore, catalog: ConfiguredCaseCatalog, detail: InvestigationDetail, service: InvestigatorReadyApprovalLoopService | None) -> None:
    reason = detail.attention_reason
    if reason is AttentionReason.DECLINE_RECONSIDERATION_INCOMPLETE:
        st.error("THE AGENT COULD NOT COMPLETE THE PLAN ADJUSTMENT")
        declined = next((item for item in detail.decision_history if item.decision_type == "DECLINE" and detail.current_or_last_proposal and item.proposal_id == detail.current_or_last_proposal.proposal_id), None)
        st.write("Your instruction is saved." if declined and declined.instruction_or_reason else "The previous proposal was declined without additional guidance.")
        st.write("The previous proposal remains DECLINED. No new proposal was created and no action was authorized.")
        if detail.current_or_last_proposal and st.button("Try again", disabled=service is None):
            _queue(st, "retry", investigation_id=detail.investigation.investigation_id, proposal_id=detail.current_or_last_proposal.proposal_id)
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


def _render_detail(st: object, store: SQLiteInvestigationStore, catalog: ConfiguredCaseCatalog, projector: InvestigationReadProjector, service: InvestigatorReadyApprovalLoopService | None) -> None:
    detail = projector.detail(st.session_state.v05_active_id)
    st.title(detail.investigation.case_reference)
    st.write(f"**Investigation objective:** {detail.investigation.objective if detail.investigation.objective is not None else 'Not recorded'}")
    if detail.context is not None:
        _render_context(st, detail.context)
    if detail.lifecycle_state is PersistedLifecycleState.ATTENTION:
        _render_attention(st, store, catalog, detail, service)
        _render_history(st, detail)
        return
    if detail.current_direction:
        st.subheader("Current direction")
        st.markdown("**Working explanations — none is currently established as a finding.**")
        for item in detail.current_direction.competing_explanations:
            st.write(f"- {item}")
        st.markdown("**Provisional plan**")
        for item in detail.current_direction.plan_steps:
            st.write(f"- {item}")
    if detail.lifecycle_state is PersistedLifecycleState.NEEDS_REVIEW and detail.active_proposal:
        _render_proposal(st, detail.active_proposal)
        if st.button("Approve"):
            _queue(st, "approve", investigation_id=detail.investigation.investigation_id, proposal_id=detail.active_proposal.proposal_id)
        st.write("Keep the basic proposed action, but change it according to your instruction.")
        modification = st.text_area("Modification instruction", key="modify-instruction")
        if st.button("Modify"):
            if not modification.strip(): st.error("Modification instruction must be non-empty.")
            else: _queue(st, "modify", investigation_id=detail.investigation.investigation_id, proposal_id=detail.active_proposal.proposal_id, instruction=modification)
        guidance = st.text_area("Optional decline guidance", key="decline-guidance")
        st.write("The current proposal will be declined. The agent will reconsider the investigation plan using your instruction and return with a new proposed next action for your approval.")
        if st.button("Adjust investigation plan" if guidance.strip() else "Decline without guidance"):
            _queue(st, "decline", investigation_id=detail.investigation.investigation_id, proposal_id=detail.active_proposal.proposal_id, guidance=guidance)
    elif detail.lifecycle_state is PersistedLifecycleState.APPROVED and detail.current_or_last_proposal:
        st.success("ACTION APPROVED")
        st.write("This analytical action is authorized.\nAnalytical execution is not implemented in this version.")
        _render_proposal(st, detail.current_or_last_proposal, "Approved analytical action")
    _render_history(st, detail)


def main() -> None:
    import streamlit as st
    st.set_page_config(page_title="Fraud Investigation", layout="wide")
    _initialize(st)
    store, catalog, projector, service, configuration_error = _build_dependencies()
    try:
        _perform_pending(st, service)
        if st.session_state.v05_error: st.error(st.session_state.v05_error)
        if st.session_state.v05_view == "new": _render_new(st, catalog, service)
        elif st.session_state.v05_active_id: _render_detail(st, store, catalog, projector, service)
        else: _render_list(st, projector)
        if configuration_error:
            with st.expander("Local model details"): st.write(configuration_error)
    finally:
        store.close()


if __name__ == "__main__":
    main()
