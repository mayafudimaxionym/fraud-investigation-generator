"""Python-side assembly of constrained model language into visible artifacts."""

from __future__ import annotations

from generator.artifacts.contracts import (
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
)
from generator.artifacts.models import InvestigatorArtifact


def assemble_investigator_artifact(
    request: ArtifactGenerationRequest, response: ArtifactGenerationResponse
) -> InvestigatorArtifact:
    """Attach model language to the Python-assigned artifact identity."""
    return InvestigatorArtifact(
        artifact_id=request.artifact_id,
        artifact_type=request.artifact_type,
        content=response.content,
    )
