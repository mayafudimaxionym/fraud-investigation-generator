import csv
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from generator.dev.package_case import export_development_investigation_package
from investigation.approval_loop import ApprovalLoopService
from investigation.models import AnalyticalActionProposal
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import ProposalAgentResult


class FakeProposalAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[object, str, str, datetime]] = []

    def propose(
        self,
        context: object,
        investigator_instruction: str,
        proposal_id: str,
        created_at: datetime,
    ) -> ProposalAgentResult:
        self.calls.append((context, investigator_instruction, proposal_id, created_at))
        if self.fail:
            raise RuntimeError("proposal generation failed")
        return ProposalAgentResult(
            "Review the available evidence before choosing the next step.",
            AnalyticalActionProposal(
                proposal_id,
                "Review visible events for relevant activity.",
                "Assess the reported concern.",
                "The available context identifies visible events as a next step.",
                "visible_events.csv and the investigation request",
                "A bounded summary for investigator review.",
                "PROPOSED",
                created_at,
            ),
        )


def _package(tmp_path: Path) -> Path:
    return export_development_investigation_package(tmp_path)


def _service(
    database_path: Path, proposal_agent: FakeProposalAgent
) -> tuple[SQLiteInvestigationStore, ApprovalLoopService]:
    store = SQLiteInvestigationStore(database_path)
    return store, ApprovalLoopService(store, proposal_agent)  # type: ignore[arg-type]


def _start(service: ApprovalLoopService, package: Path):
    return service.start_investigation(
        "development-case-42", package, "Investigate the reported concern."
    )


def test_initial_proposal_is_generated_persisted_and_reconstructed_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    store, service = _service(database_path, FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))
    investigation_id = result.state.investigation.investigation_id

    assert result.provisional_plan
    assert len(result.state.proposals) == 1
    assert result.state.proposals[0].status == "PROPOSED"
    assert result.state.decisions == ()
    store.close()

    with SQLiteInvestigationStore(database_path) as restarted:
        state = ApprovalLoopService(restarted, FakeProposalAgent()).get_state(investigation_id)

    assert state == result.state


def test_initial_proposal_agent_failure_leaves_no_persisted_investigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifiers = iter(("investigation-001", "proposal-001"))
    monkeypatch.setattr(
        "investigation.approval_loop._new_identifier", lambda _prefix: next(identifiers)
    )
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent(fail=True))

    with pytest.raises(RuntimeError, match="proposal generation failed"):
        _start(service, _package(tmp_path / "package"))

    with pytest.raises(ValueError, match="investigation does not exist"):
        store.get_investigation("investigation-001")


def test_approve_persists_decision_and_never_executes_action(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))
    proposal = result.state.proposals[0]

    state = service.approve(result.state.investigation.investigation_id, proposal.proposal_id)

    assert state.proposals[0].status == "APPROVED"
    assert state.decisions[0].decision_type == "APPROVE"
    assert state.decisions[0].instruction_or_reason is None
    assert not hasattr(service, "execute")
    assert not hasattr(service, "query")
    store.close()


def test_cross_investigation_proposal_operations_fail_without_mutation(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    first = _start(service, _package(tmp_path / "first-package"))
    second = _start(service, _package(tmp_path / "second-package"))
    first_id = first.state.investigation.investigation_id
    second_id = second.state.investigation.investigation_id
    second_proposal_id = second.state.proposals[0].proposal_id

    with pytest.raises(ValueError, match="proposal does not belong to investigation"):
        service.approve(first_id, second_proposal_id)

    assert service.get_state(first_id) == first.state
    assert service.get_state(second_id) == second.state
    store.close()


@pytest.mark.parametrize("reason", (None, "Use a different evidence source first."))
def test_decline_persists_optional_reason(tmp_path: Path, reason: str | None) -> None:
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))

    state = service.decline(
        result.state.investigation.investigation_id,
        result.state.proposals[0].proposal_id,
        reason,
    )

    assert state.proposals[0].status == "DECLINED"
    assert state.decisions[0].decision_type == "DECLINE"
    assert state.decisions[0].instruction_or_reason == reason
    store.close()


@pytest.mark.parametrize("reason", ("", "   "))
def test_decline_rejects_blank_reason_without_persisting_decision(
    tmp_path: Path, reason: str
) -> None:
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))

    with pytest.raises(ValueError, match="instruction_or_reason"):
        service.decline(
            result.state.investigation.investigation_id,
            result.state.proposals[0].proposal_id,
            reason,
        )

    assert service.get_state(result.state.investigation.investigation_id) == result.state
    store.close()


@pytest.mark.parametrize("instruction", ("", "   "))
def test_modify_rejects_blank_instruction_before_generation_or_persistence(
    tmp_path: Path, instruction: str
) -> None:
    agent = FakeProposalAgent()
    store, service = _service(tmp_path / "investigations.sqlite", agent)
    result = _start(service, _package(tmp_path / "package"))

    with pytest.raises(ValueError, match="instruction_or_reason"):
        service.modify(
            result.state.investigation.investigation_id,
            result.state.proposals[0].proposal_id,
            _package(tmp_path / "revision-package"),
            instruction,
        )

    assert len(agent.calls) == 1
    assert store.list_decisions(result.state.investigation.investigation_id) == ()
    assert store.list_proposals(result.state.investigation.investigation_id)[0].status == "PROPOSED"
    store.close()


def test_modify_generates_explicit_revision_and_persists_atomic_lifecycle(tmp_path: Path) -> None:
    agent = FakeProposalAgent()
    store, service = _service(tmp_path / "investigations.sqlite", agent)
    result = _start(service, _package(tmp_path / "package"))
    original = result.state.proposals[0]
    modification = "Focus the revision on visible login and transfer activity."

    revised_result = service.modify(
        result.state.investigation.investigation_id,
        original.proposal_id,
        _package(tmp_path / "revision-package"),
        modification,
    )

    revision_instruction = agent.calls[-1][1]
    for value in (
        original.action,
        original.purpose,
        original.why_now,
        original.data_to_be_used,
        original.expected_output,
        modification,
    ):
        assert value in revision_instruction
    proposals = {proposal.proposal_id: proposal for proposal in revised_result.state.proposals}
    assert proposals[original.proposal_id].status == "MODIFIED"
    revised = next(proposal for proposal in proposals.values() if proposal != proposals[original.proposal_id])
    assert revised.status == "PROPOSED"
    assert revised.revised_from_proposal_id == original.proposal_id
    assert revised_result.state.decisions[0].decision_type == "MODIFY"
    assert revised_result.state.decisions[0].instruction_or_reason == modification
    store.close()


def test_modify_agent_failure_preserves_original_and_writes_no_decision(tmp_path: Path) -> None:
    agent = FakeProposalAgent()
    store, service = _service(tmp_path / "investigations.sqlite", agent)
    result = _start(service, _package(tmp_path / "package"))
    agent.fail = True

    with pytest.raises(RuntimeError, match="proposal generation failed"):
        service.modify(
            result.state.investigation.investigation_id,
            result.state.proposals[0].proposal_id,
            _package(tmp_path / "revision-package"),
            "Focus on visible events.",
        )

    assert store.list_proposals(result.state.investigation.investigation_id) == result.state.proposals
    assert store.list_decisions(result.state.investigation.investigation_id) == ()
    store.close()


def test_modify_persistence_failure_uses_existing_atomic_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifiers = iter((
        "investigation-001", "proposal-original", "decision-modify", "proposal-duplicate",
    ))
    monkeypatch.setattr(
        "investigation.approval_loop._new_identifier", lambda _prefix: next(identifiers)
    )
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))
    duplicate = replace(result.state.proposals[0], proposal_id="proposal-duplicate")
    store.add_proposal(result.state.investigation.investigation_id, duplicate)

    with pytest.raises(ValueError, match="integrity"):
        service.modify(
            result.state.investigation.investigation_id,
            result.state.proposals[0].proposal_id,
            _package(tmp_path / "revision-package"),
            "Focus on visible events.",
        )

    proposals = store.list_proposals(result.state.investigation.investigation_id)
    assert all(proposal.status == "PROPOSED" for proposal in proposals)
    assert store.list_decisions(result.state.investigation.investigation_id) == ()
    store.close()


def test_invalid_or_stale_lifecycle_operations_fail_safely(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "investigations.sqlite", FakeProposalAgent())
    result = _start(service, _package(tmp_path / "package"))
    investigation_id = result.state.investigation.investigation_id
    proposal_id = result.state.proposals[0].proposal_id
    service.approve(investigation_id, proposal_id)

    with pytest.raises(ValueError, match="only a PROPOSED proposal"):
        service.decline(investigation_id, proposal_id)
    with pytest.raises(ValueError, match="does not belong"):
        service.approve(investigation_id, "proposal-missing")
    store.close()


def test_service_preserves_governed_context_boundary(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    row_marker = "UNIQUE-APPROVAL-LOOP-ROW-MARKER"
    evaluator_marker = "UNIQUE-APPROVAL-LOOP-EVALUATOR-MARKER"
    with (package / "investigator/data/visible_entities.csv").open(
        "a", encoding="utf-8", newline=""
    ) as csv_file:
        csv.writer(csv_file).writerow((row_marker, "account"))
    (package / "evaluator_only/marker.txt").write_text(evaluator_marker, encoding="utf-8")
    agent = FakeProposalAgent()
    store, service = _service(tmp_path / "investigations.sqlite", agent)

    _start(service, package)

    context = agent.calls[0][0]
    assert row_marker not in repr(context)
    assert evaluator_marker not in repr(context)
    assert "evaluator_only" not in repr(context)
    assert not hasattr(service, "execute")
    assert not hasattr(service, "query")
    store.close()
