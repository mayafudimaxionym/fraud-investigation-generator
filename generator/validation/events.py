"""Validation of canonical event references."""

from __future__ import annotations

from collections.abc import Iterable

from generator.events.models import CanonicalEvent
from generator.world.entities import CanonicalEntity


def validate_event_references(
    entities: Iterable[CanonicalEntity], events: Iterable[CanonicalEvent]
) -> tuple[str, ...]:
    """Return errors for event subjects absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in entities}
    errors: list[str] = []

    for event in events:
        if event.subject_entity_id not in entity_ids:
            errors.append(
                f"{event.event_id}: missing subject {event.subject_entity_id}"
            )

    return tuple(errors)
