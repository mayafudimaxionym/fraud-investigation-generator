"""Canonical evidence signals derived from world relationships and events."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalSignal:
    """A discoverable signal with references to its supporting world evidence."""

    signal_id: str
    signal_type: str
    supporting_entity_ids: tuple[str, ...] = ()
    supporting_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("signal_id must be non-empty")
        if not self.signal_type.strip():
            raise ValueError("signal_type must be non-empty")
        if not self.supporting_entity_ids and not self.supporting_event_ids:
            raise ValueError("a signal must reference supporting evidence")
