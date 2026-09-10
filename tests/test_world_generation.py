from datetime import timedelta

from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.temporal import validate_event_precedence
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

    assert len(world.entities) == 9
    assert len(world.relationships) == 6
    assert len(world.events) == 12
    assert len(world.signals) == 3
    assert len(device_ids) == 3

    campaign_device_ids: set[str] = set()
    campaign_entity_ids: set[str] = set()
    campaign_event_ids: set[str] = set()
    campaign_signal_ids: set[str] = set()
    fraud_transfer_latencies: list[timedelta] = []
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
        campaign_events = [
            event
            for event in world.events
            if event.event_id in campaign.fraudulent_event_ids
        ]
        login_events = [event for event in campaign_events if event.event_type == "login"]
        transfer_events = [
            event for event in campaign_events if event.event_type == "transfer"
        ]
        relationships = [
            relationship
            for relationship in world.relationships
            if relationship.source_entity_id in account_ids
            and relationship.target_entity_id == campaign_device_id
            and relationship.relationship_type == "uses_device"
        ]

        campaign_device_ids.add(campaign_device_id)
        campaign_entity_ids.update(campaign.fraudulent_entity_ids)
        campaign_event_ids.update(campaign.fraudulent_event_ids)
        campaign_signal_ids.update(campaign.causal_signal_ids)
        assert len(campaign.fraudulent_entity_ids) == 3
        assert len(campaign.fraudulent_event_ids) == 4
        assert len(campaign.causal_signal_ids) == 1
        assert len(account_ids) == 2
        assert len(relationships) == 2
        assert signal.signal_type == "shared_device_login_transfer"
        assert len(login_events) == 2
        assert len(transfer_events) == 2
        login_spacing = login_events[1].occurred_at - login_events[0].occurred_at
        assert timedelta(seconds=1) <= login_spacing <= timedelta(seconds=15)
        assert set(signal.supporting_entity_ids) == account_ids | {campaign_device_id}
        assert set(signal.supporting_event_ids) == set(campaign.fraudulent_event_ids)

        for account_id in account_ids:
            login_event = next(
                event
                for event in login_events
                if event.subject_entity_id == account_id
            )
            transfer_event = next(
                event
                for event in transfer_events
                if event.subject_entity_id == account_id
            )
            assert validate_event_precedence(login_event, transfer_event) == ()
            fraud_transfer_latencies.append(
                transfer_event.occurred_at - login_event.occurred_at
            )

    assert fraud_transfer_latencies.count(timedelta(seconds=30)) == len(world.campaigns)
    assert sum(
        timedelta(minutes=8) <= latency <= timedelta(minutes=20)
        for latency in fraud_transfer_latencies
    ) == len(world.campaigns)

    lookalike_entity_ids = set(entities_by_id) - campaign_entity_ids
    lookalike_event_ids = {event.event_id for event in world.events} - campaign_event_ids
    lookalike_signal_ids = set(signals_by_id) - campaign_signal_ids
    lookalike_device_ids = {
        entity_id
        for entity_id in lookalike_entity_ids
        if entities_by_id[entity_id].entity_type == "device"
    }
    lookalike_account_ids = {
        entity_id
        for entity_id in lookalike_entity_ids
        if entities_by_id[entity_id].entity_type == "account"
    }
    lookalike_signal = signals_by_id[next(iter(lookalike_signal_ids))]
    lookalike_events = [
        event for event in world.events if event.event_id in lookalike_event_ids
    ]
    lookalike_logins = [
        event for event in lookalike_events if event.event_type == "login"
    ]
    lookalike_transfers = [
        event for event in lookalike_events if event.event_type == "transfer"
    ]
    lookalike_relationships = [
        relationship
        for relationship in world.relationships
        if relationship.source_entity_id in lookalike_account_ids
        and relationship.target_entity_id in lookalike_device_ids
        and relationship.relationship_type == "uses_device"
    ]

    assert campaign_device_ids.isdisjoint(lookalike_device_ids)
    assert len(lookalike_device_ids) == 1
    assert len(lookalike_account_ids) == 2
    assert len(lookalike_relationships) == 2
    assert len(lookalike_signal_ids) == 1
    assert lookalike_signal.signal_type == "shared_device_login_transfer"
    assert set(lookalike_signal.supporting_entity_ids) == (
        lookalike_account_ids | lookalike_device_ids
    )
    assert set(lookalike_signal.supporting_event_ids) == lookalike_event_ids
    assert len(lookalike_logins) == 2
    assert len(lookalike_transfers) == 2
    lookalike_login_spacing = (
        lookalike_logins[1].occurred_at - lookalike_logins[0].occurred_at
    )
    assert timedelta(seconds=1) <= lookalike_login_spacing <= timedelta(seconds=15)

    lookalike_transfer_latencies: list[timedelta] = []
    for account_id in lookalike_account_ids:
        login_event = next(
            event
            for event in lookalike_logins
            if event.subject_entity_id == account_id
        )
        transfer_event = next(
            event
            for event in lookalike_transfers
            if event.subject_entity_id == account_id
        )
        transfer_latency = transfer_event.occurred_at - login_event.occurred_at

        assert validate_event_precedence(login_event, transfer_event) == ()
        assert timedelta(minutes=8) <= transfer_latency <= timedelta(minutes=20)
        assert transfer_latency > timedelta(seconds=30)
        lookalike_transfer_latencies.append(transfer_latency)

    assert set(fraud_transfer_latencies) & set(lookalike_transfer_latencies)
