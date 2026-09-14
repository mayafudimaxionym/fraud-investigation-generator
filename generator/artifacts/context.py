"""Investigator-only assertions and requests for artifact generation."""

from __future__ import annotations

from dataclasses import dataclass

from generator.artifacts.contracts import ArtifactAssertion, ArtifactGenerationRequest
from generator.artifacts.manifest import InvestigatorViewManifest
from generator.events.models import CanonicalEvent
from generator.scenario.spec import ScenarioSpec
from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
from generator.world.relationships import CanonicalRelationship

_PURPOSE_ASSERTION_TYPES = {
    "customer_reported_concern": frozenset({"entity", "event"}),
    "customer_facing_notification": frozenset({"entity", "event"}),
    "analyst_observation_note": frozenset({"entity", "relationship", "event"}),
    "operational_observation_summary": frozenset({"relationship", "event"}),
    "alternative_analyst_interpretation": frozenset({"entity", "relationship", "event"}),
}


@dataclass(frozen=True)
class InvestigatorArtifactContext:
    """Visible records and Python-rendered assertions, with no truth-side objects."""

    domain: str
    scale: str
    assertions: tuple[ArtifactAssertion, ...]
    operational_framing: str = ""

    @property
    def allowed_canonical_ids(self) -> tuple[str, ...]:
        return _stable_unique(
            tuple(
                identifier
                for assertion in self.assertions
                for identifier in assertion.evidence_ids
            )
        )


@dataclass(frozen=True)
class ArtifactTask:
    """Python-owned identity, purpose, and eligible factual assertions."""

    artifact_id: str
    artifact_type: str
    purpose: str
    mode: str
    assertion_ids: tuple[str, ...]
    ambiguity_instructions: tuple[str, ...] = ()
    operational_framing: str = ""


def build_investigator_artifact_context(
    scenario: ScenarioSpec,
    world: CanonicalWorld,
    investigator_view: InvestigatorViewManifest,
    *,
    operational_framing: str = "",
) -> InvestigatorArtifactContext:
    """Derive factual atoms only from records visible to an investigator."""
    entities = {entity.entity_id: entity for entity in world.entities}
    relationships = {
        relationship.relationship_id: relationship
        for relationship in world.relationships
    }
    events = {event.event_id: event for event in world.events}
    visible_entities = tuple(
        entities[identifier] for identifier in investigator_view.visible_entity_ids
    )
    visible_relationships = tuple(
        relationships[identifier]
        for identifier in investigator_view.visible_relationship_ids
    )
    visible_events = tuple(
        events[identifier] for identifier in investigator_view.visible_event_ids
    )
    return InvestigatorArtifactContext(
        domain=scenario.domain,
        scale=scenario.scale,
        assertions=tuple(
            _entity_assertion(entity)
            for entity in visible_entities
        )
        + tuple(
            _relationship_assertion(relationship)
            for relationship in visible_relationships
        )
        + tuple(_event_assertion(event) for event in visible_events),
        operational_framing=operational_framing,
    )


def build_artifact_generation_request(
    context: InvestigatorArtifactContext, task: ArtifactTask
) -> ArtifactGenerationRequest:
    """Build an assertion-only request for one Python-owned artifact task."""
    assertions = {assertion.assertion_id: assertion for assertion in context.assertions}
    unknown_ids = set(task.assertion_ids) - set(assertions)
    if unknown_ids:
        raise ValueError(f"artifact task references unavailable assertion IDs: {sorted(unknown_ids)}")
    selected_assertions = tuple(assertions[identifier] for identifier in task.assertion_ids)
    permitted_types = _PURPOSE_ASSERTION_TYPES.get(task.purpose)
    if permitted_types is None:
        raise ValueError(f"artifact task has unknown purpose {task.purpose}")
    if any(assertion.assertion_type not in permitted_types for assertion in selected_assertions):
        raise ValueError("artifact task assertions are not eligible for its purpose")
    if task.purpose == "alternative_analyst_interpretation" and task.mode != "interpretive":
        raise ValueError("alternative analyst interpretation must use interpretive mode")
    if task.mode == "interpretive" and task.purpose != "alternative_analyst_interpretation":
        raise ValueError("interpretive mode is reserved for alternative analyst interpretation")
    return ArtifactGenerationRequest(
        artifact_id=task.artifact_id,
        artifact_type=task.artifact_type,
        purpose=task.purpose,
        mode=task.mode,
        assertions=selected_assertions,
        ambiguity_instructions=task.ambiguity_instructions,
        allowed_canonical_ids=_stable_unique(
            tuple(
                identifier
                for assertion in selected_assertions
                for identifier in assertion.evidence_ids
            )
        ),
        operational_framing=task.operational_framing or context.operational_framing,
    )


def _entity_assertion(entity: CanonicalEntity) -> ArtifactAssertion:
    return ArtifactAssertion(
        assertion_id=f"assertion-{entity.entity_id}",
        assertion_type="entity",
        evidence_ids=(entity.entity_id,),
        rendered_fact=f"{entity.entity_id} is a {entity.entity_type}.",
    )


def _relationship_assertion(relationship: CanonicalRelationship) -> ArtifactAssertion:
    verb = {
        "uses_device": "uses",
        "uses_network": "uses",
        "transfers_to": "transfers to",
    }.get(relationship.relationship_type, relationship.relationship_type)
    return ArtifactAssertion(
        assertion_id=f"assertion-{relationship.relationship_id}",
        assertion_type="relationship",
        evidence_ids=(
            relationship.relationship_id,
            relationship.source_entity_id,
            relationship.target_entity_id,
        ),
        rendered_fact=(
            f"{relationship.source_entity_id} {verb} "
            f"{relationship.target_entity_id}."
        ),
    )


def _event_assertion(event: CanonicalEvent) -> ArtifactAssertion:
    evidence_ids = (event.event_id, event.subject_entity_id) + (
        (event.target_entity_id,) if event.target_entity_id is not None else ()
    )
    if event.event_type == "login":
        rendered_fact = f"{event.subject_entity_id} logged in at {event.occurred_at.isoformat()}."
    elif event.event_type == "transfer" and event.target_entity_id is not None:
        rendered_fact = (
            f"{event.subject_entity_id} transferred to {event.target_entity_id} "
            f"at {event.occurred_at.isoformat()}."
        )
    else:
        rendered_fact = (
            f"{event.subject_entity_id} had {event.event_type} at "
            f"{event.occurred_at.isoformat()}."
        )
    return ArtifactAssertion(
        assertion_id=f"assertion-{event.event_id}",
        assertion_type="event",
        evidence_ids=evidence_ids,
        rendered_fact=rendered_fact,
    )


def _stable_unique(identifiers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(identifiers))
