"""Direction-aware local proposal generation from governed investigator context."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from investigation.models import AnalyticalActionProposal, InvestigationDirection
from investigation.package_access import InvestigatorPackageContext


_GENERATION_MODES = ("INITIAL", "MODIFY", "DECLINE_REDIRECT")
_PROPOSAL_FIELDS = (
    "action", "purpose", "why_now", "data_to_be_used", "expected_output"
)
_RESPONSE_FIELDS = ("competing_explanations", "plan_steps", "proposal")
_FORBIDDEN_PRIVATE_REFERENCES = (
    "evaluator_only", "evaluator-only", "ground_truth", "ground truth",
    "campaigns.csv", "signals.csv", "canonical world", "canonical-world",
    "private world", "private data", "evaluator artifact",
)


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True)
class ProposalOllamaConfig:
    """Explicit deployment configuration for one local investigation model."""

    base_url: str = "http://localhost:11434"
    model: str = ""
    timeout_seconds: float = 300.0
    temperature: float = 0.0
    seed: int = 42

    def __post_init__(self) -> None:
        _require_non_blank(self.base_url, "base_url")
        _require_non_blank(self.model, "model")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(self.temperature, (int, float)):
            raise ValueError("temperature must be numeric")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")

    @classmethod
    def from_environment(cls) -> "ProposalOllamaConfig":
        """Load explicit local deployment settings without a settings framework."""
        return cls(
            base_url=os.environ.get("OLLAMA_BASE_URL", cls.base_url).rstrip("/"),
            model=os.environ.get("OLLAMA_MODEL", ""),
            timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300")),
            temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0")),
            seed=int(os.environ.get("OLLAMA_SEED", "42")),
        )


class ProposalModelFailureCategory(str, Enum):
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    GENERATION_ERROR = "GENERATION_ERROR"


class ProposalModelError(RuntimeError):
    """A local-model failure whose category is safe for later UI handling."""

    def __init__(self, category: ProposalModelFailureCategory, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class CandidateDirectionContent:
    """Model-proposed textual direction without persisted-direction ownership."""

    competing_explanations: tuple[str, ...]
    plan_steps: tuple[str, ...]


@dataclass(frozen=True)
class ProposalModelResponse:
    """Strict identifier-free structured content returned by the local model."""

    direction: CandidateDirectionContent
    action: str
    purpose: str
    why_now: str
    data_to_be_used: str
    expected_output: str


@dataclass(frozen=True)
class ProposalGenerationRequest:
    """The complete governed input for one candidate V0.5 proposal request."""

    context: InvestigatorPackageContext
    objective: str
    proposal_id: str
    created_at: datetime
    mode: str
    investigator_instruction: str | None = None
    current_direction: InvestigationDirection | None = None
    source_proposal: AnalyticalActionProposal | None = None
    decline_guidance: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context, InvestigatorPackageContext):
            raise ValueError("context must be an InvestigatorPackageContext")
        if not isinstance(self.objective, str):
            raise ValueError("objective must be a string")
        _require_non_blank(self.proposal_id, "proposal_id")
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be a datetime")
        if self.mode not in _GENERATION_MODES:
            raise ValueError(f"mode must be one of {_GENERATION_MODES}")
        if self.investigator_instruction is not None:
            _require_non_blank(self.investigator_instruction, "investigator_instruction")
        if self.decline_guidance is not None:
            _require_non_blank(self.decline_guidance, "decline_guidance")
        if self.mode == "INITIAL":
            if any(value is not None for value in (
                self.current_direction, self.source_proposal, self.decline_guidance
            )):
                raise ValueError("INITIAL must not include prior direction or proposal state")
        elif self.current_direction is None or self.source_proposal is None:
            raise ValueError(f"{self.mode} requires current_direction and source_proposal")
        elif self.mode == "MODIFY":
            if self.investigator_instruction is None:
                raise ValueError("MODIFY requires an investigator_instruction")
            if self.decline_guidance is not None:
                raise ValueError("MODIFY must not include decline_guidance")
        elif self.mode == "DECLINE_REDIRECT" and self.investigator_instruction is not None:
            raise ValueError("DECLINE_REDIRECT must use decline_guidance instead of instruction")


class ProposalModelClient(Protocol):
    """A fakeable local-model boundary for structured proposal responses."""

    def generate(self, prompt: str) -> str:
        """Return the model's JSON response text."""


@dataclass(frozen=True)
class ProposalAgentResult:
    """Candidate direction text and exactly one human-reviewable proposal."""

    provisional_plan: str
    proposal: AnalyticalActionProposal
    direction: CandidateDirectionContent = CandidateDirectionContent((), ())


class OllamaProposalClient:
    """Dependency-free local Ollama transport with explicit preflight and failures."""

    def __init__(self, config: ProposalOllamaConfig) -> None:
        self._config = config

    @property
    def config(self) -> ProposalOllamaConfig:
        """Expose the effective explicit deployment configuration to the application."""
        return self._config

    def preflight(self) -> None:
        """Confirm that the local service and exact configured model are available."""
        request = Request(f"{self._config.base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as reply:
                payload = json.loads(reply.read().decode("utf-8"))
        except TimeoutError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.SERVICE_UNAVAILABLE,
                "local Ollama service did not respond to preflight",
            ) from error
        except HTTPError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local Ollama preflight returned an invalid response",
            ) from error
        except URLError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.SERVICE_UNAVAILABLE,
                "local Ollama service is unavailable",
            ) from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local Ollama preflight returned an invalid response",
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local Ollama preflight returned an invalid response",
            )
        model_names = {
            item.get("name") for item in payload["models"]
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if self._config.model not in model_names:
            raise ProposalModelError(
                ProposalModelFailureCategory.MODEL_UNAVAILABLE,
                "the configured local Ollama model is unavailable",
            )

    def generate(self, prompt: str) -> str:
        """Make exactly one model request; this boundary never retries automatically."""
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": self._config.temperature, "seed": self._config.seed},
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
        except TimeoutError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.REQUEST_TIMEOUT,
                "local Ollama proposal request timed out",
            ) from error
        except HTTPError as error:
            category = (
                ProposalModelFailureCategory.MODEL_UNAVAILABLE
                if error.code == 404
                else ProposalModelFailureCategory.GENERATION_ERROR
            )
            raise ProposalModelError(category, "local Ollama proposal request failed") from error
        except URLError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.SERVICE_UNAVAILABLE,
                "local Ollama service is unavailable",
            ) from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local Ollama proposal response was invalid",
            ) from error
        if not isinstance(body, dict) or not isinstance(body.get("response"), str):
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local Ollama proposal response was invalid",
            )
        return body["response"]


class LocalProposalAgent:
    """Create one unpersisted, non-executing proposal from governed inputs only."""

    def __init__(self, client: ProposalModelClient) -> None:
        self._client = client

    def generate(self, request: ProposalGenerationRequest) -> ProposalAgentResult:
        """Return candidate direction content and one proposal without side effects."""
        try:
            response = parse_proposal_model_response(
                self._client.generate(build_proposal_prompt(request))
            )
            _require_no_private_references(response)
        except ProposalModelError:
            raise
        except ValueError as error:
            raise ProposalModelError(
                ProposalModelFailureCategory.GENERATION_ERROR,
                "local model returned an invalid proposal response",
            ) from error
        proposal = AnalyticalActionProposal(
            proposal_id=request.proposal_id,
            action=response.action,
            purpose=response.purpose,
            why_now=response.why_now,
            data_to_be_used=response.data_to_be_used,
            expected_output=response.expected_output,
            status="PROPOSED",
            created_at=request.created_at,
        )
        return ProposalAgentResult(
            provisional_plan="\n".join(response.direction.plan_steps),
            proposal=proposal,
            direction=response.direction,
        )

    def propose(
        self,
        context: InvestigatorPackageContext,
        investigator_instruction: str,
        proposal_id: str,
        created_at: datetime,
    ) -> ProposalAgentResult:
        """Retain the V0 caller shape while using the V0.5 INITIAL contract."""
        return self.generate(ProposalGenerationRequest(
            context=context,
            objective="",
            proposal_id=proposal_id,
            created_at=created_at,
            mode="INITIAL",
            investigator_instruction=investigator_instruction,
        ))


def build_proposal_prompt(request: ProposalGenerationRequest) -> str:
    """Render only governed input into a strict direction-aware model prompt."""
    datasets = "\n".join(
        "- "
        f"{dataset.dataset_name} | {dataset.row_count} rows | "
        f"fields: {', '.join(dataset.field_names)}"
        for dataset in request.context.datasets
    )
    return (
        "Return JSON only with exactly this shape:\n"
        '{"competing_explanations": ["..."], "plan_steps": ["..."], '
        '"proposal": {"action": "...", "purpose": "...", "why_now": "...", '
        '"data_to_be_used": "...", "expected_output": "..."}}\n\n'
        "Maintain plausible competing explanations where warranted. Customer/support statements "
        "and prior analyst notes are evidence inputs or possible explanations, not established "
        "facts or findings. Prefer the one next action that can discriminate among plausible "
        "explanations. The proposal must be investigator-readable and must not describe Python, "
        "SQL, internal tools, filesystem operations, execution details, or analytical results that "
        "have not been produced. The action is neither authorized nor executed. Use only the "
        "supplied context and inventory; do not refer to sources that were not supplied.\n\n"
        f"Generation mode: {request.mode}\n"
        f"Effective investigation objective (may be intentionally blank):\n{request.objective}\n\n"
        f"Investigation request:\n{request.context.investigation_request}\n\n"
        f"Customer or support statement:\n{request.context.customer_support_statement}\n\n"
        f"Prior analyst note:\n{request.context.prior_analyst_note}\n\n"
        f"Available structured dataset inventory:\n{datasets}\n"
        f"{_direction_prompt_context(request)}"
    )


def parse_proposal_model_response(response_text: str) -> ProposalModelResponse:
    """Accept only strict identifier-free V0.5 direction and proposal content."""
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
    direction = CandidateDirectionContent(
        _parse_text_list(payload["competing_explanations"], "competing_explanations"),
        _parse_text_list(payload["plan_steps"], "plan_steps"),
    )
    proposal = payload["proposal"]
    if not isinstance(proposal, dict) or set(proposal) != set(_PROPOSAL_FIELDS):
        raise ValueError("proposal response proposal must contain exactly the five proposal fields")
    if not all(isinstance(proposal[field], str) for field in _PROPOSAL_FIELDS):
        raise ValueError("proposal response proposal fields must all be strings")
    for field in _PROPOSAL_FIELDS:
        _require_non_blank(proposal[field], field)
    return ProposalModelResponse(
        direction=direction, **{field: proposal[field] for field in _PROPOSAL_FIELDS}
    )


def _parse_text_list(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    for item in value:
        _require_non_blank(item, field_name)
    return tuple(value)


def _direction_prompt_context(request: ProposalGenerationRequest) -> str:
    if request.mode == "INITIAL":
        return (
            f"\nInvestigator instruction:\n{request.investigator_instruction}"
            if request.investigator_instruction is not None
            else ""
        )

    assert request.current_direction is not None
    assert request.source_proposal is not None
    explanations = "\n".join(f"- {item}" for item in request.current_direction.competing_explanations)
    plan_steps = "\n".join(f"- {item}" for item in request.current_direction.plan_steps)
    proposal = request.source_proposal
    content = (
        "\nCurrent working explanations (none is established):\n"
        f"{explanations or '- None recorded'}\n\n"
        "Current provisional plan steps:\n"
        f"{plan_steps or '- None recorded'}\n\n"
        "Prior proposed action for context:\n"
        f"Action: {proposal.action}\nPurpose: {proposal.purpose}\n"
        f"Why now: {proposal.why_now}\nData to be used: {proposal.data_to_be_used}\n"
        f"Expected output: {proposal.expected_output}\n"
    )
    if request.mode == "MODIFY":
        assert request.investigator_instruction is not None
        return content + f"\nInvestigator modification instruction:\n{request.investigator_instruction}"
    if request.decline_guidance is None:
        return content + "\nThe prior action was declined without additional guidance."
    return content + f"\nPersisted decline guidance:\n{request.decline_guidance}"


def _require_no_private_references(response: ProposalModelResponse) -> None:
    values = (
        *response.direction.competing_explanations,
        *response.direction.plan_steps,
        response.action,
        response.purpose,
        response.why_now,
        response.data_to_be_used,
        response.expected_output,
    )
    if any(
        reference in value.casefold()
        for value in values
        for reference in _FORBIDDEN_PRIVATE_REFERENCES
    ):
        raise ValueError("proposal response references a source outside governed context")
