"""Minimal local Streamlit interface for the V0 approval loop."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from generator.artifacts.ollama import OllamaConfig
from investigation.approval_loop import ApprovalLoopService, ApprovalLoopState
from investigation.models import AnalyticalActionProposal
from investigation.package_access import InvestigatorPackageContext, load_investigator_package
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import LocalProposalAgent, OllamaProposalClient


DATABASE_PATH = Path("investigations.sqlite")
DEVELOPMENT_PACKAGE_DIRECTORY = Path("output") / "development-case-42"


def select_active_proposal(
    proposals: Sequence[AnalyticalActionProposal],
) -> AnalyticalActionProposal | None:
    """Return the one proposal that may receive a V0 human decision."""
    proposed = tuple(proposal for proposal in proposals if proposal.status == "PROPOSED")
    if len(proposed) > 1:
        raise ValueError(
            "persisted workflow state contains multiple PROPOSED proposals; "
            "the exactly-one-next-action invariant is violated"
        )
    return proposed[0] if proposed else None


def optional_decline_reason(value: str) -> str | None:
    """Convert a blank optional decline field into the domain representation."""
    return value if value.strip() else None


def _build_service() -> ApprovalLoopService:
    store = SQLiteInvestigationStore(DATABASE_PATH)
    client = OllamaProposalClient(OllamaConfig.from_environment())
    return ApprovalLoopService(store, LocalProposalAgent(client))


def _render_context(st: object, context: InvestigatorPackageContext) -> None:
    """Render only Task 3-governed investigator context."""
    st.subheader("Investigation context")
    st.markdown("**Investigation request**")
    st.write(context.investigation_request)
    with st.expander("Customer/support statement"):
        st.write(context.customer_support_statement)
    with st.expander("Prior analyst note"):
        st.write(context.prior_analyst_note)
    st.markdown("**Available structured datasets**")
    for dataset in context.datasets:
        st.write(
            f"{dataset.dataset_name}: {dataset.row_count} rows; "
            f"fields: {', '.join(dataset.field_names)}"
        )


def _render_proposal(st: object, proposal: AnalyticalActionProposal) -> None:
    """Render the five approved proposal fields without execution controls."""
    st.subheader("Proposed next analytical action")
    st.write(f"**Status:** {proposal.status}")
    st.write(f"**Action:** {proposal.action}")
    st.write(f"**Purpose:** {proposal.purpose}")
    st.write(f"**Why now:** {proposal.why_now}")
    st.write(f"**Data to be used:** {proposal.data_to_be_used}")
    st.write(f"**Expected output:** {proposal.expected_output}")


def _render_history(st: object, state: ApprovalLoopState) -> None:
    """Render the persisted compact V0 proposal and decision trail."""
    st.subheader("Decision history")
    for proposal in state.proposals:
        lineage = (
            f"; revision of {proposal.revised_from_proposal_id}"
            if proposal.revised_from_proposal_id
            else ""
        )
        st.write(
            f"Proposal {proposal.proposal_id}: {proposal.status}; "
            f"created {proposal.created_at.isoformat()}{lineage}"
        )
    for decision in state.decisions:
        detail = (
            f"; instruction/reason: {decision.instruction_or_reason}"
            if decision.instruction_or_reason is not None
            else ""
        )
        st.write(
            f"Decision {decision.decision_type} for proposal {decision.proposal_id}; "
            f"decided {decision.decided_at.isoformat()}{detail}"
        )


def main() -> None:
    """Run the deliberately small local V0 Streamlit screen."""
    import streamlit as st

    st.set_page_config(page_title="V0 Fraud Investigation", layout="wide")
    st.title("V0 Fraud Investigation Approval Loop")

    @st.cache_resource
    def service() -> ApprovalLoopService:
        return _build_service()

    approval_service = service()
    defaults = {
        "active_investigation_id": None,
        "active_package_directory": "",
        "latest_provisional_plan": None,
        "approved_not_executed": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    st.subheader("Start or load investigation")
    case_reference = st.text_input("Case reference", value="development-case-42")
    package_directory = st.text_input(
        "Investigator package directory", value=str(DEVELOPMENT_PACKAGE_DIRECTORY)
    )
    investigator_instruction = st.text_area("Investigator instruction")
    if st.button("Start investigation"):
        try:
            result = approval_service.start_investigation(
                case_reference, Path(package_directory), investigator_instruction
            )
            st.session_state.active_investigation_id = result.state.investigation.investigation_id
            st.session_state.active_package_directory = package_directory
            st.session_state.latest_provisional_plan = result.provisional_plan
            st.session_state.approved_not_executed = False
            st.success("Investigation started.")
        except (ValueError, RuntimeError, OSError) as error:
            st.error(str(error))

    existing_investigation_id = st.text_input("Existing investigation ID")
    existing_package_directory = st.text_input("Package directory for existing investigation")
    if st.button("Load investigation"):
        try:
            approval_service.get_state(existing_investigation_id)
            load_investigator_package(Path(existing_package_directory))
            st.session_state.active_investigation_id = existing_investigation_id
            st.session_state.active_package_directory = existing_package_directory
            st.session_state.latest_provisional_plan = None
            st.session_state.approved_not_executed = False
            st.success("Persisted investigation loaded. Provisional plan is unavailable after restart.")
        except (ValueError, RuntimeError, OSError) as error:
            st.error(str(error))

    investigation_id = st.session_state.active_investigation_id
    active_package_directory = st.session_state.active_package_directory
    if not investigation_id or not active_package_directory:
        return

    try:
        state = approval_service.get_state(investigation_id)
        context = load_investigator_package(Path(active_package_directory))
    except (ValueError, RuntimeError, OSError) as error:
        st.error(str(error))
        return

    st.write(
        f"**Active investigation:** {state.investigation.investigation_id} "
        f"(case: {state.investigation.case_reference})"
    )
    _render_context(st, context)

    if st.session_state.latest_provisional_plan:
        st.subheader("Provisional investigation plan")
        st.info(st.session_state.latest_provisional_plan)

    try:
        active_proposal = select_active_proposal(state.proposals)
    except ValueError as error:
        st.error(str(error))
        _render_history(st, state)
        return
    if active_proposal is not None:
        _render_proposal(st, active_proposal)
        if st.button("Approve"):
            try:
                approval_service.approve(investigation_id, active_proposal.proposal_id)
                st.session_state.approved_not_executed = True
                st.rerun()
            except (ValueError, RuntimeError, OSError) as error:
                st.error(str(error))

        decline_reason = st.text_input("Optional decline reason or instruction")
        if st.button("Decline"):
            try:
                approval_service.decline(
                    investigation_id,
                    active_proposal.proposal_id,
                    optional_decline_reason(decline_reason),
                )
                st.rerun()
            except (ValueError, RuntimeError, OSError) as error:
                st.error(str(error))

        modification_instruction = st.text_area("Modification instruction")
        if st.button("Modify"):
            if not modification_instruction.strip():
                st.error("Modification instruction must be non-empty.")
            else:
                try:
                    result = approval_service.modify(
                        investigation_id,
                        active_proposal.proposal_id,
                        Path(active_package_directory),
                        modification_instruction,
                    )
                    st.session_state.latest_provisional_plan = result.provisional_plan
                    st.session_state.approved_not_executed = False
                    st.rerun()
                except (ValueError, RuntimeError, OSError) as error:
                    st.error(str(error))
    elif st.session_state.approved_not_executed:
        st.success("Approved — analytical execution is not implemented in V0.")

    _render_history(st, state)


if __name__ == "__main__":
    main()
