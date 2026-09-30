"""The harness must evaluate structure using the product's contract, not a copy.

`docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 7: the machine-checkable
contract must have a single definition, because a drifted harness reports model
fitness against a contract the product does not enforce. These tests are the drift
alarm.
"""

from __future__ import annotations

import json

import investigation.proposal_agent as product

from validation.qualification.contract import (
    CHECK_COVERAGE,
    StructuralCheck,
    attribute_failure,
    attributed_failure_messages,
    evaluate_structural_contract,
    forbidden_private_references,
)

from qualification_support import valid_response_text


def _response(**overrides) -> str:
    payload = json.loads(valid_response_text())
    payload.update(overrides)
    return json.dumps(payload)


def test_structurally_valid_response_reports_valid_and_returns_parsed_content() -> None:
    outcome, parsed = evaluate_structural_contract(valid_response_text())

    assert outcome.structurally_valid is True
    assert outcome.failed_check is None
    assert parsed is not None
    assert len(parsed.direction.plan_steps) == 2


def test_every_attributed_message_is_still_produced_by_the_product_contract() -> None:
    """If the product rewords a check, this fails instead of misattributing results."""
    produced: set[str] = set()
    for candidate in _responses_exercising_the_contract():
        try:
            response = product.parse_proposal_model_response(candidate)
            product._require_no_private_references(response)
        except ValueError as error:
            produced.add(str(error))

    unproduced = set(attributed_failure_messages()) - produced
    assert not unproduced, (
        "the harness maps messages the product no longer raises; the contract has "
        f"drifted: {sorted(unproduced)}"
    )


def test_a_message_the_harness_does_not_recognise_is_reported_as_unattributed() -> None:
    """Drift degrades to a visible unattributed count, never to a guessed category."""
    assert attribute_failure("a check the harness has never seen") is (
        StructuralCheck.UNATTRIBUTED_CONTRACT_FAILURE
    )


def test_unexpected_response_shape_is_attributed_to_the_exact_shape_check() -> None:
    outcome, parsed = evaluate_structural_contract('{"unexpected": "shape"}')

    assert outcome.failed_check == StructuralCheck.EXACT_RESPONSE_SHAPE.value
    assert parsed is None


def test_non_json_response_is_attributed_to_the_json_parse_check() -> None:
    outcome, parsed = evaluate_structural_contract("Here is my plan, not JSON.")

    assert outcome.structurally_valid is False
    assert outcome.failed_check == StructuralCheck.JSON_PARSE.value
    assert parsed is None


def test_single_competing_explanation_is_attributed_to_its_own_check() -> None:
    outcome, _ = evaluate_structural_contract(
        _response(competing_explanations=["Only one explanation."])
    )

    assert outcome.failed_check == StructuralCheck.COMPETING_EXPLANATIONS.value


def test_single_plan_step_is_attributed_to_its_own_check() -> None:
    outcome, _ = evaluate_structural_contract(_response(plan_steps=["Only one step."]))

    assert outcome.failed_check == StructuralCheck.PLAN_STEPS.value


def test_duplicate_entries_are_attributed_after_trivial_normalization() -> None:
    outcome, _ = evaluate_structural_contract(
        _response(plan_steps=["Establish the event sequence.", "establish   the event SEQUENCE."])
    )

    assert outcome.failed_check == StructuralCheck.NO_EXACT_DUPLICATES.value


def test_model_assigned_metadata_is_rejected_under_the_exact_shape_checks() -> None:
    payload = json.loads(valid_response_text())
    payload["proposal_id"] = "model-invented-id"
    response_outcome, _ = evaluate_structural_contract(json.dumps(payload))
    assert response_outcome.failed_check == StructuralCheck.EXACT_RESPONSE_SHAPE.value

    payload = json.loads(valid_response_text())
    payload["proposal"]["status"] = "APPROVED"
    proposal_outcome, _ = evaluate_structural_contract(json.dumps(payload))
    assert proposal_outcome.failed_check == StructuralCheck.EXACT_PROPOSAL_FIELDS.value


def test_evaluator_only_reference_is_attributed_to_the_private_reference_check() -> None:
    payload = json.loads(valid_response_text())
    payload["proposal"]["data_to_be_used"] = "the ground truth manifest"

    outcome, parsed = evaluate_structural_contract(json.dumps(payload))

    assert outcome.failed_check == StructuralCheck.NO_PRIVATE_REFERENCES.value
    assert parsed is None


def test_forbidden_reference_list_is_the_products_own_definition() -> None:
    assert forbidden_private_references() == tuple(product._FORBIDDEN_PRIVATE_REFERENCES)


def test_every_reporting_category_documents_the_check_it_covers() -> None:
    assert set(CHECK_COVERAGE) == {check.value for check in StructuralCheck}


def test_structural_outcome_carries_no_score_of_any_kind() -> None:
    """Section 4 prohibits any automated value that could be read as a quality verdict."""
    outcome, _ = evaluate_structural_contract(valid_response_text())

    fields = set(vars(outcome))
    assert fields == {"structurally_valid", "failed_check", "failure_detail"}
    assert not any(
        token in name for name in fields for token in ("score", "rating", "rank", "grade")
    )


def _responses_exercising_the_contract() -> tuple[object, ...]:
    """Inputs chosen to make the product raise each message the harness attributes."""
    duplicate = "Establish the event sequence."
    return (
        123,
        "not json at all",
        json.dumps(["a", "list"]),
        _response(unexpected_field="present"),
        _response(competing_explanations="a string, not a list"),
        _response(competing_explanations=["   "]),
        _response(competing_explanations=["Only one."]),
        _response(plan_steps={"not": "a list"}),
        _response(plan_steps=["  "]),
        _response(plan_steps=["Only one step."]),
        _response(proposal={"action": "only one field"}),
        _response(proposal={
            "action": 1, "purpose": "p", "why_now": "w",
            "data_to_be_used": "d", "expected_output": "e",
        }),
        *(
            _response(proposal={**json.loads(valid_response_text())["proposal"], field: "  "})
            for field in product._PROPOSAL_FIELDS
        ),
        _response(competing_explanations=[duplicate, duplicate.upper()]),
        _response(plan_steps=[duplicate, f"  {duplicate.upper()} "]),
        _response(proposal={
            **json.loads(valid_response_text())["proposal"],
            "data_to_be_used": "the ground truth manifest",
        }),
    )
