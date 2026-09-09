from generator.validation.signals import validate_signal_references
from generator.world.entities import CanonicalEntity
from generator.world.signals import CanonicalSignal


def test_signal_validation_reports_missing_supporting_entity() -> None:
    errors = validate_signal_references(
        entities=(CanonicalEntity("account-001", "account"),),
        events=(),
        signals=(
            CanonicalSignal(
                signal_id="signal-001",
                signal_type="shared_device",
                supporting_entity_ids=("device-001",),
            ),
        ),
    )

    assert errors == ("signal-001: missing entity device-001",)
