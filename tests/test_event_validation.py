from datetime import UTC, datetime

from generator.events.models import CanonicalEvent
from generator.validation.events import validate_event_references
from generator.world.entities import CanonicalEntity


def test_event_validation_reports_missing_subject_entity() -> None:
    errors = validate_event_references(
        entities=(CanonicalEntity("account-001", "account"),),
        events=(
            CanonicalEvent(
                event_id="event-001",
                event_type="login",
                subject_entity_id="account-002",
                occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            ),
        ),
    )

    assert errors == ("event-001: missing subject account-002",)


def test_event_validation_reports_missing_target_entity() -> None:
    errors = validate_event_references(
        entities=(CanonicalEntity("account-001", "account"),),
        events=(
            CanonicalEvent(
                event_id="event-001",
                event_type="transfer",
                subject_entity_id="account-001",
                occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
                target_entity_id="beneficiary-001",
            ),
        ),
    )

    assert errors == ("event-001: missing target beneficiary-001",)
