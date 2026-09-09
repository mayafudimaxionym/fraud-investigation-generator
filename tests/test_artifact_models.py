from generator.artifacts.models import InvestigatorArtifact


def test_investigator_artifact_rejects_blank_content() -> None:
    try:
        InvestigatorArtifact(
            artifact_id="email-001",
            artifact_type="client_email",
            content=" ",
        )
    except ValueError as error:
        assert "content" in str(error)
    else:
        raise AssertionError("blank artifact content must be rejected")
