"""Canonical temporal events in the generated world."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalEvent:
    """A timestamped event owned by the deterministic canonical world."""

    event_id: str
    event_type: str
    subject_entity_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        required_text = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "subject_entity_id": self.subject_entity_id,
        }
        for field_name, value in required_text.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
