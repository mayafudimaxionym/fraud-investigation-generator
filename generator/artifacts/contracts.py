"""Structured Python-to-model contracts for investigator-visible artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


ARTIFACT_MODES = ("factual", "interpretive")
ARTIFACT_TYPES = (
    "client_email",
    "customer_email",
    "customer_support_message",
    "support_message",
    "analyst_note",
    "operational_note",
)
ARTIFACT_PURPOSES = (
    "customer_reported_concern",
    "customer_facing_notification",
    "analyst_observation_note",
    "operational_observation_summary",
    "alternative_analyst_interpretation",
)


@dataclass(frozen=True)
class ArtifactAssertion:
    """One Python-rendered, investigator-visible factual atom."""

    assertion_id: str
    assertion_type: str
    evidence_ids: tuple[str, ...]
    rendered_fact: str

    def __post_init__(self) -> None:
        if not self.assertion_id.startswith("assertion-"):
            raise ValueError("assertion_id must use the Python-owned assertion- prefix")
        if not self.assertion_type.strip():
            raise ValueError("assertion_type must be non-empty")
        if not self.evidence_ids or any(not identifier.strip() for identifier in self.evidence_ids):
            raise ValueError("assertion evidence_ids must be non-empty")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("assertion evidence_ids must not contain duplicates")
        if not self.rendered_fact.strip():
            raise ValueError("rendered_fact must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "assertion_id": self.assertion_id,
            "assertion_type": self.assertion_type,
            "evidence_ids": list(self.evidence_ids),
            "rendered_fact": self.rendered_fact,
        }


@dataclass(frozen=True)
class ArtifactGenerationRequest:
    """Constrained input that permits only assertion selection and ordering."""

    artifact_id: str
    artifact_type: str
    purpose: str
    mode: str
    assertions: tuple[ArtifactAssertion, ...]
    ambiguity_instructions: tuple[str, ...] = ()
    allowed_canonical_ids: tuple[str, ...] = ()
    operational_framing: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must be non-empty")
        if self.artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"artifact_type must be one of {ARTIFACT_TYPES}")
        if self.purpose not in ARTIFACT_PURPOSES:
            raise ValueError(f"purpose must be one of {ARTIFACT_PURPOSES}")
        if self.mode not in ARTIFACT_MODES:
            raise ValueError(f"mode must be one of {ARTIFACT_MODES}")
        assertion_ids = tuple(assertion.assertion_id for assertion in self.assertions)
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError("assertions must not contain duplicate IDs")
        if len(self.allowed_canonical_ids) != len(set(self.allowed_canonical_ids)):
            raise ValueError("allowed_canonical_ids must not contain duplicates")
        if any(not identifier.strip() for identifier in self.allowed_canonical_ids):
            raise ValueError("allowed_canonical_ids must not contain blank values")
        assertion_evidence_ids = {
            identifier for assertion in self.assertions for identifier in assertion.evidence_ids
        }
        if not assertion_evidence_ids <= set(self.allowed_canonical_ids):
            raise ValueError("assertion evidence IDs must be permitted canonical IDs")

    def to_dict(self) -> dict[str, object]:
        """Return the structured payload used to create the model prompt."""
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "purpose": self.purpose,
            "mode": self.mode,
            "assertions": [assertion.to_dict() for assertion in self.assertions],
            "ambiguity_instructions": list(self.ambiguity_instructions),
            "allowed_canonical_ids": list(self.allowed_canonical_ids),
            "operational_framing": self.operational_framing,
        }


@dataclass(frozen=True)
class ArtifactGenerationResponse:
    """Model-selected assertions plus optional, non-authoritative interpretation."""

    selected_assertion_ids: tuple[str, ...]
    interpretation: str | None = None

    def __post_init__(self) -> None:
        if len(self.selected_assertion_ids) != len(set(self.selected_assertion_ids)):
            raise ValueError("selected_assertion_ids must not contain duplicates")
        if any(not identifier.strip() for identifier in self.selected_assertion_ids):
            raise ValueError("selected_assertion_ids must not contain blank values")
        if self.interpretation is not None and not self.interpretation.strip():
            raise ValueError("interpretation must be non-empty when supplied")


def parse_artifact_generation_response(
    payload: Mapping[str, object],
) -> ArtifactGenerationResponse:
    """Reject free factual prose and model-assigned canonical identity fields."""
    allowed_keys = ({"selected_assertion_ids"}, {"selected_assertion_ids", "interpretation"})
    if set(payload) not in allowed_keys:
        raise ValueError("artifact response must contain only selected_assertion_ids and optional interpretation")
    selected_assertion_ids = payload["selected_assertion_ids"]
    if not isinstance(selected_assertion_ids, list) or not all(
        isinstance(identifier, str) for identifier in selected_assertion_ids
    ):
        raise ValueError("selected_assertion_ids must be a list of strings")
    interpretation = payload.get("interpretation")
    if interpretation is not None and not isinstance(interpretation, str):
        raise ValueError("interpretation must be a string when supplied")
    return ArtifactGenerationResponse(
        tuple(dict.fromkeys(selected_assertion_ids)), interpretation
    )
