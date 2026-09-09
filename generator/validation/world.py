"""Deterministic validation for a complete canonical world."""

from __future__ import annotations

from generator.validation.events import validate_event_references
from generator.validation.relationships import validate_relationship_references
from generator.validation.signals import validate_signal_references
from generator.world.model import CanonicalWorld


def validate_world_references(world: CanonicalWorld) -> tuple[str, ...]:
    """Return all missing entity-reference errors in a canonical world."""
    relationship_errors = validate_relationship_references(
        world.entities, world.relationships
    )
    event_errors = validate_event_references(world.entities, world.events)
    signal_errors = validate_signal_references(
        world.entities, world.events, world.signals
    )
    return relationship_errors + event_errors + signal_errors
