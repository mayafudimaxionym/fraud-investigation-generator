"""Structural evaluation that consumes the product's contract instead of restating it.

`docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 7 records one genuine
architecture constraint for this harness: **the machine-checkable contract must have
a single definition.** Two definitions drift, and a drifted harness reports model
fitness against a contract the product does not enforce.

So the authoritative verdict here is always the product's own
`parse_proposal_model_response` plus the product's private-reference check. This
module adds no threshold, no field list and no tolerance of its own. Its only extra
job is *attribution*: mapping the product's raised message onto the reporting
category from section 4 so results can be reported as counts per check.

Attribution is deliberately fail-visible. An unrecognised message is reported as
`UNATTRIBUTED_CONTRACT_FAILURE` rather than guessed into a category, and
`tests/test_qualification_contract.py` asserts every mapped message is still
producible by the product, so contract drift surfaces as a test failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Private names are imported on purpose: they are the single definition of the
# product's contract (section 7). Restating the token list or the field lists here
# is the specific failure mode that constraint exists to prevent.
from investigation.proposal_agent import (  # noqa: PLC2701
    _FORBIDDEN_PRIVATE_REFERENCES,
    _PROPOSAL_FIELDS,
    _require_no_private_references,
    ProposalModelResponse,
    parse_proposal_model_response,
)


class StructuralCheck(str, Enum):
    """Reporting categories for the section 4 structural checks."""

    JSON_PARSE = "JSON_PARSE"
    EXACT_RESPONSE_SHAPE = "EXACT_RESPONSE_SHAPE"
    EXACT_PROPOSAL_FIELDS = "EXACT_PROPOSAL_FIELDS"
    COMPETING_EXPLANATIONS = "COMPETING_EXPLANATIONS"
    PLAN_STEPS = "PLAN_STEPS"
    NO_EXACT_DUPLICATES = "NO_EXACT_DUPLICATES"
    NO_PRIVATE_REFERENCES = "NO_PRIVATE_REFERENCES"
    UNATTRIBUTED_CONTRACT_FAILURE = "UNATTRIBUTED_CONTRACT_FAILURE"


#: Which section 4 structural check each reporting category covers. The product
#: enforces "no model-assigned IDs, status, timestamps or authorization" by exact-set
#: equality on the response and proposal keys, so that requirement is reported under
#: the two exact-shape categories rather than as a separate check.
CHECK_COVERAGE: dict[str, str] = {
    StructuralCheck.JSON_PARSE.value: "parses as JSON",
    StructuralCheck.EXACT_RESPONSE_SHAPE.value: (
        "exact approved response shape; no model-assigned IDs, status, timestamps or "
        "authorization at the response level"
    ),
    StructuralCheck.EXACT_PROPOSAL_FIELDS.value: (
        "exactly one five-field proposal, all fields non-blank strings; no "
        "model-assigned IDs, status, timestamps or authorization inside the proposal"
    ),
    StructuralCheck.COMPETING_EXPLANATIONS.value: "at least two competing explanations",
    StructuralCheck.PLAN_STEPS.value: "at least two ordered plan steps",
    StructuralCheck.NO_EXACT_DUPLICATES.value: (
        "no exact duplicates after trivial normalization"
    ),
    StructuralCheck.NO_PRIVATE_REFERENCES.value: "no evaluator-only references",
    StructuralCheck.UNATTRIBUTED_CONTRACT_FAILURE.value: (
        "the product rejected the response with a message this harness does not "
        "recognise; the contract definition has probably changed"
    ),
}


#: Exact messages raised by the product's contract code, mapped to a reporting
#: category. Keyed on the exact message so a reworded product check degrades to
#: UNATTRIBUTED_CONTRACT_FAILURE instead of being misattributed.
_FAILURE_ATTRIBUTION: dict[str, StructuralCheck] = {
    "proposal response must be JSON text": StructuralCheck.JSON_PARSE,
    "proposal response was not JSON": StructuralCheck.JSON_PARSE,
    "proposal response JSON must be an object": StructuralCheck.EXACT_RESPONSE_SHAPE,
    "proposal response must contain exactly the required fields": (
        StructuralCheck.EXACT_RESPONSE_SHAPE
    ),
    "competing_explanations must be a list of strings": StructuralCheck.COMPETING_EXPLANATIONS,
    "competing_explanations must be non-empty": StructuralCheck.COMPETING_EXPLANATIONS,
    "response requires at least two competing explanations": (
        StructuralCheck.COMPETING_EXPLANATIONS
    ),
    "plan_steps must be a list of strings": StructuralCheck.PLAN_STEPS,
    "plan_steps must be non-empty": StructuralCheck.PLAN_STEPS,
    "response requires at least two provisional plan steps": StructuralCheck.PLAN_STEPS,
    "proposal response proposal must contain exactly the five proposal fields": (
        StructuralCheck.EXACT_PROPOSAL_FIELDS
    ),
    "proposal response proposal fields must all be strings": (
        StructuralCheck.EXACT_PROPOSAL_FIELDS
    ),
    "competing explanations must not contain exact duplicates": (
        StructuralCheck.NO_EXACT_DUPLICATES
    ),
    "provisional plan steps must not contain exact duplicates": (
        StructuralCheck.NO_EXACT_DUPLICATES
    ),
    "proposal response references a source outside governed context": (
        StructuralCheck.NO_PRIVATE_REFERENCES
    ),
    **{
        f"{field} must be non-empty": StructuralCheck.EXACT_PROPOSAL_FIELDS
        for field in _PROPOSAL_FIELDS
    },
}


def attribute_failure(message: str) -> StructuralCheck:
    """Map a message raised by the product's contract onto a reporting category.

    An unrecognised message is `UNATTRIBUTED_CONTRACT_FAILURE`, never a guess. A
    reworded product check then shows up as an unattributed count in the roll-up
    rather than being silently counted as some other check.
    """
    return _FAILURE_ATTRIBUTION.get(message, StructuralCheck.UNATTRIBUTED_CONTRACT_FAILURE)


def attributed_failure_messages() -> tuple[str, ...]:
    """Expose the mapped messages so a drift test can assert they are still produced."""
    return tuple(_FAILURE_ATTRIBUTION)


def forbidden_private_references() -> tuple[str, ...]:
    """Return the product's own evaluator-only token list. Never a harness copy."""
    return tuple(_FORBIDDEN_PRIVATE_REFERENCES)


@dataclass(frozen=True)
class StructuralOutcome:
    """Whether one raw response satisfied the product's contract, and where it failed.

    Deliberately carries no score and no quality judgement of any kind: a boolean,
    a failure category and the product's own message. Section 4 prohibits any
    automated value that could be read as a verdict on quality.
    """

    structurally_valid: bool
    failed_check: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.structurally_valid, bool):
            raise ValueError("structurally_valid must be a bool")
        if self.structurally_valid and (self.failed_check or self.failure_detail):
            raise ValueError("a structurally valid outcome must record no failed check")
        if not self.structurally_valid and not self.failed_check:
            raise ValueError("a structurally invalid outcome must record a failed check")


def evaluate_structural_contract(
    raw_response: str,
) -> tuple[StructuralOutcome, ProposalModelResponse | None]:
    """Apply the product's contract to a raw response already captured verbatim.

    Returns the outcome and, when the response is valid, the parsed content so the
    harness can chain the next turn and present the plan for human reading.
    """
    if not isinstance(raw_response, str):
        raise ValueError("raw_response must be the verbatim response text")
    try:
        response = parse_proposal_model_response(raw_response)
        _require_no_private_references(response)
    except ValueError as error:
        message = str(error)
        return StructuralOutcome(False, attribute_failure(message).value, message), None
    return StructuralOutcome(True), response
