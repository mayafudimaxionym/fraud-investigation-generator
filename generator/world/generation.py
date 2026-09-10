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
    login_spacing_seconds = 1 + world_seed % 15
    shared_slow_transfer_delay_minutes = 8 + (world_seed >> 8) % 13

    for campaign_index in range(blueprint.campaign_count):
        suffix = f"{world_seed:016x}-{campaign_index:03d}"
        signal_id = f"signal-{suffix}"
        beneficiary_signal_id = f"signal-beneficiary-{suffix}"
        campaign_id = f"campaign-{suffix}"
        device_id = f"device-{suffix}"
        beneficiary_id = f"beneficiary-{suffix}"
        account_ids: list[str] = []
        event_ids: list[str] = []
        transfer_event_ids: list[str] = []
        campaign_timestamp = base_timestamp + timedelta(minutes=campaign_index * 5)

        entities.append(CanonicalEntity(device_id, "device"))
        entities.append(CanonicalEntity(beneficiary_id, "beneficiary"))
        for account_index in range(2):
            account_id = f"account-{suffix}-{account_index:03d}"
            login_event_id = f"login-{suffix}-{account_index:03d}"
            transfer_event_id = f"transfer-{suffix}-{account_index:03d}"
            relationship_id = f"relationship-{suffix}-{account_index:03d}"
            beneficiary_relationship_id = (
                f"relationship-beneficiary-{suffix}-{account_index:03d}"
            )
            login_timestamp = campaign_timestamp + timedelta(
                seconds=account_index * login_spacing_seconds
            )
            account_ids.append(account_id)
            event_ids.extend((login_event_id, transfer_event_id))
            transfer_event_ids.append(transfer_event_id)

            entities.append(CanonicalEntity(account_id, "account"))
            relationships.append(
                CanonicalRelationship(
                    relationship_id=relationship_id,
                    source_entity_id=account_id,
                    target_entity_id=device_id,
                    relationship_type="uses_device",
                )
            )
            relationships.append(
                CanonicalRelationship(
                    relationship_id=beneficiary_relationship_id,
                    source_entity_id=account_id,
                    target_entity_id=beneficiary_id,
                    relationship_type="transfers_to",
                )
            )
            events.append(
                CanonicalEvent(
                    event_id=login_event_id,
                    event_type="login",
                    subject_entity_id=account_id,
                    occurred_at=login_timestamp,
                )
            )
            events.append(
                CanonicalEvent(
                    event_id=transfer_event_id,
                    event_type="transfer",
                    subject_entity_id=account_id,
                    occurred_at=login_timestamp
                    + timedelta(
                        seconds=30
                        if account_index == 0
                        else shared_slow_transfer_delay_minutes * 60
                    ),
                    target_entity_id=beneficiary_id,
                )
            )
        signals.append(
            CanonicalSignal(
                signal_id=signal_id,
                signal_type="shared_device_login_transfer",
                supporting_entity_ids=tuple(account_ids) + (device_id,),
                supporting_event_ids=tuple(event_ids),
            )
        )
        signals.append(
            CanonicalSignal(
                signal_id=beneficiary_signal_id,
                signal_type="shared_beneficiary",
                supporting_entity_ids=tuple(account_ids) + (beneficiary_id,),
                supporting_event_ids=tuple(transfer_event_ids),
            )
        )
        campaigns.append(
            FraudCampaign(
                campaign_id=campaign_id,
                mechanism=blueprint.scenario.fraud_mechanism,
                actor_entity_ids=(),
                fraudulent_entity_ids=tuple(account_ids) + (device_id, beneficiary_id),
                fraudulent_event_ids=tuple(event_ids),
                causal_signal_ids=(signal_id, beneficiary_signal_id),
            )
        )

    lookalike_suffix = f"{world_seed:016x}"
    lookalike_device_id = f"device-lookalike-{lookalike_suffix}"
    lookalike_signal_id = f"signal-lookalike-{lookalike_suffix}"
    lookalike_timestamp = base_timestamp + timedelta(
        minutes=blueprint.campaign_count * 5 + 5
    )
    lookalike_account_ids: list[str] = []
    lookalike_event_ids: list[str] = []

    entities.append(CanonicalEntity(lookalike_device_id, "device"))
    for account_index in range(2):
        account_id = f"account-lookalike-{lookalike_suffix}-{account_index:03d}"
        login_event_id = f"login-lookalike-{lookalike_suffix}-{account_index:03d}"
        transfer_event_id = (
            f"transfer-lookalike-{lookalike_suffix}-{account_index:03d}"
        )
        relationship_id = (
            f"relationship-lookalike-{lookalike_suffix}-{account_index:03d}"
        )
        beneficiary_id = (
            f"beneficiary-lookalike-{lookalike_suffix}-{account_index:03d}"
        )
        beneficiary_relationship_id = (
            f"relationship-beneficiary-lookalike-{lookalike_suffix}-{account_index:03d}"
        )
        login_timestamp = lookalike_timestamp + timedelta(
            seconds=account_index * login_spacing_seconds
        )
        transfer_delay_minutes = (
            8 + world_seed % 13
            if account_index == 0
            else shared_slow_transfer_delay_minutes
        )
        lookalike_account_ids.append(account_id)
        lookalike_event_ids.extend((login_event_id, transfer_event_id))

        entities.append(CanonicalEntity(account_id, "account"))
        entities.append(CanonicalEntity(beneficiary_id, "beneficiary"))
        relationships.append(
            CanonicalRelationship(
                relationship_id=relationship_id,
                source_entity_id=account_id,
                target_entity_id=lookalike_device_id,
                relationship_type="uses_device",
            )
        )
        relationships.append(
            CanonicalRelationship(
                relationship_id=beneficiary_relationship_id,
                source_entity_id=account_id,
                target_entity_id=beneficiary_id,
                relationship_type="transfers_to",
            )
        )
        events.append(
            CanonicalEvent(
                event_id=login_event_id,
                event_type="login",
                subject_entity_id=account_id,
                occurred_at=login_timestamp,
            )
        )
        events.append(
            CanonicalEvent(
                event_id=transfer_event_id,
                event_type="transfer",
                subject_entity_id=account_id,
                occurred_at=login_timestamp
                + timedelta(minutes=transfer_delay_minutes),
                target_entity_id=beneficiary_id,
            )
        )
    signals.append(
        CanonicalSignal(
            signal_id=lookalike_signal_id,
            signal_type="shared_device_login_transfer",
            supporting_entity_ids=tuple(lookalike_account_ids)
            + (lookalike_device_id,),
            supporting_event_ids=tuple(lookalike_event_ids),
        )
    )

    return CanonicalWorld(
        entities=tuple(entities),
        relationships=tuple(relationships),
        events=tuple(events),
        signals=tuple(signals),
        campaigns=tuple(campaigns),
    )
