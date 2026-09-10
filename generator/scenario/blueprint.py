"""Private Python-owned truth constraints for deterministic case generation."""

from __future__ import annotations

from dataclasses import dataclass

from generator.scenario.spec import ScenarioSpec


@dataclass(frozen=True)
class CaseBlueprint:
    """Declare intended truth constraints before canonical world generation."""

    scenario: ScenarioSpec
    correct_hypothesis: str
    campaign_count: int

    def __post_init__(self) -> None:
        if self.correct_hypothesis not in self.scenario.competing_hypotheses:
            raise ValueError(
                "correct_hypothesis must be declared in competing_hypotheses"
            )
        if self.campaign_count <= 0:
            raise ValueError("campaign_count must be greater than zero")
