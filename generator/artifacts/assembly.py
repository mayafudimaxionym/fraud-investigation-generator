"""Python-side assembly of assertion-selected investigator artifacts."""

from __future__ import annotations

from generator.artifacts.contracts import (
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
)
from generator.artifacts.models import InvestigatorArtifact
from generator.artifacts.validation import require_valid_artifact_response


def assemble_investigator_artifact(
    request: ArtifactGenerationRequest, response: ArtifactGenerationResponse
) -> InvestigatorArtifact:
    """Render Python-owned factual assertions and optional interpretation."""
    require_valid_artifact_response(request, response)
    assertions = {assertion.assertion_id: assertion for assertion in request.assertions}
    factual_spine = "\n".join(
        assertions[assertion_id].rendered_fact
        for assertion_id in response.selected_assertion_ids
    )
    content = _purpose_heading(request.purpose) + "\n" + factual_spine
    if response.interpretation is not None:
        content += (
            "\n\nAnalyst interpretation (non-authoritative):\n"
            + response.interpretation
        )
    return InvestigatorArtifact(
        artifact_id=request.artifact_id,
        artifact_type=request.artifact_type,
        content=content,
    )


def _purpose_heading(purpose: str) -> str:
    return {
        "customer_reported_concern": "Customer-reported concern",
        "customer_facing_notification": "Customer-facing notification",
        "analyst_observation_note": "Analyst observation note",
        "operational_observation_summary": "Operational observation summary",
        "alternative_analyst_interpretation": "Factual observations",
    }[purpose]
