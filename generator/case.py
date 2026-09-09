"""Aggregate contract for one synthetic fraud-investigation case."""

from __future__ import annotations

from dataclasses import dataclass

from generator.artifacts.manifest import InvestigatorViewManifest
from generator.artifacts.models import InvestigatorArtifact
from generator.metadata import GenerationMetadata
from generator.scenario.spec import ScenarioSpec
from generator.world.model import CanonicalWorld
from generator.world.truth import GroundTruthManifest


@dataclass(frozen=True)
class CanonicalCase:
    """One Python-owned case and its separate investigator-visible view."""

    case_id: str
    metadata: GenerationMetadata
    scenario: ScenarioSpec
    world: CanonicalWorld
    ground_truth: GroundTruthManifest
    investigator_view: InvestigatorViewManifest
    artifacts: tuple[InvestigatorArtifact, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        artifact_ids = tuple(artifact.artifact_id for artifact in self.artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifacts must not contain duplicate IDs")
