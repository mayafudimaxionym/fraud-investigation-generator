"""Focused V0.5 orchestration tests; all proposal-model behavior is faked."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from generator.dev.package_case import export_development_investigation_package
from investigation.approval_loop import (
    InvestigatorReadyApprovalLoopService,
    InvestigatorReadyServiceError,
)
from investigation.case_catalog import ConfiguredCaseCatalog, ConfiguredCasePackage
from investigation.models import AnalyticalActionProposal, InvestigationRecord
from investigation.persistence import SQLiteInvestigationStore
from investigation.proposal_agent import (
    CandidateDirectionContent,
    ProposalAgentResult,
    ProposalGenerationRequest,
    ProposalModelError,
    ProposalModelFailureCategory,
)


BASE_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


class FakePreflight:
    def __init__(self) -> None:
        self.calls = 0
        self.failure: ProposalModelError | None = None

    def preflight(self) -> None:
        self.calls += 1
        if self.failure is not None:
            raise self.failure


class FakeDirectionAgent:
    def __init__(self) -> None:
        self.requests: list[ProposalGenerationRequest] = []
        self.failure: ProposalModelError | None = None
        self.direction = CandidateDirectionContent(
            ("The activity may be coordinated.", "The activity may be legitimate."),
            ("Review visible event timing.", "Compare visible relationship evidence."),
        )

    def generate(self, request: ProposalGenerationRequest) -> ProposalAgentResult:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return ProposalAgentResult(
            "\n".join(self.direction.plan_steps),
            AnalyticalActionProposal(
                request.proposal_id,
                "Review visible_events.csv for the relevant activity.",
                "Distinguish plausible explanations.",
                "The governed context identifies event timing as the next step.",
                "visible_events.csv and the investigation request",
                "A bounded investigator-readable event summary.",
                "PROPOSED",
                request.created_at,
            ),
            self.direction,
        )


def _catalog(package: Path) -> ConfiguredCaseCatalog:
    return ConfiguredCaseCatalog(
        (ConfiguredCasePackage("case-42", "development-case-42", package, "payments"),)
    )


def _service(
    tmp_path: Path,
) -> tuple[SQLiteInvestigationStore, InvestigatorReadyApprovalLoopService, FakeDirectionAgent, FakePreflight]:
    store = SQLiteInvestigationStore(tmp_path / "investigations.sqlite")
    agent = FakeDirectionAgent()
    preflight = FakePreflight()
    catalog = _catalog(export_development_investigation_package(tmp_path / "package"))
    return store, InvestigatorReadyApprovalLoopService(store, catalog, agent, preflight), agent, preflight  # type: ignore[arg-type]


def _start(service: InvestigatorReadyApprovalLoopService, objective: str = "Investigate."):
    return service.start_investigation("case-42", objective, "Review the reported concern.")


def _initial_proposal(state):
    return next(proposal for proposal in state.proposals if proposal.status == "PROPOSED")


def test_initial_flow_preflights_once_and_atomically_persists_direction_and_proposal(
    tmp_path: Path,
) -> None:
    store, service, agent, preflight = _service(tmp_path)
    state = _start(service, "")

    assert preflight.calls == 1
    assert len(agent.requests) == 1
    assert agent.requests[0].objective == ""
    assert state.investigation.case_reference == "development-case-42"
    assert state.investigation.package_association == "case-42"
    assert state.investigation.objective == ""
    assert state.current_direction is not None
    assert state.current_direction.version == 1
    assert state.current_direction.provenance == "INITIAL"
    assert state.current_direction.trigger_reference_id is None
    assert len(state.proposals) == 1 and state.proposals[0].status == "PROPOSED"
    assert state.decisions == ()
    store.close()


def test_initial_context_or_model_failure_creates_no_investigation(tmp_path: Path) -> None:
    store, service, agent, preflight = _service(tmp_path)
    with pytest.raises(InvestigatorReadyServiceError) as unknown:
        service.start_investigation("unknown", "objective")
    assert unknown.value.category == "SAFE_CONTEXT_UNAVAILABLE"
    assert preflight.calls == 0 and agent.requests == [] and store.list_investigations() == ()

    preflight.failure = ProposalModelError(
        ProposalModelFailureCategory.MODEL_UNAVAILABLE, "missing model"
    )
    with pytest.raises(InvestigatorReadyServiceError) as unavailable:
        _start(service)
    assert unavailable.value.category is ProposalModelFailureCategory.MODEL_UNAVAILABLE
    assert store.list_investigations() == ()
    store.close()


def test_initial_persistence_failure_leaves_no_partial_investigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, _, _ = _service(tmp_path)
    existing = InvestigationRecord("existing", "development-case-42", BASE_TIME, BASE_TIME, "", "case-42")
    store.add_investigation(existing)
    store.add_proposal(
        existing.investigation_id,
        AnalyticalActionProposal("duplicate", "Review events.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME),
    )
    identifiers = iter(("new-investigation", "duplicate", "new-direction"))
    monkeypatch.setattr("investigation.approval_loop._new_identifier", lambda _prefix: next(identifiers))
    with pytest.raises(InvestigatorReadyServiceError) as failed:
        _start(service)
    assert failed.value.category == "PERSISTENCE_ERROR"
    with pytest.raises(ValueError, match="does not exist"):
        store.get_investigation("new-investigation")
    assert store.get_current_direction("new-investigation") is None
    store.close()


def test_modify_uses_revision_lineage_and_creates_direction_only_when_changed(tmp_path: Path) -> None:
    store, service, agent, _ = _service(tmp_path)
    original_state = _start(service)
    original = _initial_proposal(original_state)

    unchanged = service.modify(original_state.investigation.investigation_id, original.proposal_id, "Focus on event timing.")
    assert len(unchanged.directions) == 1
    assert unchanged.proposals[0].status == "MODIFIED"
    revised = _initial_proposal(unchanged)
    assert revised.revised_from_proposal_id == original.proposal_id
    assert unchanged.decisions[0].decision_type == "MODIFY"
    assert agent.requests[-1].mode == "MODIFY"

    agent.direction = CandidateDirectionContent(
        ("The activity may be coordinated.", "A network explanation remains plausible."),
        unchanged.current_direction.plan_steps,  # type: ignore[union-attr]
    )
    changed = service.modify(unchanged.investigation.investigation_id, revised.proposal_id, "Add the network explanation.")
    assert changed.current_direction is not None
    assert changed.current_direction.version == 2
    assert changed.current_direction.provenance == "MODIFY"
    assert changed.current_direction.trigger_reference_id == changed.decisions[-1].decision_id
    store.close()


@pytest.mark.parametrize("failure_owner", ("preflight", "agent"))
def test_modify_failure_leaves_original_proposed_without_decision(
    tmp_path: Path, failure_owner: str
) -> None:
    store, service, agent, preflight = _service(tmp_path)
    state = _start(service)
    original = _initial_proposal(state)
    error = ProposalModelError(ProposalModelFailureCategory.REQUEST_TIMEOUT, "timed out")
    if failure_owner == "preflight":
        preflight.failure = error
    else:
        agent.failure = error

    with pytest.raises(InvestigatorReadyServiceError) as raised:
        service.modify(state.investigation.investigation_id, original.proposal_id, "Focus on events.")
    assert raised.value.category is ProposalModelFailureCategory.REQUEST_TIMEOUT
    after = service.get_state(state.investigation.investigation_id)
    assert after.proposals == state.proposals and after.decisions == () and len(after.directions) == 1
    store.close()


def test_modify_persistence_failure_rolls_back_decision_direction_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, agent, _ = _service(tmp_path)
    state = _start(service)
    original = _initial_proposal(state)
    duplicate = AnalyticalActionProposal(
        "duplicate", "Other action.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME
    )
    other = InvestigationRecord("other", "development-case-42", BASE_TIME, BASE_TIME, "", "case-42")
    store.add_investigation(other)
    store.add_proposal(other.investigation_id, duplicate)
    agent.direction = CandidateDirectionContent(("A changed explanation.",), state.current_direction.plan_steps)  # type: ignore[union-attr]
    identifiers = iter(("modify-decision", "duplicate", "direction-002"))
    monkeypatch.setattr("investigation.approval_loop._new_identifier", lambda _prefix: next(identifiers))
    with pytest.raises(InvestigatorReadyServiceError) as failed:
        service.modify(state.investigation.investigation_id, original.proposal_id, "Focus it.")
    assert failed.value.category == "PERSISTENCE_ERROR"
    after = service.get_state(state.investigation.investigation_id)
    assert len(after.directions) == 1 and after.decisions == ()
    assert all(proposal.status == "PROPOSED" for proposal in after.proposals)
    store.close()


def test_decline_commits_before_failed_reconsideration_and_retry_does_not_duplicate_decision(
    tmp_path: Path,
) -> None:
    store, service, agent, preflight = _service(tmp_path)
    state = _start(service)
    original = _initial_proposal(state)
    preflight.failure = ProposalModelError(
        ProposalModelFailureCategory.SERVICE_UNAVAILABLE, "service unavailable"
    )

    with pytest.raises(InvestigatorReadyServiceError) as failed:
        service.decline(state.investigation.investigation_id, original.proposal_id, "Review relationships instead.")
    assert failed.value.decline_committed is True
    assert failed.value.category is ProposalModelFailureCategory.SERVICE_UNAVAILABLE
    committed = service.get_state(state.investigation.investigation_id)
    assert committed.proposals[0].status == "DECLINED"
    assert committed.decisions[0].instruction_or_reason == "Review relationships instead."
    assert len(agent.requests) == 1

    preflight.failure = None
    retried = service.retry_decline_reconsideration(
        state.investigation.investigation_id, original.proposal_id
    )
    assert len(retried.decisions) == 1
    replacement = _initial_proposal(retried)
    assert replacement.revised_from_proposal_id is None
    assert len(agent.requests) == 2
    result = store.get_decline_reconsideration_result(retried.decisions[0].decision_id)
    assert result is not None and result.replacement_proposal_id == replacement.proposal_id
    with pytest.raises(ValueError, match="persisted replacement"):
        service.retry_decline_reconsideration(state.investigation.investigation_id, original.proposal_id)
    store.close()


def test_unrelated_active_proposal_is_not_mistaken_for_a_decline_replacement(
    tmp_path: Path,
) -> None:
    store, service, _, preflight = _service(tmp_path)
    state = _start(service)
    declined = _initial_proposal(state)
    preflight.failure = ProposalModelError(ProposalModelFailureCategory.SERVICE_UNAVAILABLE, "offline")
    with pytest.raises(InvestigatorReadyServiceError):
        service.decline(state.investigation.investigation_id, declined.proposal_id)
    unrelated = AnalyticalActionProposal(
        "unrelated-proposal", "Other review.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME
    )
    store.add_proposal(state.investigation.investigation_id, unrelated)
    decision = store.list_decisions(state.investigation.investigation_id)[0]
    assert store.get_decline_reconsideration_result(decision.decision_id) is None
    preflight.failure = None
    with pytest.raises(ValueError, match="another active PROPOSED"):
        service.retry_decline_reconsideration(state.investigation.investigation_id, declined.proposal_id)
    assert store.get_decline_reconsideration_result(decision.decision_id) is None
    store.close()


def test_decline_without_guidance_creates_independent_replacement_and_redirect_direction(
    tmp_path: Path,
) -> None:
    store, service, agent, _ = _service(tmp_path)
    state = _start(service)
    original = _initial_proposal(state)
    agent.direction = CandidateDirectionContent(
        ("Legitimate shared access remains possible.",),
        ("Review relationship evidence before event timing.",),
    )
    redirected = service.decline(state.investigation.investigation_id, original.proposal_id)
    replacement = _initial_proposal(redirected)
    assert replacement.revised_from_proposal_id is None
    assert redirected.decisions[0].instruction_or_reason is None
    assert redirected.current_direction is not None
    assert redirected.current_direction.provenance == "DECLINE_REDIRECT"
    assert redirected.current_direction.trigger_reference_id == redirected.decisions[0].decision_id
    assert agent.requests[-1].mode == "DECLINE_REDIRECT"
    assert agent.requests[-1].decline_guidance is None
    store.close()


def test_reconsideration_association_failure_rolls_back_direction_and_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, agent, preflight = _service(tmp_path)
    state = _start(service)
    declined = _initial_proposal(state)
    preflight.failure = ProposalModelError(ProposalModelFailureCategory.SERVICE_UNAVAILABLE, "offline")
    with pytest.raises(InvestigatorReadyServiceError):
        service.decline(state.investigation.investigation_id, declined.proposal_id)
    preflight.failure = None
    agent.direction = CandidateDirectionContent(("A changed explanation.",), ("A changed plan.",))

    def fail_result(*_args: object) -> None:
        raise sqlite3.IntegrityError("forced result insertion failure")

    monkeypatch.setattr(store, "_insert_decline_reconsideration_result", fail_result)
    with pytest.raises(InvestigatorReadyServiceError) as failed:
        service.retry_decline_reconsideration(state.investigation.investigation_id, declined.proposal_id)
    assert failed.value.category == "PERSISTENCE_ERROR" and failed.value.decline_committed
    after = service.get_state(state.investigation.investigation_id)
    decision = after.decisions[0]
    assert len(after.directions) == 1
    assert [proposal.status for proposal in after.proposals] == ["DECLINED"]
    assert store.get_decline_reconsideration_result(decision.decision_id) is None
    store.close()


def test_approve_persists_only_the_decision_and_never_generates_or_changes_direction(
    tmp_path: Path,
) -> None:
    store, service, agent, preflight = _service(tmp_path)
    state = _start(service)
    approved = service.approve(state.investigation.investigation_id, _initial_proposal(state).proposal_id)
    assert approved.proposals[0].status == "APPROVED"
    assert approved.decisions[0].decision_type == "APPROVE"
    assert approved.directions == state.directions
    assert len(agent.requests) == 1 and preflight.calls == 1
    assert not hasattr(service, "execute")
    store.close()


def test_legacy_missing_association_or_objective_is_recoverable_without_guessing(tmp_path: Path) -> None:
    store, service, _, _ = _service(tmp_path)
    legacy = InvestigationRecord("legacy", "development-case-42", BASE_TIME, BASE_TIME, None, None)
    store.add_investigation(legacy)
    proposal = AnalyticalActionProposal(
        "legacy-proposal", "Review events.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME
    )
    store.add_proposal(legacy.investigation_id, proposal)
    with pytest.raises(InvestigatorReadyServiceError) as error:
        service.modify(legacy.investigation_id, proposal.proposal_id, "Focus it.")
    assert error.value.category == "PACKAGE_ASSOCIATION_UNAVAILABLE"
    assert store.list_decisions(legacy.investigation_id) == ()

    no_objective = InvestigationRecord("legacy-objective", "development-case-42", BASE_TIME, BASE_TIME, None, "case-42")
    store.add_investigation(no_objective)
    objective_proposal = AnalyticalActionProposal(
        "legacy-objective-proposal", "Review events.", "Assess.", "Now.", "visible_events.csv", "Summary.", "PROPOSED", BASE_TIME
    )
    store.add_proposal(no_objective.investigation_id, objective_proposal)
    with pytest.raises(InvestigatorReadyServiceError) as objective_error:
        service.modify(no_objective.investigation_id, objective_proposal.proposal_id, "Focus it.")
    assert objective_error.value.category == "OBJECTIVE_UNAVAILABLE"
    store.close()


def test_reconstruction_survives_store_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    store = SQLiteInvestigationStore(database_path)
    package = export_development_investigation_package(tmp_path / "package")
    agent, preflight = FakeDirectionAgent(), FakePreflight()
    service = InvestigatorReadyApprovalLoopService(store, _catalog(package), agent, preflight)  # type: ignore[arg-type]
    started = _start(service)
    investigation_id = started.investigation.investigation_id
    store.close()
    with SQLiteInvestigationStore(database_path) as reopened:
        recovered = InvestigatorReadyApprovalLoopService(reopened, _catalog(package), agent, preflight).get_state(investigation_id)  # type: ignore[arg-type]
    assert recovered == started


def test_decline_retry_after_reopen_uses_persisted_decision_and_records_result(tmp_path: Path) -> None:
    database_path = tmp_path / "investigations.sqlite"
    package = export_development_investigation_package(tmp_path / "package")
    store = SQLiteInvestigationStore(database_path)
    agent, preflight = FakeDirectionAgent(), FakePreflight()
    service = InvestigatorReadyApprovalLoopService(store, _catalog(package), agent, preflight)  # type: ignore[arg-type]
    started = _start(service)
    declined = _initial_proposal(started)
    preflight.failure = ProposalModelError(ProposalModelFailureCategory.REQUEST_TIMEOUT, "slow")
    with pytest.raises(InvestigatorReadyServiceError):
        service.decline(started.investigation.investigation_id, declined.proposal_id, "Try another approach.")
    store.close()

    preflight.failure = None
    with SQLiteInvestigationStore(database_path) as reopened:
        retry_service = InvestigatorReadyApprovalLoopService(reopened, _catalog(package), agent, preflight)  # type: ignore[arg-type]
        retried = retry_service.retry_decline_reconsideration(started.investigation.investigation_id, declined.proposal_id)
        decision = retried.decisions[0]
        result = reopened.get_decline_reconsideration_result(decision.decision_id)
        assert len(retried.decisions) == 1
        assert result is not None
        assert result.replacement_proposal_id == _initial_proposal(retried).proposal_id
        with pytest.raises(ValueError, match="persisted replacement"):
            retry_service.retry_decline_reconsideration(started.investigation.investigation_id, declined.proposal_id)
