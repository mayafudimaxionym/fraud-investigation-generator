"""The harness entry point, and the counts it defaults to.

Building the harness and running the qualification campaign are separate work
(`docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 9, steps 6 and 7), so no test
here dispatches a model request and the CLI refuses to dispatch without an explicit
confirmation.
"""

from __future__ import annotations

from validation.qualification.cli import build_parser, main
from validation.qualification.counts import (
    APPROVED_COUNTS,
    ObservationCounts,
    SEMANTIC_ACCEPTANCE_RULE,
    SEMANTIC_SCREENING_GATE_QUALIFICATION,
)


def test_approved_counts_are_ten_structural_and_three_semantic_per_scenario() -> None:
    """Section 2.1, PO-2 and PO-8 as approved."""
    assert APPROVED_COUNTS.structural_runs_per_scenario == 10
    assert APPROVED_COUNTS.semantic_runs_per_scenario == 3
    assert APPROVED_COUNTS.total_structural_runs() == 30
    assert APPROVED_COUNTS.total_semantic_plans() == 9
    assert APPROVED_COUNTS.chain_repetitions == 10


def test_the_screening_gate_qualification_refuses_a_reliability_reading() -> None:
    assert "screening gate" in SEMANTIC_SCREENING_GATE_QUALIFICATION
    assert "not a statistical reliability guarantee" in SEMANTIC_SCREENING_GATE_QUALIFICATION
    assert "does not establish a reliability rate" in SEMANTIC_SCREENING_GATE_QUALIFICATION
    assert "never pooled" in SEMANTIC_SCREENING_GATE_QUALIFICATION


def test_the_acceptance_rule_reserves_the_judgement_to_the_product_owner() -> None:
    assert "Product Owner" in SEMANTIC_ACCEPTANCE_RULE
    assert "no partial or per-scenario pass" in SEMANTIC_ACCEPTANCE_RULE
    assert "records and presents, never judges" in SEMANTIC_ACCEPTANCE_RULE


def test_semantic_runs_cannot_exceed_structural_runs() -> None:
    try:
        ObservationCounts(structural_runs_per_scenario=2, semantic_runs_per_scenario=3)
    except ValueError:
        return
    raise AssertionError("the semantic subset must fit inside the structural runs")


def test_listing_scenarios_dispatches_nothing(capsys) -> None:
    assert main(["--list-scenarios"]) == 0

    output = capsys.readouterr().out
    assert "v05-representative-chain" in output
    assert "INITIAL" in output and "MODIFY" in output and "DECLINE_REDIRECT" in output


def test_a_sweep_without_confirmation_reports_the_plan_and_dispatches_nothing(capsys) -> None:
    assert main(["--model", "qwen3:30b", "--label", "qwen3-30b-64k"]) == 0

    output = capsys.readouterr().out
    assert "Counts per semantic scenario: 10 structural, 3 presented" in output
    assert "Model requests to dispatch: 30" in output
    assert "Nothing dispatched" in output
    assert "--confirm-run" in output


def test_a_dry_run_reports_the_plan_and_dispatches_nothing(capsys) -> None:
    assert main(["--model", "qwen3:30b", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "Dry run. Nothing dispatched." in output


def test_counts_below_the_approved_counts_are_warned_about(capsys) -> None:
    assert main(["--model", "qwen3:30b", "--structural-runs", "5", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "below the approved section 2.1 counts" in output
    assert "does not satisfy the observation counts" in output


def test_a_semantic_count_larger_than_the_structural_count_is_a_clean_cli_error() -> None:
    try:
        main(["--model", "qwen3:30b", "--structural-runs", "2", "--dry-run"])
    except SystemExit as error:
        assert error.code == 2
        return
    raise AssertionError("the CLI must reject an impossible combination of counts")


def test_the_cli_defaults_to_the_approved_counts() -> None:
    arguments = build_parser().parse_args(["--model", "qwen3:30b"])

    assert arguments.structural_runs == APPROVED_COUNTS.structural_runs_per_scenario
    assert arguments.semantic_runs == APPROVED_COUNTS.semantic_runs_per_scenario
    assert arguments.confirm_run is False


def test_an_unknown_scenario_id_is_rejected() -> None:
    try:
        main(["--model", "qwen3:30b", "--scenario", "does-not-exist"])
    except SystemExit as error:
        assert "unknown scenario id" in str(error)
        return
    raise AssertionError("an unknown scenario id must be rejected")


def test_mismatched_models_and_labels_are_rejected() -> None:
    try:
        main(["--model", "a:1b", "--model", "b:1b", "--label", "only-one"])
    except SystemExit:
        return
    raise AssertionError("labels must match models one for one when supplied")
