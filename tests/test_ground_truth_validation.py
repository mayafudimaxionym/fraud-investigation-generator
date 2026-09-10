from datetime import UTC, datetime

from generator.scenario.spec import ScenarioSpec
from generator.events.models import CanonicalEvent
from generator.validation.ground_truth import validate_ground_truth_hypothesis
from generator.validation.ground_truth import validate_ground_truth_references
from generator.world.campaigns import FraudCampaign
from generator.world.entities import CanonicalEntity
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
        campaign_ids=(),
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
        fraudulent_entity_ids=("account-001",),
        fraudulent_event_ids=("event-001",),
        causal_signal_ids=(),
        red_herring_ids=(),
        correct_hypothesis="account takeover",
    )

    assert validate_ground_truth_references(
        CanonicalWorld(
            entities=(CanonicalEntity("account-001", "account"),),
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
        ),
        ground_truth,
    ) == ("ground_truth: missing fraudulent event event-001",)


def test_ground_truth_validation_reports_undeclared_campaign_members() -> None:
    ground_truth = GroundTruthManifest(
        campaign_ids=("campaign-001",),
        fraudulent_entity_ids=(),
        fraudulent_event_ids=(),
        causal_signal_ids=(),
        red_herring_ids=(),
        correct_hypothesis="account takeover",
    )

    assert validate_ground_truth_references(
        CanonicalWorld(
            entities=(CanonicalEntity("account-001", "account"),),
            relationships=(),
            events=(
                CanonicalEvent(
                    event_id="event-001",
                    event_type="transfer",
                    subject_entity_id="account-001",
                    occurred_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
                ),
            ),
            campaigns=(
                FraudCampaign(
                    campaign_id="campaign-001",
                    mechanism="account takeover",
                    actor_entity_ids=(),
                    fraudulent_entity_ids=("account-001",),
                    fraudulent_event_ids=("event-001",),
                    causal_signal_ids=(),
                ),
            ),
        ),
        ground_truth,
    ) == (
        "ground_truth: campaign campaign-001 fraudulent entity account-001 "
        "is not declared",
        "ground_truth: campaign campaign-001 fraudulent event event-001 "
        "is not declared",
    )


def test_ground_truth_validation_reports_missing_campaign() -> None:
    ground_truth = GroundTruthManifest(
        campaign_ids=("campaign-001",),
        fraudulent_entity_ids=(),
        fraudulent_event_ids=(),
        causal_signal_ids=(),
        red_herring_ids=(),
        correct_hypothesis="account takeover",
    )

    assert validate_ground_truth_references(
        CanonicalWorld(entities=(), relationships=(), events=()), ground_truth
    ) == ("ground_truth: missing campaign campaign-001",)
