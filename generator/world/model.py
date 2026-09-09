"""Aggregate canonical world contract for one generated case."""

from __future__ import annotations

from dataclasses import dataclass

from generator.events.models import CanonicalEvent
from generator.world.entities import CanonicalEntity
from generator.world.relationships import CanonicalRelationship
from generator.world.signals import CanonicalSignal


@dataclass(frozen=True)
class CanonicalWorld:
    """Python-owned entities, relationships, and events for a single case."""

    entities: tuple[CanonicalEntity, ...]
    relationships: tuple[CanonicalRelationship, ...]
    events: tuple[CanonicalEvent, ...]
    signals: tuple[CanonicalSignal, ...] = ()

    def __post_init__(self) -> None:
        collections = {
            "entities": tuple(entity.entity_id for entity in self.entities),
            "relationships": tuple(
                relationship.relationship_id for relationship in self.relationships
            ),
            "events": tuple(event.event_id for event in self.events),
            "signals": tuple(signal.signal_id for signal in self.signals),
        }
        for collection_name, identifiers in collections.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{collection_name} must not contain duplicate IDs")
