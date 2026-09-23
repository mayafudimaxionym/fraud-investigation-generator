"""Local V0 proposal generation constrained to governed investigator context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from generator.artifacts.ollama import OllamaConfig
from investigation.models import AnalyticalActionProposal
from investigation.package_access import InvestigatorPackageContext


_RESPONSE_FIELDS = (
    "provisional_plan",
    "action",
    "purpose",
    "why_now",
    "data_to_be_used",
    "expected_output",
)
_FORBIDDEN_DATA_SOURCE_REFERENCES = (
    "evaluator_only",
    "ground_truth.csv",
    "campaigns.csv",
    "signals.csv",
    "canonical world",
    "canonical-world",
    "private world",
    "private data",
)


class ProposalModelClient(Protocol):
    """A fakeable local-model boundary for structured proposal responses."""

    def generate(self, prompt: str) -> str:
        """Return the model's JSON response text."""


@dataclass(frozen=True)
class ProposalAgentResult:
    """One informational plan and one human-reviewable V0 proposal."""

    provisional_plan: str
    proposal: AnalyticalActionProposal


class OllamaProposalClient:
    """Dependency-free local Ollama transport for the V0 proposal agent."""

    def __init__(self, config: OllamaConfig) -> None:
        self._config = config

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._config.temperature,
                "seed": self._config.seed,
            },
        }
        request = Request(
            f"{self._config.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as reply:
                body = json.loads(reply.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Ollama proposal generation failed: {error}") from error
        if not isinstance(body, dict):
            raise RuntimeError("Ollama proposal response must be a JSON object")
        response_text = body.get("response")
        if "response" not in body or not isinstance(response_text, str):
            raise RuntimeError("Ollama proposal response did not contain string response")
        return response_text


class LocalProposalAgent:
    """Create one non-executing proposal from governed initial context."""

    def __init__(self, client: ProposalModelClient) -> None:
        self._client = client

    def propose(
        self,
        context: InvestigatorPackageContext,
        investigator_instruction: str,
        proposal_id: str,
        created_at: datetime,
    ) -> ProposalAgentResult:
        """Request and validate exactly one structured, unpersisted proposal."""
        if not isinstance(context, InvestigatorPackageContext):
            raise ValueError("context must be an InvestigatorPackageContext")
        _require_non_blank(investigator_instruction, "investigator_instruction")

        response = parse_proposal_model_response(
            self._client.generate(build_proposal_prompt(context, investigator_instruction))
        )
        _require_visible_data_reference(response["data_to_be_used"])
        proposal = AnalyticalActionProposal(
            proposal_id=proposal_id,
            action=response["action"],
            purpose=response["purpose"],
            why_now=response["why_now"],
            data_to_be_used=response["data_to_be_used"],
            expected_output=response["expected_output"],
            status="PROPOSED",
            created_at=created_at,
        )
        return ProposalAgentResult(response["provisional_plan"], proposal)


def build_proposal_prompt(
    context: InvestigatorPackageContext, investigator_instruction: str
) -> str:
    """Render only the approved V0 initial agent context into a model prompt."""
    _require_non_blank(investigator_instruction, "investigator_instruction")
    datasets = "\n".join(
        "- "
        f"{dataset.dataset_name} | {dataset.row_count} rows | "
        f"fields: {', '.join(dataset.field_names)}"
        for dataset in context.datasets
    )
    return (
        "Return JSON only, with exactly these string fields: "
        "provisional_plan, action, purpose, why_now, data_to_be_used, expected_output.\n"
        "Propose exactly one next analytical action for human review. "
        "Do not execute, simulate, or claim results of the action. "
        "Use only the supplied investigation context and dataset inventory.\n\n"
        f"Investigator instruction:\n{investigator_instruction}\n\n"
        f"Investigation request:\n{context.investigation_request}\n\n"
        f"Customer or support statement:\n{context.customer_support_statement}\n\n"
        f"Prior analyst note:\n{context.prior_analyst_note}\n\n"
        f"Available structured dataset inventory:\n{datasets}"
    )


def parse_proposal_model_response(response_text: str) -> dict[str, str]:
    """Accept only the strict six-field JSON proposal response contract."""
    if not isinstance(response_text, str):
        raise ValueError("proposal response must be JSON text")
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError("proposal response was not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("proposal response JSON must be an object")
    if set(payload) != set(_RESPONSE_FIELDS):
        raise ValueError("proposal response must contain exactly the required fields")
    if not all(isinstance(payload[field], str) for field in _RESPONSE_FIELDS):
        raise ValueError("proposal response fields must all be strings")
    response = {field: payload[field] for field in _RESPONSE_FIELDS}
    for field, value in response.items():
        _require_non_blank(value, field)
    return response


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_visible_data_reference(value: str) -> None:
    """Reject explicit V0 references to sources outside governed context."""
    normalized_value = value.casefold()
    if any(reference in normalized_value for reference in _FORBIDDEN_DATA_SOURCE_REFERENCES):
        raise ValueError("data_to_be_used references a source outside governed context")
