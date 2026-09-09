"""Validation of required temporal ordering between canonical events."""

from __future__ import annotations

from generator.events.models import CanonicalEvent


def validate_event_precedence(
    earlier_event: CanonicalEvent, later_event: CanonicalEvent
) -> tuple[str, ...]:
    """Return an error unless ``earlier_event`` occurs strictly first."""
    if earlier_event.occurred_at >= later_event.occurred_at:
        return (
            f"{earlier_event.event_id} must occur before {later_event.event_id}",
        )
    return ()
