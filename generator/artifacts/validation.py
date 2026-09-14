"""Python-side safety checks for assertion-based artifact responses."""

from __future__ import annotations

import re

from generator.artifacts.contracts import ArtifactGenerationRequest, ArtifactGenerationResponse

_CANONICAL_ID_PATTERN = re.compile(
    r"\b(?:entity|event|relationship|signal|campaign)-[A-Za-z0-9-]+\b"
)


def validate_artifact_response(
    request: ArtifactGenerationRequest, response: ArtifactGenerationResponse
) -> tuple[str, ...]:
    """Return deterministic errors for assertion and interpretation boundaries."""
    errors: list[str] = []
    allowed_assertion_ids = {assertion.assertion_id for assertion in request.assertions}
    for assertion_id in response.selected_assertion_ids:
        if assertion_id not in allowed_assertion_ids:
            errors.append(f"artifact response selects unavailable assertion ID {assertion_id}")
    if request.mode == "factual" and response.interpretation is not None:
        errors.append("factual artifact response must not contain interpretation")
    if response.interpretation is not None:
        for identifier in _disallowed_canonical_ids(request, response.interpretation):
            errors.append(
                "artifact interpretation references unavailable canonical ID "
                f"{identifier}"
            )
    return tuple(errors)


def require_valid_artifact_response(
    request: ArtifactGenerationRequest, response: ArtifactGenerationResponse
) -> None:
    """Raise a diagnostic error when a model response crosses its boundary."""
    errors = validate_artifact_response(request, response)
    if errors:
        permitted_assertions = ", ".join(
            assertion.assertion_id for assertion in request.assertions
        ) or "(none)"
        permitted_ids = ", ".join(request.allowed_canonical_ids) or "(none)"
        raise ValueError(
            "artifact response rejected "
            f"artifact_id={request.artifact_id} artifact_type={request.artifact_type}; "
            f"permitted assertion IDs=[{permitted_assertions}]; "
            f"permitted canonical IDs=[{permitted_ids}]; "
            f"errors=[{'; '.join(errors)}]"
        )


def _disallowed_canonical_ids(
    request: ArtifactGenerationRequest, text: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(_CANONICAL_ID_PATTERN.findall(text))
            - set(request.allowed_canonical_ids)
        )
    )
