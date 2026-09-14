from generator.artifacts.contracts import (
    ArtifactAssertion,
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
    parse_artifact_generation_response,
)


def _assertion() -> ArtifactAssertion:
    return ArtifactAssertion(
        "assertion-event-001",
        "event",
        ("event-001", "entity-001"),
        "entity-001 logged in at 2026-01-01T09:00:00+00:00.",
    )


def _request() -> ArtifactGenerationRequest:
    return ArtifactGenerationRequest(
        artifact_id="artifact-001",
        artifact_type="analyst_note",
        purpose="analyst_observation_note",
        mode="factual",
        assertions=(_assertion(),),
        allowed_canonical_ids=("event-001", "entity-001"),
    )


def test_assertion_rejects_blank_or_duplicate_evidence_ids() -> None:
    try:
        ArtifactAssertion("assertion-001", "event", ("event-001", "event-001"), "Fact.")
    except ValueError as error:
        assert "evidence_ids" in str(error)
    else:
        raise AssertionError("duplicate assertion evidence must be rejected")


def test_request_rejects_assertion_evidence_outside_its_allowed_context() -> None:
    try:
        ArtifactGenerationRequest(
            "artifact-001", "analyst_note", "analyst_observation_note", "factual",
            (_assertion(),), allowed_canonical_ids=("event-001",),
        )
    except ValueError as error:
        assert "evidence IDs" in str(error)
    else:
        raise AssertionError("assertion evidence must remain within request context")


def test_artifact_request_rejects_duplicate_assertion_ids() -> None:
    assertion = _assertion()
    try:
        ArtifactGenerationRequest(
            "artifact-001", "analyst_note", "analyst_observation_note", "factual",
            (assertion, assertion),
        )
    except ValueError as error:
        assert "assertions" in str(error)
    else:
        raise AssertionError("duplicate assertions must be rejected")


def test_artifact_request_serializes_structured_assertions() -> None:
    assert _request().to_dict() == {
        "artifact_id": "artifact-001",
        "artifact_type": "analyst_note",
        "purpose": "analyst_observation_note",
        "mode": "factual",
        "assertions": [{
            "assertion_id": "assertion-event-001",
            "assertion_type": "event",
            "evidence_ids": ["event-001", "entity-001"],
            "rendered_fact": "entity-001 logged in at 2026-01-01T09:00:00+00:00.",
        }],
        "ambiguity_instructions": [],
        "allowed_canonical_ids": ["event-001", "entity-001"],
        "operational_framing": "",
    }


def test_artifact_response_parser_rejects_model_authored_content() -> None:
    try:
        parse_artifact_generation_response(
            {"selected_assertion_ids": [], "content": "Invented prose."}
        )
    except ValueError as error:
        assert "only selected_assertion_ids" in str(error)
    else:
        raise AssertionError("model responses must not author final content")


def test_artifact_response_parser_accepts_selection_and_interpretation() -> None:
    response = parse_artifact_generation_response(
        {
            "selected_assertion_ids": ["assertion-event-001"],
            "interpretation": "This may be routine activity.",
        }
    )

    assert response == ArtifactGenerationResponse(
        ("assertion-event-001",), "This may be routine activity."
    )


def test_artifact_response_parser_stably_deduplicates_selected_assertion_ids() -> None:
    response = parse_artifact_generation_response(
        {
            "selected_assertion_ids": [
                "assertion-2",
                "assertion-1",
                "assertion-2",
                "assertion-3",
                "assertion-1",
            ]
        }
    )

    assert response.selected_assertion_ids == (
        "assertion-2",
        "assertion-1",
        "assertion-3",
    )
