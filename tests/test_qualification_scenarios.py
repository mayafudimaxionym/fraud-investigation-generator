"""Version-controlled scenario definitions (PO-4, approved)."""

from __future__ import annotations

import json
from pathlib import Path

from validation.qualification.counts import SEMANTIC_SCENARIO_MODES
from validation.qualification.scenarios import (
    SCENARIO_DIRECTORY,
    ScenarioDefinition,
    ScenarioStep,
    load_scenario,
    load_scenarios,
)


def test_committed_scenarios_load_and_cover_the_three_semantic_scenarios() -> None:
    scenarios = load_scenarios()

    assert scenarios, "at least one scenario must be version-controlled"
    chained = [
        scenario for scenario in scenarios
        if tuple(step.mode for step in scenario.steps) == SEMANTIC_SCENARIO_MODES
    ]
    assert chained, "a scenario must chain INITIAL, MODIFY and DECLINE_REDIRECT"


def test_committed_scenarios_reference_an_existing_package_and_carry_their_text() -> None:
    for scenario in load_scenarios():
        assert scenario.package_directory.is_dir(), scenario.scenario_id
        modify = scenario.step_for_mode("MODIFY")
        decline = scenario.step_for_mode("DECLINE_REDIRECT")
        assert modify.investigator_instruction
        assert decline.decline_guidance
        assert scenario.step_for_mode("INITIAL").objective


def test_committed_scenarios_carry_no_evaluator_only_material() -> None:
    """Section 4: evaluator isolation is absolute, including in scenario definitions."""
    from validation.qualification.isolation import assert_no_evaluator_material

    for path in sorted(SCENARIO_DIRECTORY.glob("*.json")):
        assert_no_evaluator_material(path.read_text(encoding="utf-8"), str(path))


def test_a_scenario_must_begin_with_an_initial_step() -> None:
    try:
        ScenarioDefinition(
            scenario_id="bad",
            name="Bad",
            description="Starts at MODIFY with no real prior state to modify.",
            package_directory=Path("output"),
            steps=(ScenarioStep("modify", "MODIFY", "", investigator_instruction="Narrow it."),),
        )
    except ValueError:
        return
    raise AssertionError("a chained scenario must begin with an INITIAL step")


def test_step_definitions_enforce_the_products_own_mode_rules() -> None:
    for bad in (
        lambda: ScenarioStep("modify", "MODIFY", ""),
        lambda: ScenarioStep("decline", "DECLINE_REDIRECT", ""),
        lambda: ScenarioStep(
            "decline", "DECLINE_REDIRECT", "", investigator_instruction="Not allowed here.",
            decline_guidance="Redirect.",
        ),
        lambda: ScenarioStep("initial", "INITIAL", "", decline_guidance="Not allowed here."),
        lambda: ScenarioStep("initial", "UNKNOWN_MODE", ""),
    ):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("an invalid scenario step must be rejected")


def test_unexpected_definition_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({
        "scenario_id": "s", "name": "n", "description": "d",
        "package_directory": "output", "steps": [
            {"step_id": "initial", "mode": "INITIAL", "objective": "o"}
        ],
        "expected_verdict": "PASS",
    }), encoding="utf-8")

    try:
        load_scenario(path)
    except ValueError as error:
        assert "unexpected fields" in str(error)
        return
    raise AssertionError("an unexpected scenario field must be rejected")


def test_absolute_package_paths_are_rejected_so_definitions_stay_portable(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({
        "scenario_id": "s", "name": "n", "description": "d",
        "package_directory": str(tmp_path),
        "steps": [{"step_id": "initial", "mode": "INITIAL", "objective": "o"}],
    }), encoding="utf-8")

    try:
        load_scenario(path)
    except ValueError as error:
        assert "repository-relative" in str(error)
        return
    raise AssertionError("an absolute package path must be rejected")


def test_an_intentionally_blank_objective_is_permitted(tmp_path: Path) -> None:
    """The product treats a blank effective objective as a real case."""
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({
        "scenario_id": "blank", "name": "Blank objective", "description": "d",
        "package_directory": "output",
        "steps": [{"step_id": "initial", "mode": "INITIAL", "objective": ""}],
    }), encoding="utf-8")

    scenario = load_scenario(path)

    assert scenario.steps[0].objective == ""
