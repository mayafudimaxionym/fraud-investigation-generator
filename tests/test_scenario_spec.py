from generator.scenario.spec import ScenarioSpec


def test_scenario_spec_rejects_blank_mechanism() -> None:
    try:
        ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism=" ",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal", "relational", "behavioral"),
            required_artifacts=("client email",),
        )
    except ValueError as error:
        assert "fraud_mechanism" in str(error)
    else:
        raise AssertionError("blank fraud mechanisms must be rejected")
