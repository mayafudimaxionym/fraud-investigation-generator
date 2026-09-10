from generator.validation.campaigns import validate_campaign_references
from generator.world.campaigns import FraudCampaign
from generator.world.model import CanonicalWorld


def test_campaign_validation_reports_missing_fraudulent_entity() -> None:
    world = CanonicalWorld(
        entities=(),
        relationships=(),
        events=(),
        campaigns=(
            FraudCampaign(
                campaign_id="campaign-001",
                mechanism="account takeover",
                actor_entity_ids=(),
                fraudulent_entity_ids=("account-001",),
                fraudulent_event_ids=(),
                causal_signal_ids=(),
            ),
        ),
    )

    assert validate_campaign_references(world) == (
        "campaign-001: missing fraudulent entity account-001",
    )
