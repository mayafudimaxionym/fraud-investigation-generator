"""Private canonical ground truth for a generated case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroundTruthManifest:
    """Canonical identifiers and adjudication, never investigator-visible evidence."""

    campaign_ids: tuple[str, ...]
    fraudulent_entity_ids: tuple[str, ...]
    fraudulent_event_ids: tuple[str, ...]
    causal_signal_ids: tuple[str, ...]
    red_herring_ids: tuple[str, ...]
    correct_hypothesis: str

    def __post_init__(self) -> None:
        identifier_groups = {
            "campaign_ids": self.campaign_ids,
            "fraudulent_entity_ids": self.fraudulent_entity_ids,
            "fraudulent_event_ids": self.fraudulent_event_ids,
            "causal_signal_ids": self.causal_signal_ids,
            "red_herring_ids": self.red_herring_ids,
        }
        for field_name, identifiers in identifier_groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if not self.correct_hypothesis.strip():
            raise ValueError("correct_hypothesis must be non-empty")
