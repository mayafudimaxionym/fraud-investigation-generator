from datetime import UTC, datetime

from generator.events.models import CanonicalEvent
from generator.validation.world import validate_world_references
from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
from generator.world.signals import CanonicalSignal


def test_world_validation_reports_missing_event_subject() -> None:
    world = CanonicalWorld(
        entities=(CanonicalEntity("account-001", "account"),),
        relationships=(),
        events=(
            CanonicalEvent(
                event_id="event-001",
                event_type="login",
                subject_entity_id="account-002",
                occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            ),
        ),
    )

    assert validate_world_references(world) == (
        "event-001: missing subject account-002",
    )


def test_world_validation_reports_missing_signal_event() -> None:
    world = CanonicalWorld(
        entities=(),
        relationships=(),
        events=(),
        signals=(
            CanonicalSignal(
                signal_id="signal-001",
                signal_type="temporal_cluster",
                supporting_event_ids=("event-001",),
            ),
        ),
    )

    assert validate_world_references(world) == (
        "signal-001: missing event event-001",
    )
