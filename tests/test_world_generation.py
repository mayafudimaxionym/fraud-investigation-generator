from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.world import validate_world_references
from generator.world.generation import build_minimal_world


def _blueprint(campaign_count: int = 2) -> CaseBlueprint:
    return CaseBlueprint(
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        correct_hypothesis="account takeover",
        campaign_count=campaign_count,
    )


def test_minimal_world_generation_is_reproducible() -> None:
    blueprint = _blueprint()

    assert build_minimal_world(blueprint, 427) == build_minimal_world(blueprint, 427)


def test_minimal_world_generation_respects_campaign_count_and_references() -> None:
    world = build_minimal_world(_blueprint(campaign_count=3), 427)

    assert len(world.campaigns) == 3
    assert validate_world_references(world) == ()


def test_minimal_world_generation_varies_with_seed() -> None:
    blueprint = _blueprint()

    assert build_minimal_world(blueprint, 427) != build_minimal_world(blueprint, 428)


def test_minimal_world_generation_creates_isolated_shared_device_campaigns() -> None:
    world = build_minimal_world(_blueprint(campaign_count=2), 427)
    entities_by_id = {entity.entity_id: entity for entity in world.entities}
    signals_by_id = {signal.signal_id: signal for signal in world.signals}
    device_ids = {
        entity.entity_id for entity in world.entities if entity.entity_type == "device"
    }

    assert len(world.entities) == 6
    assert len(world.relationships) == 4
    assert len(world.events) == 4
    assert len(world.signals) == 2
    assert len(device_ids) == 2

    campaign_device_ids: set[str] = set()
    for campaign in world.campaigns:
        account_ids = {
            entity_id
            for entity_id in campaign.fraudulent_entity_ids
            if entities_by_id[entity_id].entity_type == "account"
        }
        campaign_device_id = next(
            entity_id
            for entity_id in campaign.fraudulent_entity_ids
            if entities_by_id[entity_id].entity_type == "device"
        )
        signal = signals_by_id[campaign.causal_signal_ids[0]]
        relationships = [
            relationship
            for relationship in world.relationships
            if relationship.source_entity_id in account_ids
            and relationship.target_entity_id == campaign_device_id
            and relationship.relationship_type == "uses_device"
        ]

        campaign_device_ids.add(campaign_device_id)
        assert len(campaign.fraudulent_entity_ids) == 3
        assert len(campaign.fraudulent_event_ids) == 2
        assert len(campaign.causal_signal_ids) == 1
        assert len(account_ids) == 2
        assert len(relationships) == 2
        assert set(signal.supporting_entity_ids) == account_ids | {campaign_device_id}
        assert set(signal.supporting_event_ids) == set(campaign.fraudulent_event_ids)

    assert campaign_device_ids == device_ids
