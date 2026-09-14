from generator.world.signals import CanonicalSignal


def test_signal_requires_supporting_evidence() -> None:
    try:
        CanonicalSignal(signal_id="signal-001", signal_type="temporal_cluster")
    except ValueError as error:
        assert "supporting evidence" in str(error)
    else:
        raise AssertionError("signals without evidence must be rejected")


def test_signal_rejects_non_boolean_red_herring_marker() -> None:
    try:
        CanonicalSignal(
            signal_id="signal-001",
            signal_type="temporal_cluster",
            supporting_entity_ids=("account-001",),
            is_red_herring="yes",
        )
    except ValueError as error:
        assert "is_red_herring" in str(error)
    else:
        raise AssertionError("signal red-herring markers must be boolean")
