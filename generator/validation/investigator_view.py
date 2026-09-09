"""Validation of references exposed in the investigator-visible case view."""

from __future__ import annotations

from generator.artifacts.manifest import InvestigatorViewManifest
from generator.world.model import CanonicalWorld


def validate_investigator_view_references(
    world: CanonicalWorld, investigator_view: InvestigatorViewManifest
) -> tuple[str, ...]:
    """Return errors for visible world references absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in world.entities}
    event_ids = {event.event_id for event in world.events}
    errors: list[str] = []

    for entity_id in investigator_view.visible_entity_ids:
        if entity_id not in entity_ids:
            errors.append(f"investigator_view: missing visible entity {entity_id}")
    for event_id in investigator_view.visible_event_ids:
        if event_id not in event_ids:
            errors.append(f"investigator_view: missing visible event {event_id}")

    return tuple(errors)
