from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
from generator.world.signals import CanonicalSignal


def test_canonical_world_rejects_duplicate_entity_ids() -> None:
    try:
        CanonicalWorld(
            entities=(
                CanonicalEntity("account-001", "account"),
                CanonicalEntity("account-001", "account"),
            ),
            relationships=(),
            events=(),
        )
    except ValueError as error:
        assert "entities" in str(error)
    else:
        raise AssertionError("duplicate canonical entity IDs must be rejected")


def test_canonical_world_rejects_duplicate_signal_ids() -> None:
    signal = CanonicalSignal(
        signal_id="signal-001",
        signal_type="temporal_cluster",
        supporting_entity_ids=("account-001",),
    )

    try:
        CanonicalWorld(entities=(), relationships=(), events=(), signals=(signal, signal))
    except ValueError as error:
        assert "signals" in str(error)
    else:
        raise AssertionError("duplicate canonical signal IDs must be rejected")
