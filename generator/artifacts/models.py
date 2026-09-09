"""Investigator-visible artifact records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvestigatorArtifact:
    """A Python-identified artifact containing investigator-visible language."""

    artifact_id: str
    artifact_type: str
    content: str

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must be non-empty")
        if not self.artifact_type.strip():
            raise ValueError("artifact_type must be non-empty")
        if not self.content.strip():
            raise ValueError("content must be non-empty")
