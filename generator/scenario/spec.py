"""Scenario intent contract, independent of generated case data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioSpec:
    """Describe a fraud mechanism and investigation design constraints."""

    domain: str
    scale: str
    fraud_mechanism: str
    competing_hypotheses: tuple[str, ...]
    required_signals: tuple[str, ...]
    required_artifacts: tuple[str, ...]

    def __post_init__(self) -> None:
        required_text = {
            "domain": self.domain,
            "scale": self.scale,
            "fraud_mechanism": self.fraud_mechanism,
        }
        for field_name, value in required_text.items():
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
