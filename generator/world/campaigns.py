"""Private canonical fraud campaigns in a generated case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FraudCampaign:
    """Canonical campaign membership and mechanism, never investigator-visible."""

    campaign_id: str
    mechanism: str
    actor_entity_ids: tuple[str, ...]
    fraudulent_entity_ids: tuple[str, ...]
    fraudulent_event_ids: tuple[str, ...]
    causal_signal_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise ValueError("campaign_id must be non-empty")
        if not self.mechanism.strip():
            raise ValueError("mechanism must be non-empty")
        identifier_groups = {
            "actor_entity_ids": self.actor_entity_ids,
            "fraudulent_entity_ids": self.fraudulent_entity_ids,
            "fraudulent_event_ids": self.fraudulent_event_ids,
            "causal_signal_ids": self.causal_signal_ids,
        }
        for field_name, identifiers in identifier_groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if not self.fraudulent_entity_ids and not self.fraudulent_event_ids:
            raise ValueError(
                "a campaign must reference a fraudulent entity or fraudulent event"
            )
