from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec


def _scenario() -> ScenarioSpec:
    return ScenarioSpec(
        domain="payments",
        scale="small",
        fraud_mechanism="account takeover",
        competing_hypotheses=("account takeover", "merchant dispute abuse"),
        required_signals=("temporal",),
        required_artifacts=("client email",),
    )


def test_case_blueprint_rejects_undeclared_correct_hypothesis() -> None:
    try:
        CaseBlueprint(
            scenario=_scenario(),
            correct_hypothesis="first-party fraud",
            campaign_count=1,
        )
    except ValueError as error:
        assert "correct_hypothesis" in str(error)
    else:
        raise AssertionError("undeclared correct hypotheses must be rejected")


def test_case_blueprint_rejects_non_positive_campaign_count() -> None:
    try:
        CaseBlueprint(
            scenario=_scenario(),
            correct_hypothesis="account takeover",
            campaign_count=0,
        )
    except ValueError as error:
        assert "campaign_count" in str(error)
    else:
        raise AssertionError("non-positive campaign counts must be rejected")
