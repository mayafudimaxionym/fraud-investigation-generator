from generator.artifacts.assembly import assemble_investigator_artifact
from generator.artifacts.contracts import (
    ArtifactAssertion,
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
)


def _request(mode: str = "factual") -> ArtifactGenerationRequest:
    return ArtifactGenerationRequest(
        "artifact-001",
        "analyst_note",
        "alternative_analyst_interpretation" if mode == "interpretive" else "analyst_observation_note",
        mode,
        (
            ArtifactAssertion(
                "assertion-event-001", "event", ("event-001", "entity-001"),
                "entity-001 logged in at 2026-01-01T09:00:00+00:00.",
            ),
        ),
        allowed_canonical_ids=("event-001", "entity-001"),
    )


def test_factual_assembly_uses_only_python_rendered_assertions() -> None:
    artifact = assemble_investigator_artifact(
        _request(), ArtifactGenerationResponse(("assertion-event-001",))
    )

    assert artifact.artifact_id == "artifact-001"
    assert artifact.artifact_type == "analyst_note"
    assert artifact.content == (
        "Analyst observation note\n"
        "entity-001 logged in at 2026-01-01T09:00:00+00:00."
    )


def test_interpretive_assembly_preserves_factual_spine_and_labels_interpretation() -> None:
    artifact = assemble_investigator_artifact(
        _request("interpretive"),
        ArtifactGenerationResponse(
            ("assertion-event-001",), "This may have been routine activity."
        ),
    )

    assert "entity-001 logged in at 2026-01-01T09:00:00+00:00." in artifact.content
    assert "Analyst interpretation (non-authoritative):" in artifact.content
    assert artifact.content.endswith("This may have been routine activity.")
