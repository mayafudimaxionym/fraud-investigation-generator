from datetime import datetime

from generator.events.models import CanonicalEvent


def test_event_rejects_naive_timestamp() -> None:
    try:
        CanonicalEvent(
            event_id="event-001",
            event_type="login",
            subject_entity_id="account-001",
            occurred_at=datetime(2026, 1, 1, 9, 0),
        )
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("naive event timestamps must be rejected")
