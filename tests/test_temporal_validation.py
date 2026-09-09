from datetime import UTC, datetime

from generator.events.models import CanonicalEvent
from generator.validation.temporal import validate_event_precedence


def test_event_precedence_reports_reversed_timestamps() -> None:
    login = CanonicalEvent(
        event_id="login-001",
        event_type="login",
        subject_entity_id="account-001",
        occurred_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
    )
    transfer = CanonicalEvent(
        event_id="transfer-001",
        event_type="transfer",
        subject_entity_id="account-001",
        occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )

    assert validate_event_precedence(login, transfer) == (
        "login-001 must occur before transfer-001",
    )
