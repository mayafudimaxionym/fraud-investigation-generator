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


def test_scenario_spec_rejects_duplicate_hypotheses() -> None:
    try:
        ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "account takeover"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        )
    except ValueError as error:
        assert "competing_hypotheses" in str(error)
    else:
        raise AssertionError("duplicate hypotheses must be rejected")


def test_scenario_spec_serializes_to_json_compatible_payload() -> None:
    scenario = ScenarioSpec(
        domain="payments",
        scale="small",
        fraud_mechanism="account takeover",
        competing_hypotheses=("account takeover", "merchant dispute abuse"),
        required_signals=("temporal", "relational"),
        required_artifacts=("client email",),
    )

    assert scenario.to_dict() == {
        "domain": "payments",
        "scale": "small",
        "fraud_mechanism": "account takeover",
        "competing_hypotheses": ["account takeover", "merchant dispute abuse"],
        "required_signals": ["temporal", "relational"],
        "required_artifacts": ["client email"],
    }
