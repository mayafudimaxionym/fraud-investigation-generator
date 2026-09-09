"""Validation of private ground truth against declared scenario intent."""

from __future__ import annotations

from generator.scenario.spec import ScenarioSpec
from generator.world.model import CanonicalWorld
from generator.world.truth import GroundTruthManifest


def validate_ground_truth_hypothesis(
    scenario: ScenarioSpec, ground_truth: GroundTruthManifest
) -> tuple[str, ...]:
    """Return an error when truth resolves to an undeclared hypothesis."""
    if ground_truth.correct_hypothesis not in scenario.competing_hypotheses:
        return (
            "correct_hypothesis must be declared in competing_hypotheses",
        )
    return ()


def validate_ground_truth_references(
    world: CanonicalWorld, ground_truth: GroundTruthManifest
) -> tuple[str, ...]:
    """Return errors for truth references absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in world.entities}
    event_ids = {event.event_id for event in world.events}
    signal_ids = {signal.signal_id for signal in world.signals}
    errors: list[str] = []

    for entity_id in ground_truth.fraudulent_entity_ids:
        if entity_id not in entity_ids:
            errors.append(f"ground_truth: missing fraudulent entity {entity_id}")
    for event_id in ground_truth.fraudulent_event_ids:
        if event_id not in event_ids:
            errors.append(f"ground_truth: missing fraudulent event {event_id}")
    for signal_id in ground_truth.causal_signal_ids:
        if signal_id not in signal_ids:
            errors.append(f"ground_truth: missing causal signal {signal_id}")
    for signal_id in ground_truth.red_herring_ids:
        if signal_id not in signal_ids:
            errors.append(f"ground_truth: missing red herring {signal_id}")

    return tuple(errors)
