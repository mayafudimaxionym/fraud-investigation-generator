from generator.world.campaigns import FraudCampaign


def test_campaign_allows_no_explicit_actor_entity() -> None:
    campaign = FraudCampaign(
        campaign_id="campaign-001",
        mechanism="account takeover",
        actor_entity_ids=(),
        fraudulent_entity_ids=("account-001",),
        fraudulent_event_ids=(),
        causal_signal_ids=(),
    )

    assert campaign.actor_entity_ids == ()


def test_campaign_requires_fraudulent_membership() -> None:
    try:
        FraudCampaign(
            campaign_id="campaign-001",
            mechanism="account takeover",
            actor_entity_ids=(),
            fraudulent_entity_ids=(),
            fraudulent_event_ids=(),
            causal_signal_ids=(),
        )
    except ValueError as error:
        assert "fraudulent entity or fraudulent event" in str(error)
    else:
        raise AssertionError("campaigns without fraudulent membership must be rejected")
