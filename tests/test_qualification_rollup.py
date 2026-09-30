"""Roll-ups report per-scenario counts and one clearly-labelled structural rate.

Requirements: `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` sections 2.1 and 4.
"""

from __future__ import annotations

import json

from validation.qualification.counts import APPROVED_COUNTS, ObservationCounts
from validation.qualification.rollup import build_rollup
from validation.qualification.runner import run_sweep
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


def _records(script, counts, scenario=None, configurations=None):
    client = ScriptedClient(script)
    return run_sweep(
        (scenario or chained_scenario(),),
        configurations or (configuration(),),
        counts=counts,
        client_factory=lambda _: client,
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        experiment_id="experiment-test",
        clock=fixed_clock,
    )


def _chain(marker: str = "x") -> list[str]:
    return [valid_response_text(f"{marker}-i"), valid_response_text(f"{marker}-m"),
            valid_response_text(f"{marker}-d")]


def test_rollup_reports_a_validity_rate_per_scenario_and_never_pooled() -> None:
    counts = ObservationCounts(2, 1)
    records = _records(_chain("a") + [valid_response_text("b-i"), "not json", "not json"], counts)

    rollup = build_rollup("experiment-test", records, counts=counts)
    scenarios = {scenario.mode: scenario for scenario in rollup.configurations[0].scenarios}

    assert scenarios["INITIAL"].structural_validity_rate == 1.0
    assert scenarios["MODIFY"].structural_validity_rate == 0.5
    assert scenarios["DECLINE_REDIRECT"].attempted_runs == 1
    assert scenarios["DECLINE_REDIRECT"].structural_validity_rate == 1.0
    # No figure spans scenarios.
    record = rollup.as_record()
    assert "structural_validity_rate" not in record
    for configuration_record in record["configurations"]:
        assert "structural_validity_rate" not in configuration_record


def test_rollup_counts_failure_categories_by_check_and_by_transport() -> None:
    counts = ObservationCounts(2, 1)
    records = _records(
        _chain("a") + [transport_failure()],
        counts,
    )

    rollup = build_rollup("experiment-test", records, counts=counts)
    scenarios = {scenario.mode: scenario for scenario in rollup.configurations[0].scenarios}

    assert scenarios["INITIAL"].transport_failures == {"SERVICE_UNAVAILABLE": 1}
    assert scenarios["INITIAL"].structurally_valid_runs == 1
    assert scenarios["MODIFY"].not_attempted_reasons == {"CHAIN_PREDECESSOR_UNAVAILABLE": 1}


def test_an_under_observed_scenario_is_reported_as_short_of_the_required_counts() -> None:
    """A chain failure must not look like a complete result."""
    counts = ObservationCounts(2, 1)
    records = _records(_chain("a") + [transport_failure()], counts)

    rollup = build_rollup("experiment-test", records, counts=counts)
    scenarios = {scenario.mode: scenario for scenario in rollup.configurations[0].scenarios}

    assert scenarios["INITIAL"].meets_required_structural_observations is True
    assert scenarios["MODIFY"].attempted_runs == 1
    assert scenarios["MODIFY"].required_structural_runs == 2
    assert scenarios["MODIFY"].meets_required_structural_observations is False
    assert rollup.configurations[0].observation_counts_complete is False


def test_rollup_records_the_approved_counts_and_the_screening_gate_qualification() -> None:
    records = _records(_chain(), ObservationCounts(1, 1))

    record = build_rollup("experiment-test", records, counts=APPROVED_COUNTS).as_record()

    assert record["observation_counts"]["structural_runs_per_scenario"] == 10
    assert record["observation_counts"]["semantic_runs_per_scenario"] == 3
    assert "screening gate" in record["semantic_screening_gate_qualification"]
    assert "not a statistical reliability guarantee" in (
        record["semantic_screening_gate_qualification"]
    )
    assert "three-of-three within each scenario" in (
        record["semantic_screening_gate_qualification"]
    )


def test_rollup_describes_no_reliability_rate_and_makes_no_pooled_nine_run_claim() -> None:
    """Section 2.1 forbids both, in any output, report, roll-up or record."""
    records = _records(_chain(), ObservationCounts(1, 1))

    serialized = json.dumps(
        build_rollup("experiment-test", records, counts=APPROVED_COUNTS).as_record()
    ).casefold()

    assert "reliability rate" not in serialized.replace(
        "does not establish a reliability rate", ""
    ).replace("establishing a reliability rate", "")
    for pooled in ("nine-of-nine", "9 of 9", "nine of nine", "9/9"):
        assert pooled not in serialized


def test_rollup_reports_semantic_plans_as_presented_never_as_judged() -> None:
    counts = ObservationCounts(2, 1)
    records = _records(_chain("a") + _chain("b"), counts)

    rollup = build_rollup("experiment-test", records, counts=counts)
    scenario = rollup.configurations[0].scenarios[0]

    assert scenario.semantic_plans_presented == 1
    assert "count of runs presented, never a count of runs judged adequate" in (
        scenario.as_record()["semantic_plans_presented_basis"]
    )


def test_rollup_keeps_configurations_separate_in_a_sweep() -> None:
    clients: dict[str, ScriptedClient] = {}

    def factory(candidate):
        script = _chain(candidate.label) if candidate.label == "config-a" else ["not json"]
        clients[candidate.label] = ScriptedClient(script)
        return clients[candidate.label]

    records = run_sweep(
        (chained_scenario(),),
        (configuration("config-a"), configuration("config-b", "other:1b")),
        counts=ObservationCounts(1, 1),
        client_factory=factory,
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        experiment_id="experiment-test",
        clock=fixed_clock,
    )

    rollup = build_rollup("experiment-test", records, counts=ObservationCounts(1, 1))

    assert [item.configuration_label for item in rollup.configurations] == [
        "config-a", "config-b",
    ]
    by_label = {item.configuration_label: item for item in rollup.configurations}
    assert by_label["config-a"].scenarios[0].structurally_valid_runs == 1
    assert by_label["config-b"].scenarios[0].structurally_invalid_runs == 1


def test_a_scenario_with_no_attempted_run_reports_no_rate_rather_than_zero() -> None:
    single_step = ScenarioDefinition(
        scenario_id="initial-only",
        name="Initial only",
        description="One INITIAL step.",
        package_directory=chained_scenario().package_directory,
        steps=(ScenarioStep("initial", "INITIAL", "Assess the disputed transfers."),),
    )
    records = _records([transport_failure()], ObservationCounts(1, 1), scenario=single_step)

    rollup = build_rollup("experiment-test", records, counts=ObservationCounts(1, 1))
    scenario = rollup.configurations[0].scenarios[0]

    assert scenario.attempted_runs == 1
    assert scenario.structurally_valid_runs == 0
    assert scenario.structural_validity_rate == 0.0

    missing = _records(
        repeating_script([], 0) or [transport_failure()],
        ObservationCounts(1, 1),
        scenario=chained_scenario(),
    )
    modify = [record for record in missing if record.mode == "MODIFY"]
    modify_rollup = build_rollup(
        "experiment-test", modify, counts=ObservationCounts(1, 1)
    ).configurations[0].scenarios[0]
    assert modify_rollup.attempted_runs == 0
    assert modify_rollup.structural_validity_rate is None
