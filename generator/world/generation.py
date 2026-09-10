"""Deterministic construction of minimal canonical worlds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from generator.events.models import CanonicalEvent
from generator.scenario.blueprint import CaseBlueprint
from generator.seed import derive_seed
from generator.world.campaigns import FraudCampaign
from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
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
    events: list[CanonicalEvent] = []
    signals: list[CanonicalSignal] = []
    campaigns: list[FraudCampaign] = []

    for campaign_index in range(blueprint.campaign_count):
        suffix = f"{world_seed:016x}-{campaign_index:03d}"
        account_id = f"account-{suffix}"
        event_id = f"event-{suffix}"
        signal_id = f"signal-{suffix}"
        campaign_id = f"campaign-{suffix}"

        entities.append(CanonicalEntity(account_id, "account"))
        events.append(
            CanonicalEvent(
                event_id=event_id,
                event_type="transfer",
                subject_entity_id=account_id,
                occurred_at=base_timestamp + timedelta(seconds=campaign_index),
            )
        )
        signals.append(
            CanonicalSignal(
                signal_id=signal_id,
                signal_type="temporal_cluster",
                supporting_entity_ids=(account_id,),
                supporting_event_ids=(event_id,),
            )
        )
        campaigns.append(
            FraudCampaign(
                campaign_id=campaign_id,
                mechanism=blueprint.scenario.fraud_mechanism,
                actor_entity_ids=(),
                fraudulent_entity_ids=(account_id,),
                fraudulent_event_ids=(event_id,),
                causal_signal_ids=(signal_id,),
            )
        )

    return CanonicalWorld(
        entities=tuple(entities),
        relationships=(),
        events=tuple(events),
        signals=tuple(signals),
        campaigns=tuple(campaigns),
    )
