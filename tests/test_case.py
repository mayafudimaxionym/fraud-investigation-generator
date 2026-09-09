from generator.artifacts.manifest import InvestigatorViewManifest
from generator.artifacts.models import InvestigatorArtifact
from generator.case import CanonicalCase
from generator.metadata import GenerationMetadata
from generator.scenario.spec import ScenarioSpec
from generator.world.model import CanonicalWorld
from generator.world.truth import GroundTruthManifest


def test_case_rejects_blank_case_id() -> None:
    try:
        CanonicalCase(
            case_id=" ",
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
            investigator_view=InvestigatorViewManifest((), (), ()),
        )
    except ValueError as error:
        assert "case_id" in str(error)
    else:
        raise AssertionError("blank case IDs must be rejected")


def test_case_rejects_duplicate_artifact_ids() -> None:
    artifact = InvestigatorArtifact("email-001", "client_email", "Please help.")

    try:
        CanonicalCase(
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
            investigator_view=InvestigatorViewManifest((), (), ()),
            artifacts=(artifact, artifact),
        )
    except ValueError as error:
        assert "artifacts" in str(error)
    else:
        raise AssertionError("duplicate artifact IDs must be rejected")
