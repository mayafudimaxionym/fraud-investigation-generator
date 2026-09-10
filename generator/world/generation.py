"""Deterministic construction of minimal canonical worlds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from generator.events.models import CanonicalEvent
from generator.scenario.blueprint import CaseBlueprint
from generator.seed import derive_seed
from generator.world.campaigns import FraudCampaign
from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
from generator.world.relationships import CanonicalRelationship
from generator.world.signals import CanonicalSignal


def build_minimal_world(
    blueprint: CaseBlueprint, master_seed: int
) -> CanonicalWorld:
    """Build one valid canonical world unit per declared campaign."""
    world_seed = derive_seed(master_seed, "world")
    base_timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
        seconds=world_seed % 86_400
    )
    entities: list[CanonicalEntity] = []
    relationships: list[CanonicalRelationship] = []
    events: list[CanonicalEvent] = []
    signals: list[CanonicalSignal] = []
    campaigns: list[FraudCampaign] = []

    for campaign_index in range(blueprint.campaign_count):
        suffix = f"{world_seed:016x}-{campaign_index:03d}"
        signal_id = f"signal-{suffix}"
        campaign_id = f"campaign-{suffix}"
        device_id = f"device-{suffix}"
        account_ids: list[str] = []
        event_ids: list[str] = []

        entities.append(CanonicalEntity(device_id, "device"))
        for account_index in range(2):
            account_id = f"account-{suffix}-{account_index:03d}"
            event_id = f"event-{suffix}-{account_index:03d}"
            relationship_id = f"relationship-{suffix}-{account_index:03d}"
            account_ids.append(account_id)
            event_ids.append(event_id)

            entities.append(CanonicalEntity(account_id, "account"))
            relationships.append(
                CanonicalRelationship(
                    relationship_id=relationship_id,
                    source_entity_id=account_id,
                    target_entity_id=device_id,
                    relationship_type="uses_device",
                )
            )
            events.append(
                CanonicalEvent(
                    event_id=event_id,
                    event_type="transfer",
                    subject_entity_id=account_id,
                    occurred_at=base_timestamp
                    + timedelta(seconds=campaign_index * 2 + account_index),
                )
            )
        signals.append(
            CanonicalSignal(
                signal_id=signal_id,
                signal_type="shared_device",
                supporting_entity_ids=tuple(account_ids) + (device_id,),
                supporting_event_ids=tuple(event_ids),
            )
        )
        campaigns.append(
            FraudCampaign(
                campaign_id=campaign_id,
                mechanism=blueprint.scenario.fraud_mechanism,
                actor_entity_ids=(),
                fraudulent_entity_ids=tuple(account_ids) + (device_id,),
                fraudulent_event_ids=tuple(event_ids),
                causal_signal_ids=(signal_id,),
            )
        )

    return CanonicalWorld(
        entities=tuple(entities),
        relationships=tuple(relationships),
        events=tuple(events),
        signals=tuple(signals),
        campaigns=tuple(campaigns),
    )
