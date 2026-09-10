"""Deterministic validation orchestration for canonical cases."""

from __future__ import annotations

from generator.case import CanonicalCase
from generator.validation.ground_truth import (
    validate_ground_truth_hypothesis,
    validate_ground_truth_references,
)
from generator.validation.investigator_view import validate_investigator_view_references
from generator.validation.world import validate_world_references


def validate_case(case: CanonicalCase) -> tuple[str, ...]:
    """Return deterministic consistency errors for a canonical case."""
    world_errors = validate_world_references(case.world)
    hypothesis_errors = validate_ground_truth_hypothesis(
        case.scenario, case.ground_truth
    )
    ground_truth_errors = validate_ground_truth_references(
        case.world, case.ground_truth
    )
    investigator_view_errors = validate_investigator_view_references(
        case.world, case.investigator_view, case.artifacts
    )
    return (
        world_errors
        + hypothesis_errors
        + ground_truth_errors
        + investigator_view_errors
    )
