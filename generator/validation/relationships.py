"""Validation of canonical relationship references."""

from __future__ import annotations

from collections.abc import Iterable

from generator.world.entities import CanonicalEntity
from generator.world.relationships import CanonicalRelationship


def validate_relationship_references(
    entities: Iterable[CanonicalEntity],
    relationships: Iterable[CanonicalRelationship],
) -> tuple[str, ...]:
    """Return errors for relationship endpoints absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in entities}
    errors: list[str] = []

    for relationship in relationships:
        if relationship.source_entity_id not in entity_ids:
            errors.append(
                f"{relationship.relationship_id}: missing source "
                f"{relationship.source_entity_id}"
            )
        if relationship.target_entity_id not in entity_ids:
            errors.append(
                f"{relationship.relationship_id}: missing target "
                f"{relationship.target_entity_id}"
            )

    return tuple(errors)
