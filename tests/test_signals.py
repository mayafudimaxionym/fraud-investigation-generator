from generator.world.signals import CanonicalSignal


def test_signal_requires_supporting_evidence() -> None:
    try:
        CanonicalSignal(signal_id="signal-001", signal_type="temporal_cluster")
    except ValueError as error:
        assert "supporting evidence" in str(error)
    else:
        raise AssertionError("signals without evidence must be rejected")
