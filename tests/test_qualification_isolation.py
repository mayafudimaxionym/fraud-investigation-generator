"""Evaluator isolation is absolute, and the scan covers what actually carries data.

`docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 4: ground truth, campaigns,
signals and hypotheses must never enter a prompt or an experiment record.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from validation.qualification.contract import CHECK_COVERAGE
from validation.qualification.counts import ObservationCounts
from validation.qualification.isolation import (
    EvaluatorIsolationError,
    assert_no_evaluator_material,
    load_governed_context,
)
from validation.qualification.records import PresentedPlan
from validation.qualification.runner import run_sweep

from qualification_support import (
    ScriptedClient,
    chained_scenario,
    configuration,
    context,
    environment_probe,
    fixed_clock,
    valid_response_text,
)


def _records():
    return run_sweep(
        (chained_scenario(),),
        (configuration(),),
        counts=ObservationCounts(1, 1),
        client_factory=lambda _: ScriptedClient([
            valid_response_text("i"), valid_response_text("m"), valid_response_text("d"),
        ]),
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        experiment_id="experiment-test",
        clock=fixed_clock,
    )


def test_the_scan_uses_the_products_token_list_and_aborts_rather_than_redacting() -> None:
    for leak in ("the ground truth manifest", "campaigns.csv", "EVALUATOR_ONLY notes",
                 "the canonical world"):
        try:
            assert_no_evaluator_material(leak, "a prompt")
        except EvaluatorIsolationError as error:
            assert "a prompt" in str(error)
            continue
        raise AssertionError(f"evaluator-only material was not detected: {leak}")


def test_governed_context_is_the_only_way_the_harness_loads_a_package() -> None:
    """The structural boundary: only the package's investigator subtree is read."""
    package = Path(__file__).resolve().parents[1] / "output" / "development-case-42"
    if not (package / "investigator").is_dir():
        return

    loaded = load_governed_context(package)

    assert loaded.investigation_request
    assert {dataset.dataset_name for dataset in loaded.datasets} == {
        "visible_entities.csv", "visible_relationships.csv", "visible_events.csv",
    }
    assert_no_evaluator_material(
        "\n".join([
            loaded.investigation_request,
            loaded.customer_support_statement,
            loaded.prior_analyst_note,
        ]),
        "the loaded governed context",
    )


def test_the_scanned_surface_includes_verbatim_model_output() -> None:
    """Leakage in what the model returned must be caught, not only in the prompt."""
    record = _records()[0]
    leaking = replace(
        record,
        plan=replace(record.plan, data_to_be_used="the ground truth manifest"),
    )

    try:
        assert_no_evaluator_material(leaking.data_text(), "a run record")
    except EvaluatorIsolationError:
        return
    raise AssertionError("evaluator-only material in model output must be detected")


def test_the_scanned_surface_includes_the_prompt_and_the_raw_response() -> None:
    record = _records()[0]

    data = record.data_text()

    assert record.raw.prompt in data
    assert record.raw.raw_response in data


def test_the_scanned_surface_excludes_the_harnesss_own_check_descriptions() -> None:
    """The guard must not fire on prose that merely names the check it performs."""
    record = _records()[0]
    description = CHECK_COVERAGE["NO_PRIVATE_REFERENCES"]

    assert "evaluator-only" in description
    assert description not in record.data_text()
    assert_no_evaluator_material(record.data_text(), "a run record")


def test_a_plan_absent_from_a_failed_run_does_not_break_the_scan() -> None:
    record = _records()[0]
    without_plan = replace(record, plan=None, structural=None)

    assert_no_evaluator_material(without_plan.data_text(), "a run record")


def test_presented_plan_is_content_only_and_carries_no_derived_fields() -> None:
    fields = set(PresentedPlan.__dataclass_fields__)

    assert fields == {
        "competing_explanations", "plan_steps", "action", "purpose", "why_now",
        "data_to_be_used", "expected_output",
    }
