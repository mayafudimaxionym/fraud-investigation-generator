"""Sweep execution: chained scenarios, repeated at the approved counts.

What this is not, restated because it matters more than what it is (section 4):
this is not a second generation call, not a semantic-adjudication boundary, and not
a repair or retry path. Each observation issues exactly one model request through the
product's own transport and accepts whatever comes back. There is no retry, no
repair, no fallback model and no second pass. A failed run is recorded as a failed
run.

Chaining. One chained execution of a scenario (INITIAL -> MODIFY -> DECLINE_REDIRECT)
yields one observation of each semantic scenario, so repeating the chain
`structural_runs_per_scenario` times satisfies section 2.1 for all three scenarios.
Non-initial steps run against the **real generated prior state** of the step before
them. When a step's predecessor produced nothing usable there is no real prior state,
and the downstream observations are recorded as not attempted rather than being run
against fabricated state or quietly omitted. The roll-up then reports the shortfall
against the required counts, so an under-observed scenario is visible instead of
looking like a complete result.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from investigation.models import AnalyticalActionProposal, InvestigationDirection
from investigation.package_access import InvestigatorPackageContext
from investigation.proposal_agent import (
    ProposalGenerationRequest,
    ProposalModelClient,
    ProposalModelError,
    ProposalModelResponse,
    build_proposal_prompt,
)

from validation.qualification.configurations import (
    CandidateConfiguration,
    ModelEnvironment,
    capture_model_environment,
)
from validation.qualification.contract import evaluate_structural_contract
from validation.qualification.counts import APPROVED_COUNTS, ObservationCounts
from validation.qualification.isolation import assert_no_evaluator_material, load_governed_context
from validation.qualification.records import (
    NotAttemptedReason,
    PresentedPlan,
    RawCapture,
    RunRecord,
    sha256_text,
)
from validation.qualification.scenarios import ScenarioDefinition, ScenarioStep


ClientFactory = Callable[[CandidateConfiguration], ProposalModelClient]
EnvironmentProbe = Callable[[CandidateConfiguration], ModelEnvironment]
ContextLoader = Callable[[ScenarioDefinition], InvestigatorPackageContext]


class RecordSink:
    """Where run records are written. Raw capture is written before parsing."""

    def capture_raw(self, run_id: str, capture: RawCapture) -> None:
        """Persist the verbatim capture immediately, before the contract is applied."""

    def record_run(self, record: RunRecord) -> None:
        """Persist the complete run record."""


class CollectingSink(RecordSink):
    """In-memory sink. Used by tests and as the default when no durable sink is given."""

    def __init__(self) -> None:
        self.raw_captures: list[tuple[str, RawCapture]] = []
        self.records: list[RunRecord] = []

    def capture_raw(self, run_id: str, capture: RawCapture) -> None:
        self.raw_captures.append((run_id, capture))

    def record_run(self, record: RunRecord) -> None:
        self.records.append(record)


@dataclass(frozen=True)
class _PriorState:
    """Real generated prior state carried from one chain step to the next."""

    direction: InvestigationDirection
    proposal: AnalyticalActionProposal
    version: int


def default_client_factory(configuration: CandidateConfiguration) -> ProposalModelClient:
    """Use the product's own transport. Imported lazily so tests never need Ollama."""
    from investigation.proposal_agent import OllamaProposalClient

    return OllamaProposalClient(configuration.ollama)


def run_sweep(
    scenarios: Sequence[ScenarioDefinition],
    configurations: Sequence[CandidateConfiguration],
    *,
    counts: ObservationCounts = APPROVED_COUNTS,
    client_factory: ClientFactory = default_client_factory,
    environment_probe: EnvironmentProbe | None = None,
    context_loader: ContextLoader | None = None,
    sink: RecordSink | None = None,
    experiment_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[RunRecord, ...]:
    """Run every scenario against every candidate configuration at the approved counts."""
    if not scenarios:
        raise ValueError("a sweep requires at least one scenario")
    if not configurations:
        raise ValueError("a sweep requires at least one candidate configuration")
    labels = [configuration.label for configuration in configurations]
    if len(set(labels)) != len(labels):
        raise ValueError("candidate configuration labels must be unique within a sweep")

    probe = environment_probe or (lambda config: capture_model_environment(config.ollama))
    loader = context_loader or (lambda scenario: load_governed_context(scenario.package_directory))
    collector = sink if sink is not None else CollectingSink()
    now = clock or (lambda: datetime.now(timezone.utc))
    resolved_experiment_id = experiment_id or f"experiment-{uuid.uuid4()}"

    records: list[RunRecord] = []
    for configuration in configurations:
        environment = probe(configuration).as_record()
        client = client_factory(configuration)
        for scenario in scenarios:
            context = loader(scenario)
            for repetition in range(1, counts.chain_repetitions + 1):
                records.extend(_run_chain(
                    scenario=scenario,
                    context=context,
                    configuration=configuration,
                    environment=environment,
                    client=client,
                    counts=counts,
                    repetition=repetition,
                    experiment_id=resolved_experiment_id,
                    sink=collector,
                    now=now,
                ))
    return tuple(records)


def _run_chain(
    *,
    scenario: ScenarioDefinition,
    context: InvestigatorPackageContext,
    configuration: CandidateConfiguration,
    environment: dict[str, object],
    client: ProposalModelClient,
    counts: ObservationCounts,
    repetition: int,
    experiment_id: str,
    sink: RecordSink,
    now: Callable[[], datetime],
) -> list[RunRecord]:
    """Execute one chained run of a scenario, carrying real generated state forward."""
    chain_id = f"chain-{uuid.uuid4()}"
    semantic_sample = repetition <= counts.semantic_runs_per_scenario
    prior: _PriorState | None = None
    records: list[RunRecord] = []

    for step_index, step in enumerate(scenario.steps, start=1):
        shared = {
            "experiment_id": experiment_id,
            "configuration_label": configuration.label,
            "configuration_settings": configuration.recorded_settings(),
            "environment": environment,
            "scenario_id": scenario.scenario_id,
            "step_id": step.step_id,
            "mode": step.mode,
            "chain_id": chain_id,
            "chain_repetition": repetition,
            "step_index": step_index,
            "run_index": repetition,
            "semantic_sample": semantic_sample,
        }
        if step.mode != "INITIAL" and prior is None:
            records.append(_not_attempted(shared, now))
            sink.record_run(records[-1])
            continue

        record, response = _run_step(
            step=step,
            context=context,
            prior=prior,
            client=client,
            shared=shared,
            sink=sink,
            now=now,
        )
        records.append(record)
        prior = (
            _prior_state_from(response, step, prior, record.run_id, now())
            if response is not None
            else None
        )
    return records


def _run_step(
    *,
    step: ScenarioStep,
    context: InvestigatorPackageContext,
    prior: _PriorState | None,
    client: ProposalModelClient,
    shared: dict[str, object],
    sink: RecordSink,
    now: Callable[[], datetime],
) -> tuple[RunRecord, ProposalModelResponse | None]:
    """One observation: build, capture verbatim, persist the capture, then evaluate."""
    run_id = f"run-{uuid.uuid4()}"
    request = _generation_request(step, context, prior, now())
    prompt = build_proposal_prompt(request)
    # Evaluator isolation is absolute: nothing leaves for the model unscanned.
    assert_no_evaluator_material(prompt, "a qualification prompt")

    started = time.monotonic()
    raw_response: str | None = None
    failure_category: str | None = None
    failure_message: str | None = None
    try:
        raw_response = client.generate(prompt)
    except ProposalModelError as error:
        failure_category = error.category.value
        failure_message = str(error)
    duration = time.monotonic() - started

    capture = RawCapture(
        prompt=prompt,
        prompt_sha256=sha256_text(prompt),
        duration_seconds=duration,
        raw_response=raw_response,
        transport_failure_category=failure_category,
        transport_failure_message=failure_message,
    )
    # Raw capture is durable before anything is parsed: an unparseable response is
    # data, not a lost run.
    sink.capture_raw(run_id, capture)

    outcome = None
    response = None
    plan = None
    if raw_response is not None:
        outcome, response = evaluate_structural_contract(raw_response)
        if response is not None:
            plan = _presented_plan(response)

    record = RunRecord(
        run_id=run_id,
        recorded_at=now().isoformat(),
        attempted=True,
        raw=capture,
        structural=outcome,
        plan=plan,
        **shared,
    )
    sink.record_run(record)
    return record, response


def _not_attempted(shared: dict[str, object], now: Callable[[], datetime]) -> RunRecord:
    return RunRecord(
        run_id=f"run-{uuid.uuid4()}",
        recorded_at=now().isoformat(),
        attempted=False,
        not_attempted_reason=NotAttemptedReason.CHAIN_PREDECESSOR_UNAVAILABLE.value,
        **shared,
    )


def _generation_request(
    step: ScenarioStep,
    context: InvestigatorPackageContext,
    prior: _PriorState | None,
    created_at: datetime,
) -> ProposalGenerationRequest:
    """Build the product's own request type. The harness adds no prompt of its own."""
    proposal_id = f"harness-proposal-{uuid.uuid4()}"
    if step.mode == "INITIAL":
        return ProposalGenerationRequest(
            context=context,
            objective=step.objective,
            proposal_id=proposal_id,
            created_at=created_at,
            mode="INITIAL",
            investigator_instruction=step.investigator_instruction,
        )
    assert prior is not None
    # The source proposal's persisted status at generation time mirrors the product
    # lifecycle: MODIFIED before a Modify generation, DECLINED before a guided
    # Decline reconsideration. Only the five text fields reach the prompt.
    source = AnalyticalActionProposal(
        proposal_id=prior.proposal.proposal_id,
        action=prior.proposal.action,
        purpose=prior.proposal.purpose,
        why_now=prior.proposal.why_now,
        data_to_be_used=prior.proposal.data_to_be_used,
        expected_output=prior.proposal.expected_output,
        status="MODIFIED" if step.mode == "MODIFY" else "DECLINED",
        created_at=prior.proposal.created_at,
    )
    return ProposalGenerationRequest(
        context=context,
        objective=step.objective,
        proposal_id=proposal_id,
        created_at=created_at,
        mode=step.mode,
        investigator_instruction=step.investigator_instruction,
        current_direction=prior.direction,
        source_proposal=source,
        decline_guidance=step.decline_guidance,
    )


def _prior_state_from(
    response: ProposalModelResponse,
    step: ScenarioStep,
    prior: _PriorState | None,
    run_id: str,
    created_at: datetime,
) -> _PriorState:
    """Build in-memory prior state from a real generated response. No database."""
    version = 1 if prior is None else prior.version + 1
    direction = InvestigationDirection(
        direction_id=f"harness-direction-{run_id}",
        investigation_id=f"harness-investigation-{run_id}",
        version=version,
        competing_explanations=response.direction.competing_explanations,
        plan_steps=response.direction.plan_steps,
        created_at=created_at,
        provenance=step.mode,
    )
    proposal = AnalyticalActionProposal(
        proposal_id=f"harness-proposal-{run_id}",
        action=response.action,
        purpose=response.purpose,
        why_now=response.why_now,
        data_to_be_used=response.data_to_be_used,
        expected_output=response.expected_output,
        status="PROPOSED",
        created_at=created_at,
    )
    return _PriorState(direction=direction, proposal=proposal, version=version)


def _presented_plan(response: ProposalModelResponse) -> PresentedPlan:
    return PresentedPlan(
        competing_explanations=response.direction.competing_explanations,
        plan_steps=response.direction.plan_steps,
        action=response.action,
        purpose=response.purpose,
        why_now=response.why_now,
        data_to_be_used=response.data_to_be_used,
        expected_output=response.expected_output,
    )


def iter_semantic_records(records: Iterable[RunRecord]) -> tuple[RunRecord, ...]:
    """The labelled semantic subset: the first N repetitions of each scenario."""
    return tuple(record for record in records if record.semantic_sample)
