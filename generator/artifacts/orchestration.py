"""Deterministic Python orchestration for investigator-visible artifacts."""

from __future__ import annotations

from dataclasses import replace

from generator.artifacts.assembly import assemble_investigator_artifact
from generator.artifacts.context import (
    ArtifactTask,
    InvestigatorArtifactContext,
    build_artifact_generation_request,
)
from generator.artifacts.models import InvestigatorArtifact
from generator.artifacts.ollama import ArtifactModelClient
from generator.artifacts.manifest import InvestigatorViewManifest
from generator.case import CanonicalCase


def generate_artifacts(
    context: InvestigatorArtifactContext,
    tasks: tuple[ArtifactTask, ...],
    client: ArtifactModelClient,
) -> tuple[InvestigatorArtifact, ...]:
    """Generate Python-identified artifacts through a fakeable client."""
    return tuple(
        assemble_investigator_artifact(
            request := build_artifact_generation_request(context, task),
            client.generate(request),
        )
        for task in tasks
    )


def attach_investigator_artifacts(
    case: CanonicalCase, artifacts: tuple[InvestigatorArtifact, ...]
) -> CanonicalCase:
    """Return a new case with visible artifacts, preserving all canonical truth."""
    existing_ids = tuple(artifact.artifact_id for artifact in case.artifacts)
    new_ids = tuple(artifact.artifact_id for artifact in artifacts)
    if len(existing_ids + new_ids) != len(set(existing_ids + new_ids)):
        raise ValueError("attached artifacts must not duplicate IDs")
    investigator_view = InvestigatorViewManifest(
        visible_entity_ids=case.investigator_view.visible_entity_ids,
        visible_event_ids=case.investigator_view.visible_event_ids,
        artifact_ids=case.investigator_view.artifact_ids + new_ids,
        visible_relationship_ids=case.investigator_view.visible_relationship_ids,
    )
    return replace(
        case,
        investigator_view=investigator_view,
        artifacts=case.artifacts + artifacts,
    )
