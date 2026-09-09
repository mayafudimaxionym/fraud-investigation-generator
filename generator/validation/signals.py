"""Validation of evidence references supporting canonical signals."""

from __future__ import annotations

from collections.abc import Iterable

from generator.events.models import CanonicalEvent
from generator.world.entities import CanonicalEntity
from generator.world.signals import CanonicalSignal


def validate_signal_references(
    entities: Iterable[CanonicalEntity],
    events: Iterable[CanonicalEvent],
    signals: Iterable[CanonicalSignal],
) -> tuple[str, ...]:
    """Return errors for signal evidence absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in entities}
    event_ids = {event.event_id for event in events}
    errors: list[str] = []

    for signal in signals:
        for entity_id in signal.supporting_entity_ids:
            if entity_id not in entity_ids:
                errors.append(f"{signal.signal_id}: missing entity {entity_id}")
        for event_id in signal.supporting_event_ids:
            if event_id not in event_ids:
                errors.append(f"{signal.signal_id}: missing event {event_id}")

    return tuple(errors)
