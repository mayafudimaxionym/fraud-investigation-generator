"""The semantic acceptance package: nine plans, grouped by scenario, labelled, unjudged.

`docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 2.1 states the grouping and
labelling as a presentation requirement, not an option, so stability within a scenario
is visible rather than an undifferentiated set. Section 4 prohibits any automated
quality signal in the package.
"""

from __future__ import annotations

import json

from validation.qualification.counts import APPROVED_COUNTS, ObservationCounts
from validation.qualification.presentation import build_semantic_acceptance_package
from validation.qualification.runner import run_sweep

from qualification_support import (
    ScriptedClient,
    chained_scenario,
    configuration,
    context,
    environment_probe,
    fixed_clock,
    transport_failure,
    valid_response_text,
)


def _records(script, counts):
    client = ScriptedClient(script)
    return run_sweep(
        (chained_scenario(),),
        (configuration(),),
        counts=counts,
        client_factory=lambda _: client,
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        experiment_id="experiment-test",
        clock=fixed_clock,
    )


def _full_nine():
    script = []
    for repetition in range(1, APPROVED_COUNTS.chain_repetitions + 1):
        script.extend([
            valid_response_text(f"initial-{repetition}"),
            valid_response_text(f"modify-{repetition}"),
            valid_response_text(f"decline-{repetition}"),
        ])
    return _records(script, APPROVED_COUNTS)


def test_package_presents_nine_plans_grouped_by_scenario_with_run_indexes() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )

    assert package.count("### ") == 9
    assert "## Scenario — Initial (`INITIAL`)" in package
    assert "## Scenario — Modify (`MODIFY`)" in package
    assert "## Scenario — Decline / redirect (`DECLINE_REDIRECT`)" in package
    for heading in ("Initial", "Modify", "Decline / redirect"):
        for index in (1, 2, 3):
            assert f"### {heading} — run {index} of 3" in package


def test_each_presented_run_is_labelled_with_its_scenario_and_run_index() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )

    assert package.count("- Scenario: `INITIAL`") == 3
    assert package.count("- Scenario: `MODIFY`") == 3
    assert package.count("- Scenario: `DECLINE_REDIRECT`") == 3
    assert package.count("- Run index within this scenario:") == 9


def test_every_presented_run_is_rendered_in_full() -> None:
    records = _full_nine()
    package = build_semantic_acceptance_package("experiment-test", "test-config", records)

    presented = [record for record in records if record.semantic_sample and record.plan]
    for record in presented:
        plan = record.plan
        for explanation in plan.competing_explanations:
            assert explanation in package
        for step in plan.plan_steps:
            assert step in package
        for field in (plan.action, plan.purpose, plan.why_now,
                      plan.data_to_be_used, plan.expected_output):
            assert field in package


def test_package_states_the_screening_gate_qualification() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )

    assert "screening gate against gross instability" in package
    assert "not a statistical reliability guarantee" in package
    assert "three-of-three within each scenario" in package


def test_package_makes_no_pooled_nine_run_confidence_claim() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    ).casefold()

    for pooled in ("nine-of-nine", "nine of nine", "9 of 9", "9/9", "9 out of 9"):
        assert pooled not in package


def test_package_contains_no_score_ranking_or_verdict() -> None:
    """Section 4 hard prohibition, and ADR 006."""
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )
    folded = package.casefold()
    assert "did not score, rank, rate or order them by quality" in folded

    # The only place any of these words may appear is the disclaimer that denies them.
    body = "\n".join(
        line for line in folded.splitlines()
        if "did not score, rank, rate or order them by quality" not in line
    )
    for forbidden in ("score", "rubric", "rating", "ranked", "grade", "overall verdict"):
        assert forbidden not in body
    assert folded.count("product owner judgement for this run") == 9


def test_package_records_the_configuration_under_judgement() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )

    assert "- Model: `test-model:1b`" in package
    assert "- Model digest: `digest-abc`" in package
    assert "- Ollama version: `0.34.3`" in package
    assert "temperature `0.0`" in package
    assert "seed `42`" in package


def test_package_states_which_prior_state_each_chained_run_used() -> None:
    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", _full_nine()
    )

    assert package.count(
        "prior state for this run was generated by the preceding step of this same chain"
    ) == 9


def test_an_incomplete_package_says_so_instead_of_reading_as_complete() -> None:
    records = _records(
        [valid_response_text("i"), valid_response_text("m"), transport_failure()],
        ObservationCounts(1, 1),
    )

    package = build_semantic_acceptance_package(
        "experiment-test", "test-config", records, counts=APPROVED_COUNTS
    )

    assert "## Incomplete package" in package
    assert "does not meet the section 2.1 observation counts" in package
    assert "`DECLINE_REDIRECT`: 0 of 3 required runs presented." in package
    assert "not an adequate result and not an inadequate one" in package


def test_package_omits_runs_beyond_the_semantic_subset() -> None:
    records = _full_nine()
    package = build_semantic_acceptance_package("experiment-test", "test-config", records)

    beyond = [
        record for record in records
        if not record.semantic_sample and record.plan is not None
    ]
    assert beyond, "the fixture must contain structural-only runs"
    for record in beyond:
        assert record.run_id not in package


def test_package_is_scoped_to_one_candidate_configuration() -> None:
    clients: dict[str, ScriptedClient] = {}

    def factory(candidate):
        clients[candidate.label] = ScriptedClient([
            valid_response_text(f"{candidate.label}-{index}") for index in range(3)
        ])
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

    package = build_semantic_acceptance_package("experiment-test", "config-a", records)

    assert "config-a" in package
    assert "config-b-0" not in package


def test_presented_plan_content_is_exactly_what_the_model_returned() -> None:
    initial = valid_response_text("exact")
    records = _records(
        [initial, valid_response_text("m"), valid_response_text("d")],
        ObservationCounts(1, 1),
    )

    generated = json.loads(initial)
    plan = records[0].plan
    assert list(plan.competing_explanations) == generated["competing_explanations"]
    assert list(plan.plan_steps) == generated["plan_steps"]
    assert plan.action == generated["proposal"]["action"]
