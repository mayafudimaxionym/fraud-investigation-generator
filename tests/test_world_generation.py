from datetime import timedelta

from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.temporal import validate_event_precedence
from generator.validation.world import validate_world_references
from generator.world.generation import build_minimal_world
from generator.world.model import CanonicalWorld


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


def test_generated_record_ids_are_opaque_to_private_interpretation() -> None:
    world = build_minimal_world(_blueprint(), 427)
    private_labels = (
        "fraud",
        "lookalike",
        "benign",
        "red_herring",
        "causal",
        "hypothesis",
        "campaign",
    )

    for prefix, identifiers in (
        ("entity-", (entity.entity_id for entity in world.entities)),
        ("event-", (event.event_id for event in world.events)),
        (
            "relationship-",
            (relationship.relationship_id for relationship in world.relationships),
        ),
        ("signal-", (signal.signal_id for signal in world.signals)),
    ):
        for identifier in identifiers:
            assert identifier.startswith(prefix)
            assert not any(label in identifier for label in private_labels)


def test_population_contains_background_overlap_and_campaign_coordination() -> None:
    world = build_minimal_world(_blueprint(campaign_count=2), 427)
    entities_by_id = {entity.entity_id: entity for entity in world.entities}
    fraud_account_ids = {
        entity_id
        for campaign in world.campaigns
        for entity_id in campaign.fraudulent_entity_ids
        if entities_by_id[entity_id].entity_type == "account"
    }
    legitimate_account_ids = {
        entity.entity_id
        for entity in world.entities
        if entity.entity_type == "account" and entity.entity_id not in fraud_account_ids
    }
    causal_signal_ids = {
        signal_id
        for campaign in world.campaigns
        for signal_id in campaign.causal_signal_ids
    }

    assert validate_world_references(world) == ()
    assert 40 <= len(
        [entity for entity in world.entities if entity.entity_type == "account"]
    ) <= 60
    assert len(world.events) >= 180
    assert len(world.campaigns) == 2
    assert any(
        signal.is_red_herring and signal.signal_id not in causal_signal_ids
        for signal in world.signals
    )
    assert any(
        not signal.is_red_herring and signal.signal_id not in causal_signal_ids
        for signal in world.signals
    )

    campaign_network_ids = [
        {
            entity_id
            for entity_id in campaign.fraudulent_entity_ids
            if entities_by_id[entity_id].entity_type == "network"
        }
        for campaign in world.campaigns
    ]
    assert all(network_ids for network_ids in campaign_network_ids)
    shared_network_ids = set.intersection(*campaign_network_ids)
    assert shared_network_ids
    assert any(
        relationship.relationship_type == "uses_network"
        and relationship.target_entity_id in shared_network_ids
        and relationship.source_entity_id not in {
            entity_id
            for campaign in world.campaigns
            for entity_id in campaign.fraudulent_entity_ids
            if entities_by_id[entity_id].entity_type == "device"
        }
        for relationship in world.relationships
    )

    for campaign in world.campaigns:
        campaign_account_ids = {
            entity_id
            for entity_id in campaign.fraudulent_entity_ids
            if entities_by_id[entity_id].entity_type == "account"
        }
        campaign_event_ids = set(campaign.fraudulent_event_ids)
        assert len(campaign_event_ids) == 4
        assert all(
            len(
                [event for event in world.events if event.subject_entity_id == account_id]
            ) > 2
            for account_id in campaign_account_ids
        )

    assert _has_shared_target(world, fraud_account_ids, "uses_device")
    assert _has_shared_target(world, legitimate_account_ids, "uses_device")
    assert _has_shared_target(world, fraud_account_ids, "transfers_to")
    assert _has_shared_target(world, legitimate_account_ids, "transfers_to")
    assert _has_rapid_login_transfer(world, fraud_account_ids)
    assert _has_rapid_login_transfer(world, legitimate_account_ids)


def _has_shared_target(
    world: CanonicalWorld, account_ids: set[str], relationship_type: str
) -> bool:
    sources_by_target: dict[str, set[str]] = {}
    for relationship in world.relationships:
        if (
            relationship.relationship_type == relationship_type
            and relationship.source_entity_id in account_ids
        ):
            sources_by_target.setdefault(relationship.target_entity_id, set()).add(
                relationship.source_entity_id
            )
    return any(len(source_ids) >= 2 for source_ids in sources_by_target.values())


def _has_rapid_login_transfer(world: CanonicalWorld, account_ids: set[str]) -> bool:
    events_by_account = {}
    for event in world.events:
        if event.subject_entity_id in account_ids:
            events_by_account.setdefault(event.subject_entity_id, []).append(event)
    for account_events in events_by_account.values():
        ordered_events = sorted(account_events, key=lambda event: event.occurred_at)
        for login_event, transfer_event in zip(ordered_events, ordered_events[1:]):
            if (
                login_event.event_type == "login"
                and transfer_event.event_type == "transfer"
                and timedelta(0)
                < transfer_event.occurred_at - login_event.occurred_at
                <= timedelta(seconds=60)
            ):
                assert validate_event_precedence(login_event, transfer_event) == ()
                return True
    return False
