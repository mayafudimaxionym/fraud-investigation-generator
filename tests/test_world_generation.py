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
