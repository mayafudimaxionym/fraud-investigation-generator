from generator.artifacts.assembly import assemble_investigator_artifact
from generator.artifacts.contracts import (
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
)


def test_artifact_assembly_uses_python_assigned_identity() -> None:
    artifact = assemble_investigator_artifact(
        ArtifactGenerationRequest(
            artifact_id="email-001",
            artifact_type="client_email",
            canonical_facts=(),
        ),
        ArtifactGenerationResponse(content="I do not remember authorizing this."),
    )

    assert artifact.artifact_id == "email-001"
    assert artifact.artifact_type == "client_email"
    assert artifact.content == "I do not remember authorizing this."
