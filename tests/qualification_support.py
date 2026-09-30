"""Shared fixtures for the Model Qualification Harness tests.

No test in this suite touches Ollama. Building the harness and running the
qualification campaign are separate work, so every test drives a scripted fake client
through the product's own `ProposalModelClient` seam.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from investigation.package_access import DatasetInventory, InvestigatorPackageContext
from investigation.proposal_agent import ProposalModelError, ProposalModelFailureCategory, ProposalOllamaConfig

from validation.qualification.configurations import CandidateConfiguration, ModelEnvironment
from validation.qualification.scenarios import ScenarioDefinition, ScenarioStep


FIXED_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_NOW


def context() -> InvestigatorPackageContext:
    """A governed context with no evaluator-only material, built directly."""
    return InvestigatorPackageContext(
        investigation_request="Review the disputed transfers reported by the customer.",
        customer_support_statement="The customer states the transfers were not authorized.",
        prior_analyst_note="An earlier analyst noted shared access to the account.",
        datasets=(
            DatasetInventory("visible_entities.csv", 12, ("entity_id", "entity_type")),
            DatasetInventory(
                "visible_events.csv", 40,
                ("event_id", "event_type", "subject_entity_id", "target_entity_id", "occurred_at"),
            ),
        ),
    )


def chained_scenario(scenario_id: str = "test-chain") -> ScenarioDefinition:
    """A three-step chain covering the three V0.5 semantic scenarios."""
    objective = "Assess the disputed transfers without assuming an explanation."
    return ScenarioDefinition(
        scenario_id=scenario_id,
        name="Test chain",
        description="INITIAL then MODIFY then DECLINE_REDIRECT.",
        package_directory=_repository_relative_placeholder(),
        steps=(
            ScenarioStep("initial", "INITIAL", objective),
            ScenarioStep(
                "modify", "MODIFY", objective,
                investigator_instruction=(
                    "Limit the action to visible_events.csv and the 72 hours around the "
                    "disputed transfers."
                ),
            ),
            ScenarioStep(
                "decline-redirect", "DECLINE_REDIRECT", objective,
                decline_guidance="Redirect to relationship structure only.",
            ),
        ),
    )


def _repository_relative_placeholder():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "output" / "development-case-42"


def configuration(label: str = "test-config", model: str = "test-model:1b") -> CandidateConfiguration:
    return CandidateConfiguration(
        label=label,
        ollama=ProposalOllamaConfig(model=model, temperature=0.0, seed=42),
    )


def environment_probe(_: CandidateConfiguration) -> ModelEnvironment:
    return ModelEnvironment(ollama_version="0.34.3", model_digest="digest-abc")


def valid_response_text(marker: str = "one") -> str:
    """A response satisfying the product's contract, with a marker for traceability."""
    return json.dumps({
        "competing_explanations": [
            f"The transfers reflect routine shared access ({marker}).",
            f"An unauthorized party used temporary access ({marker}).",
        ],
        "plan_steps": [
            f"Establish the sequence of login and transfer events ({marker}).",
            f"Compare the counterparties involved across those events ({marker}).",
        ],
        "proposal": {
            "action": f"Retrieve login and transfer event timestamps ({marker}).",
            "purpose": f"Establish whether the timing is consistent with shared access ({marker}).",
            "why_now": f"Timing is the narrowest available discriminator ({marker}).",
            "data_to_be_used": f"visible_events.csv ({marker}).",
            "expected_output": f"A chronological table with a limitations note ({marker}).",
        },
    })


class ScriptedClient:
    """Returns scripted responses in order, counting calls. Never retries anything."""

    def __init__(self, script: Sequence[object]) -> None:
        self._script = list(script)
        self.prompts: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._script:
            raise AssertionError("the scripted client was called more times than scripted")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def transport_failure(
    category: ProposalModelFailureCategory = ProposalModelFailureCategory.SERVICE_UNAVAILABLE,
) -> ProposalModelError:
    return ProposalModelError(category, "local Ollama service is unavailable")


def repeating_script(response_texts: Sequence[object], repetitions: int) -> list[object]:
    """Repeat a chain script for a number of chained repetitions."""
    return [item for _ in range(repetitions) for item in response_texts]
