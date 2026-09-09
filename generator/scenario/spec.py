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
        if len(self.competing_hypotheses) < 2:
            raise ValueError("competing_hypotheses must contain at least two hypotheses")
        if len(self.competing_hypotheses) != len(set(self.competing_hypotheses)):
            raise ValueError("competing_hypotheses must not contain duplicates")
        if any(not hypothesis.strip() for hypothesis in self.competing_hypotheses):
            raise ValueError("competing_hypotheses must not contain blank values")

    def to_dict(self) -> dict[str, object]:
        """Return the declarative scenario in a JSON-compatible form."""
        return {
            "domain": self.domain,
            "scale": self.scale,
            "fraud_mechanism": self.fraud_mechanism,
            "competing_hypotheses": list(self.competing_hypotheses),
            "required_signals": list(self.required_signals),
            "required_artifacts": list(self.required_artifacts),
        }
