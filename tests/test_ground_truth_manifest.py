from generator.world.truth import GroundTruthManifest


def test_ground_truth_manifest_rejects_duplicate_fraudulent_entities() -> None:
    try:
        GroundTruthManifest(
            campaign_ids=("campaign-001",),
            fraudulent_entity_ids=("account-001", "account-001"),
            fraudulent_event_ids=("event-001",),
            causal_signal_ids=("signal-001",),
            red_herring_ids=("red-herring-001",),
            correct_hypothesis="coordinated account takeover",
        )
    except ValueError as error:
        assert "fraudulent_entity_ids" in str(error)
    else:
        raise AssertionError("duplicate canonical identifiers must be rejected")
