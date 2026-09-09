"""Canonical relationships between generated world entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalRelationship:
    """A typed edge in the Python-owned canonical world."""

    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str

    def __post_init__(self) -> None:
        required_text = {
            "relationship_id": self.relationship_id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "relationship_type": self.relationship_type,
        }
        for field_name, value in required_text.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
