from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.ground_truth import (
    validate_ground_truth_hypothesis,
    validate_ground_truth_references,
)
from generator.world.generation import (
    build_ground_truth_manifest,
    build_minimal_world,
)


def _blueprint() -> CaseBlueprint:
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
        campaign_count=2,
    )


def test_ground_truth_manifest_generation_is_deterministic_and_valid() -> None:
    blueprint = _blueprint()
    world = build_minimal_world(blueprint, 427)
    equivalent_world = build_minimal_world(blueprint, 427)

    manifest = build_ground_truth_manifest(blueprint, world)

    assert manifest == build_ground_truth_manifest(blueprint, equivalent_world)
    assert validate_ground_truth_hypothesis(blueprint.scenario, manifest) == ()
    assert validate_ground_truth_references(world, manifest) == ()


def test_ground_truth_manifest_generation_covers_campaign_truth_and_red_herring() -> None:
    blueprint = _blueprint()
    world = build_minimal_world(blueprint, 427)

    manifest = build_ground_truth_manifest(blueprint, world)
    expected_causal_signal_ids = _stable_unique(
        signal_id
        for campaign in world.campaigns
        for signal_id in campaign.causal_signal_ids
    )
    expected_entity_ids = _stable_unique(
        entity_id
        for campaign in world.campaigns
        for entity_id in campaign.fraudulent_entity_ids
    )
    expected_event_ids = _stable_unique(
        event_id
        for campaign in world.campaigns
        for event_id in campaign.fraudulent_event_ids
    )
    lookalike_signal = next(
        signal
        for signal in world.signals
        if signal.is_red_herring
    )

    assert manifest.campaign_ids == tuple(
        campaign.campaign_id for campaign in world.campaigns
    )
    assert manifest.fraudulent_entity_ids == expected_entity_ids
    assert manifest.fraudulent_event_ids == expected_event_ids
    assert manifest.causal_signal_ids == expected_causal_signal_ids
    assert manifest.red_herring_ids == (lookalike_signal.signal_id,)
    assert lookalike_signal.signal_id not in manifest.causal_signal_ids
    assert any(
        signal.signal_id not in manifest.causal_signal_ids
        and not signal.is_red_herring
        and signal.signal_id not in manifest.red_herring_ids
        for signal in world.signals
    )
    assert manifest.correct_hypothesis == blueprint.correct_hypothesis


def _stable_unique(identifiers: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(identifiers))
