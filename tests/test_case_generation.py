from generator.metadata import GenerationMetadata
from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.validation.case import validate_case
from generator.world.generation import (
    build_canonical_case,
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


def _metadata(master_seed: int = 427) -> GenerationMetadata:
    return GenerationMetadata(
        master_seed=master_seed,
        generator_version="0.1.0",
        scenario_version="1",
        schema_version="1",
    )


def test_canonical_case_generation_is_deterministic_and_composes_builders() -> None:
    blueprint = _blueprint()
    metadata = _metadata()
    case = build_canonical_case("case-001", blueprint, metadata)
    world = build_minimal_world(blueprint, metadata.master_seed)

    assert case == build_canonical_case("case-001", blueprint, metadata)
    assert case.world == world
    assert case.ground_truth == build_ground_truth_manifest(blueprint, world)
    assert case.investigator_view == build_investigator_view_manifest(world)
    assert case.case_id == "case-001"
    assert case.metadata == metadata
    assert case.scenario == blueprint.scenario
    assert case.artifacts == ()
    assert validate_case(case) == ()


def test_canonical_case_generation_varies_by_seed_and_preserves_private_boundary() -> None:
    blueprint = _blueprint()
    case = build_canonical_case("case-001", blueprint, _metadata(427))
    different_seed_case = build_canonical_case("case-001", blueprint, _metadata(428))
    visible_ids = (
        set(case.investigator_view.visible_entity_ids)
        | set(case.investigator_view.visible_relationship_ids)
        | set(case.investigator_view.visible_event_ids)
    )
    lookalike_signal = next(
        signal
        for signal in case.world.signals
        if signal.signal_id in case.ground_truth.red_herring_ids
    )

    assert case != different_seed_case
    assert validate_case(different_seed_case) == ()
    assert set(lookalike_signal.supporting_entity_ids) <= set(
        case.investigator_view.visible_entity_ids
    )
    assert set(lookalike_signal.supporting_event_ids) <= set(
        case.investigator_view.visible_event_ids
    )
    assert visible_ids.isdisjoint(set(case.ground_truth.campaign_ids))
    assert visible_ids.isdisjoint(set(case.ground_truth.causal_signal_ids))
    assert visible_ids.isdisjoint(set(case.ground_truth.red_herring_ids))
    assert case.ground_truth.correct_hypothesis not in visible_ids
