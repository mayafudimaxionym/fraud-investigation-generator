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


def test_event_rejects_blank_target_entity_id() -> None:
    try:
        CanonicalEvent(
            event_id="event-001",
            event_type="transfer",
            subject_entity_id="account-001",
            occurred_at=datetime(2026, 1, 1, 9, 0),
            target_entity_id=" ",
        )
    except ValueError as error:
        assert str(error) == "target_entity_id must be non-empty when provided"
    else:
        raise AssertionError("blank event target IDs must be rejected")
