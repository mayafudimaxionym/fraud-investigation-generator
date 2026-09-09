from generator.scenario.spec import ScenarioSpec
from generator.validation.ground_truth import validate_ground_truth_hypothesis
from generator.validation.ground_truth import validate_ground_truth_references
from generator.world.model import CanonicalWorld
from generator.world.truth import GroundTruthManifest


def test_ground_truth_validation_rejects_undeclared_hypothesis() -> None:
    scenario = ScenarioSpec(
        domain="payments",
        scale="small",
        fraud_mechanism="account takeover",
        competing_hypotheses=("account takeover", "merchant dispute abuse"),
        required_signals=("temporal",),
        required_artifacts=("client email",),
    )
    ground_truth = GroundTruthManifest(
        campaign_ids=("campaign-001",),
        fraudulent_entity_ids=("account-001",),
        fraudulent_event_ids=("event-001",),
        causal_signal_ids=("signal-001",),
        red_herring_ids=("signal-002",),
        correct_hypothesis="first-party fraud",
    )

    assert validate_ground_truth_hypothesis(scenario, ground_truth) == (
        "correct_hypothesis must be declared in competing_hypotheses",
    )


def test_ground_truth_validation_reports_missing_fraudulent_event() -> None:
    ground_truth = GroundTruthManifest(
        campaign_ids=("campaign-001",),
        fraudulent_entity_ids=(),
        fraudulent_event_ids=("event-001",),
        causal_signal_ids=(),
        red_herring_ids=(),
        correct_hypothesis="account takeover",
    )

    assert validate_ground_truth_references(
        CanonicalWorld(entities=(), relationships=(), events=()), ground_truth
    ) == ("ground_truth: missing fraudulent event event-001",)
