"""Sweep execution: the approved counts, real chained prior state, raw capture first.

Requirements under test come from `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md`
sections 2.1 and 4. No test here contacts Ollama.
"""

from __future__ import annotations

import json

from investigation.proposal_agent import ProposalModelFailureCategory

from validation.qualification.counts import APPROVED_COUNTS, ObservationCounts
from validation.qualification.isolation import EvaluatorIsolationError
from validation.qualification.records import NotAttemptedReason
from validation.qualification.runner import CollectingSink, iter_semantic_records, run_sweep
from validation.qualification.scenarios import ScenarioDefinition, ScenarioStep

from qualification_support import (
    ScriptedClient,
    chained_scenario,
    configuration,
    context,
    environment_probe,
    fixed_clock,
    repeating_script,
    transport_failure,
    valid_response_text,
)


def _run(script, *, counts=None, scenario=None, configurations=None, sink=None):
    resolved_counts = counts or ObservationCounts(2, 1)
    client = ScriptedClient(script)
    records = run_sweep(
        (scenario or chained_scenario(),),
        configurations or (configuration(),),
        counts=resolved_counts,
        client_factory=lambda _: client,
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        sink=sink,
        experiment_id="experiment-test",
        clock=fixed_clock,
    )
    return records, client


def test_sweep_produces_the_approved_count_of_runs_of_every_scenario() -> None:
    """Section 2.1: 10 runs of each scenario, per candidate configuration."""
    script = repeating_script(
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
        APPROVED_COUNTS.chain_repetitions,
    )
    records, client = _run(script, counts=APPROVED_COUNTS)

    for mode in ("INITIAL", "MODIFY", "DECLINE_REDIRECT"):
        for_mode = [record for record in records if record.mode == mode]
        assert len(for_mode) == APPROVED_COUNTS.structural_runs_per_scenario == 10
        assert {record.run_index for record in for_mode} == set(range(1, 11))
    assert len(records) == 30
    assert client.call_count == 30


def test_semantic_subset_is_three_labelled_runs_of_each_scenario() -> None:
    """Section 2.1: 3 runs of each scenario, nine plans, each labelled and read in full."""
    script = repeating_script(
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
        APPROVED_COUNTS.chain_repetitions,
    )
    records, _ = _run(script, counts=APPROVED_COUNTS)

    semantic = iter_semantic_records(records)
    assert len(semantic) == 9
    for mode in ("INITIAL", "MODIFY", "DECLINE_REDIRECT"):
        for_mode = [record for record in semantic if record.mode == mode]
        assert len(for_mode) == APPROVED_COUNTS.semantic_runs_per_scenario == 3
        assert sorted(record.run_index for record in for_mode) == [1, 2, 3]


def test_each_observation_issues_exactly_one_model_request_and_never_retries() -> None:
    """ADR 006 and section 4: not a repair path, not a retry path."""
    script = [valid_response_text("i"), "not json", valid_response_text("d")]
    records, client = _run(script, counts=ObservationCounts(1, 1))

    # The invalid MODIFY response is not retried and does not produce a second request.
    assert client.call_count == 2
    assert [record.attempted for record in records] == [True, True, False]


def test_modify_runs_against_the_real_generated_prior_state() -> None:
    """Section 4: chaining against real prior state, because adherence spans steps."""
    initial = valid_response_text("from-initial")
    records, client = _run(
        [initial, valid_response_text("m"), valid_response_text("d")],
        counts=ObservationCounts(1, 1),
    )

    modify_prompt = client.prompts[1]
    generated = json.loads(initial)
    for explanation in generated["competing_explanations"]:
        assert explanation in modify_prompt
    for step in generated["plan_steps"]:
        assert step in modify_prompt
    assert generated["proposal"]["action"] in modify_prompt
    assert "Limit the action to visible_events.csv" in modify_prompt
    assert records[1].mode == "MODIFY"


def test_decline_runs_against_the_state_generated_by_the_modify_step() -> None:
    modify = valid_response_text("from-modify")
    _, client = _run(
        [valid_response_text("i"), modify, valid_response_text("d")],
        counts=ObservationCounts(1, 1),
    )

    decline_prompt = client.prompts[2]
    assert json.loads(modify)["proposal"]["action"] in decline_prompt
    assert "Redirect to relationship structure only." in decline_prompt


def test_raw_capture_is_written_before_the_response_is_parsed() -> None:
    """Section 4: raw capture before parsing. An unparseable response is data."""
    sink = CollectingSink()
    records, _ = _run(
        [valid_response_text("i"), "{ not valid json", valid_response_text("d")],
        counts=ObservationCounts(1, 1),
        sink=sink,
    )

    modify = records[1]
    assert modify.raw is not None
    assert modify.raw.raw_response == "{ not valid json"
    assert modify.structurally_valid is False
    assert modify.structural.failed_check == "JSON_PARSE"
    # The capture for the unparseable run reached the sink, and it did so before the
    # completed record: the run was not lost.
    captured_ids = [run_id for run_id, _ in sink.raw_captures]
    assert modify.run_id in captured_ids
    assert len(sink.raw_captures) == 2


def test_every_run_records_prompt_digest_duration_digest_and_version() -> None:
    records, _ = _run(
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
        counts=ObservationCounts(1, 1),
    )

    for record in records:
        assert record.raw is not None
        assert record.raw.prompt
        assert len(record.raw.prompt_sha256) == 64
        assert record.raw.duration_seconds >= 0
        assert record.environment["model_digest"] == "digest-abc"
        assert record.environment["ollama_version"] == "0.34.3"


def test_transport_failure_is_recorded_with_its_category_not_lost() -> None:
    records, _ = _run(
        [transport_failure(ProposalModelFailureCategory.REQUEST_TIMEOUT)],
        counts=ObservationCounts(1, 1),
    )

    initial = records[0]
    assert initial.attempted is True
    assert initial.raw is not None
    assert initial.raw.raw_response is None
    assert initial.raw.transport_failure_category == "REQUEST_TIMEOUT"
    assert initial.structural is None


def test_a_failed_predecessor_records_downstream_steps_as_not_attempted() -> None:
    """No fabricated prior state, and no silently missing observation."""
    records, client = _run([transport_failure()], counts=ObservationCounts(1, 1))

    assert client.call_count == 1
    assert [record.mode for record in records] == ["INITIAL", "MODIFY", "DECLINE_REDIRECT"]
    for downstream in records[1:]:
        assert downstream.attempted is False
        assert downstream.not_attempted_reason == (
            NotAttemptedReason.CHAIN_PREDECESSOR_UNAVAILABLE.value
        )
        assert downstream.raw is None
        assert downstream.plan is None


def test_a_sweep_compares_configurations_without_editing_scenario_text() -> None:
    """Section 4: sweeps across models and configurations, scenario text untouched."""
    scenario = chained_scenario()
    clients: dict[str, ScriptedClient] = {}

    def factory(candidate):
        clients[candidate.label] = ScriptedClient([
            valid_response_text(candidate.label) for _ in range(3)
        ])
        return clients[candidate.label]

    records = run_sweep(
        (scenario,),
        (configuration("config-a", "model-a:1b"), configuration("config-b", "model-b:1b")),
        counts=ObservationCounts(1, 1),
        client_factory=factory,
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        experiment_id="experiment-test",
        clock=fixed_clock,
    )

    assert {record.configuration_label for record in records} == {"config-a", "config-b"}
    assert {record.scenario_id for record in records} == {scenario.scenario_id}
    assert clients["config-a"].call_count == clients["config-b"].call_count == 3
    prompts_a = clients["config-a"].prompts[0]
    prompts_b = clients["config-b"].prompts[0]
    assert prompts_a == prompts_b, "the same scenario text must reach every configuration"


def test_duplicate_configuration_labels_are_rejected() -> None:
    try:
        run_sweep(
            (chained_scenario(),),
            (configuration("same"), configuration("same", "other:1b")),
            counts=ObservationCounts(1, 1),
            client_factory=lambda _: ScriptedClient([]),
            environment_probe=environment_probe,
            context_loader=lambda _: context(),
        )
    except ValueError:
        return
    raise AssertionError("a sweep must reject duplicate candidate configuration labels")


def test_evaluator_material_in_a_scenario_aborts_before_any_model_request() -> None:
    """Section 4: evaluator isolation is absolute. Nothing reaches a prompt."""
    leaking = ScenarioDefinition(
        scenario_id="leaking",
        name="Leaking scenario",
        description="Carries evaluator-only material in its objective.",
        package_directory=chained_scenario().package_directory,
        steps=(ScenarioStep("initial", "INITIAL", "Use the ground truth manifest."),),
    )
    client = ScriptedClient([valid_response_text()])

    try:
        run_sweep(
            (leaking,),
            (configuration(),),
            counts=ObservationCounts(1, 1),
            client_factory=lambda _: client,
            environment_probe=environment_probe,
            context_loader=lambda _: context(),
            clock=fixed_clock,
        )
    except EvaluatorIsolationError:
        assert client.call_count == 0
        return
    raise AssertionError("evaluator-only material must never reach a prompt")


def test_the_harness_records_no_score_field_of_any_kind() -> None:
    """Section 4 hard prohibition: no automated value that reads as a quality verdict."""
    records, _ = _run(
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
        counts=ObservationCounts(1, 1),
    )

    serialized = json.dumps([record.as_record() for record in records])
    for forbidden in ("score", "rating", "rank", "grade", "adequacy", "quality"):
        assert forbidden not in serialized.casefold(), (
            f"a run record must not contain a {forbidden} value"
        )
