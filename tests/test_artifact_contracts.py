from generator.artifacts.contracts import (
    ArtifactFact,
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
)


def test_artifact_request_rejects_duplicate_fact_keys() -> None:
    try:
        ArtifactGenerationRequest(
            artifact_id="email-001",
            artifact_type="client_email",
            canonical_facts=(
                ArtifactFact("account_id", "account-001"),
                ArtifactFact("account_id", "account-002"),
            ),
        )
    except ValueError as error:
        assert "canonical_facts" in str(error)
    else:
        raise AssertionError("duplicate supplied facts must be rejected")


def test_artifact_response_rejects_blank_content() -> None:
    try:
        ArtifactGenerationResponse(content=" ")
    except ValueError as error:
        assert "content" in str(error)
    else:
        raise AssertionError("blank model responses must be rejected")


def test_artifact_request_serializes_to_json_compatible_payload() -> None:
    request = ArtifactGenerationRequest(
        artifact_id="email-001",
        artifact_type="client_email",
        canonical_facts=(ArtifactFact("account_id", "account-001"),),
        ambiguity_instructions=("Use an incomplete recollection.",),
    )

    assert request.to_dict() == {
        "artifact_id": "email-001",
        "artifact_type": "client_email",
        "canonical_facts": [{"key": "account_id", "value": "account-001"}],
        "ambiguity_instructions": ["Use an incomplete recollection."],
    }
