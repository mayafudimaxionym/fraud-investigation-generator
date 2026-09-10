"""Validation of references exposed in the investigator-visible case view."""

from __future__ import annotations

from collections.abc import Iterable

from generator.artifacts.manifest import InvestigatorViewManifest
from generator.artifacts.models import InvestigatorArtifact
from generator.world.model import CanonicalWorld


def validate_investigator_view_references(
    world: CanonicalWorld,
    investigator_view: InvestigatorViewManifest,
    artifacts: Iterable[InvestigatorArtifact] = (),
) -> tuple[str, ...]:
    """Return errors for visible world references absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in world.entities}
    event_ids = {event.event_id for event in world.events}
    relationship_ids = {
        relationship.relationship_id for relationship in world.relationships
    }
    artifact_ids = {artifact.artifact_id for artifact in artifacts}
    errors: list[str] = []

    for entity_id in investigator_view.visible_entity_ids:
        if entity_id not in entity_ids:
            errors.append(f"investigator_view: missing visible entity {entity_id}")
    for event_id in investigator_view.visible_event_ids:
        if event_id not in event_ids:
            errors.append(f"investigator_view: missing visible event {event_id}")
    for relationship_id in investigator_view.visible_relationship_ids:
        if relationship_id not in relationship_ids:
            errors.append(
                "investigator_view: missing visible relationship "
                f"{relationship_id}"
            )
    for artifact_id in investigator_view.artifact_ids:
        if artifact_id not in artifact_ids:
            errors.append(f"investigator_view: missing artifact {artifact_id}")

    return tuple(errors)
