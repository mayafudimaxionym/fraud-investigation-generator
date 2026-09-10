from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.investigator_view import validate_investigator_view_references
from generator.world.generation import (
    build_ground_truth_manifest,
    build_investigator_view_manifest,
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


def test_investigator_view_generation_is_deterministic_and_complete() -> None:
    blueprint = _blueprint()
    world = build_minimal_world(blueprint, 427)
    equivalent_world = build_minimal_world(blueprint, 427)

    manifest = build_investigator_view_manifest(world)

    assert manifest == build_investigator_view_manifest(equivalent_world)
    assert manifest.visible_entity_ids == tuple(
        entity.entity_id for entity in world.entities
    )
    assert manifest.visible_relationship_ids == tuple(
        relationship.relationship_id for relationship in world.relationships
    )
    assert manifest.visible_event_ids == tuple(
        event.event_id for event in world.events
    )
    assert manifest.artifact_ids == ()
    assert validate_investigator_view_references(world, manifest) == ()


def test_investigator_view_generation_exposes_lookalike_evidence_without_truth() -> None:
    blueprint = _blueprint()
    world = build_minimal_world(blueprint, 427)
    ground_truth = build_ground_truth_manifest(blueprint, world)

    manifest = build_investigator_view_manifest(world)
    visible_ids = (
        set(manifest.visible_entity_ids)
        | set(manifest.visible_relationship_ids)
        | set(manifest.visible_event_ids)
    )
    lookalike_signal = next(
        signal
        for signal in world.signals
        if signal.signal_id in ground_truth.red_herring_ids
    )
    private_labels = (
        "fraud",
        "lookalike",
        "benign",
        "red_herring",
        "causal",
        "hypothesis",
        "campaign",
    )

    assert set(lookalike_signal.supporting_entity_ids) <= set(
        manifest.visible_entity_ids
    )
    assert set(lookalike_signal.supporting_event_ids) <= set(
        manifest.visible_event_ids
    )
    assert lookalike_signal.signal_id not in visible_ids
    assert visible_ids.isdisjoint(
        set(ground_truth.campaign_ids) | set(ground_truth.causal_signal_ids)
    )
    assert visible_ids.isdisjoint(set(ground_truth.red_herring_ids))
    assert ground_truth.correct_hypothesis not in visible_ids
    assert set(vars(manifest)) == {
        "visible_entity_ids",
        "visible_relationship_ids",
        "visible_event_ids",
        "artifact_ids",
    }
    assert not any(
        label in identifier
        for label in private_labels
        for identifier in visible_ids
    )
