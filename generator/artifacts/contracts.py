"""Structured Python-to-model contracts for investigator-visible artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactFact:
    """A prevalidated canonical value supplied by Python to an artifact prompt."""

    key: str
    value: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("fact key must be non-empty")

    def to_dict(self) -> dict[str, str]:
        """Return the fact in a JSON-compatible form."""
        return {"key": self.key, "value": self.value}


@dataclass(frozen=True)
class ArtifactGenerationRequest:
    """Constrained input for model-written, investigator-visible language."""

    artifact_id: str
    artifact_type: str
    canonical_facts: tuple[ArtifactFact, ...]
    ambiguity_instructions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must be non-empty")
        if not self.artifact_type.strip():
            raise ValueError("artifact_type must be non-empty")
        fact_keys = tuple(fact.key for fact in self.canonical_facts)
        if len(fact_keys) != len(set(fact_keys)):
            raise ValueError("canonical_facts must not contain duplicate keys")

    def to_dict(self) -> dict[str, object]:
        """Return the constrained request payload for a model interface."""
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "canonical_facts": [fact.to_dict() for fact in self.canonical_facts],
            "ambiguity_instructions": list(self.ambiguity_instructions),
        }


@dataclass(frozen=True)
class ArtifactGenerationResponse:
    """Model-written language, without any model-assigned canonical identifier."""

    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("content must be non-empty")

    def to_dict(self) -> dict[str, str]:
        """Return the model response payload for Python-side validation."""
        return {"content": self.content}
