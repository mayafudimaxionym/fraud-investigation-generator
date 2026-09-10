from generator.artifacts.manifest import InvestigatorViewManifest
from generator.case import CanonicalCase
from generator.metadata import GenerationMetadata
from generator.scenario.spec import ScenarioSpec
from generator.validation.case import validate_case
from generator.world.model import CanonicalWorld
from generator.world.truth import GroundTruthManifest


def test_case_validation_reports_undeclared_correct_hypothesis() -> None:
    case = CanonicalCase(
        case_id="case-001",
        metadata=GenerationMetadata(427, "0.1.0", "1", "1"),
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        world=CanonicalWorld(entities=(), relationships=(), events=()),
        ground_truth=GroundTruthManifest(
            campaign_ids=(),
            fraudulent_entity_ids=(),
            fraudulent_event_ids=(),
            causal_signal_ids=(),
            red_herring_ids=(),
            correct_hypothesis="first-party fraud",
        ),
        investigator_view=InvestigatorViewManifest((), (), ()),
    )

    assert validate_case(case) == (
        "correct_hypothesis must be declared in competing_hypotheses",
    )


def test_case_validation_reports_missing_ground_truth_event() -> None:
    case = CanonicalCase(
        case_id="case-001",
        metadata=GenerationMetadata(427, "0.1.0", "1", "1"),
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        world=CanonicalWorld(entities=(), relationships=(), events=()),
        ground_truth=GroundTruthManifest(
            campaign_ids=(),
            fraudulent_entity_ids=(),
            fraudulent_event_ids=("event-001",),
            causal_signal_ids=(),
            red_herring_ids=(),
            correct_hypothesis="account takeover",
        ),
        investigator_view=InvestigatorViewManifest((), (), ()),
    )

    assert validate_case(case) == (
        "ground_truth: missing fraudulent event event-001",
    )


def test_case_validation_reports_missing_visible_entity() -> None:
    case = CanonicalCase(
        case_id="case-001",
        metadata=GenerationMetadata(427, "0.1.0", "1", "1"),
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        world=CanonicalWorld(entities=(), relationships=(), events=()),
        ground_truth=GroundTruthManifest(
            campaign_ids=(),
            fraudulent_entity_ids=(),
            fraudulent_event_ids=(),
            causal_signal_ids=(),
            red_herring_ids=(),
            correct_hypothesis="account takeover",
        ),
        investigator_view=InvestigatorViewManifest(("account-001",), (), ()),
    )

    assert validate_case(case) == (
        "investigator_view: missing visible entity account-001",
    )


def test_case_validation_reports_missing_visible_artifact() -> None:
    case = CanonicalCase(
        case_id="case-001",
        metadata=GenerationMetadata(427, "0.1.0", "1", "1"),
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        world=CanonicalWorld(entities=(), relationships=(), events=()),
        ground_truth=GroundTruthManifest(
            campaign_ids=(),
            fraudulent_entity_ids=(),
            fraudulent_event_ids=(),
            causal_signal_ids=(),
            red_herring_ids=(),
            correct_hypothesis="account takeover",
        ),
        investigator_view=InvestigatorViewManifest((), (), ("email-001",)),
    )

    assert validate_case(case) == (
        "investigator_view: missing artifact email-001",
    )
