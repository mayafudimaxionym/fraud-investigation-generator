"""Canonical entities in the Python-owned world."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalEntity:
    """An entity with a stable identifier and a domain-specific type."""

    entity_id: str
    entity_type: str

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("entity_id must be non-empty")
        if not self.entity_type.strip():
            raise ValueError("entity_type must be non-empty")
