"""Deterministic construction of minimal canonical worlds."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from generator.artifacts.manifest import InvestigatorViewManifest
from generator.case import CanonicalCase
from generator.events.models import CanonicalEvent
from generator.metadata import GenerationMetadata
from generator.scenario.blueprint import CaseBlueprint
from generator.seed import derive_seed
from generator.world.campaigns import FraudCampaign
from generator.world.entities import CanonicalEntity
from generator.world.model import CanonicalWorld
from generator.world.relationships import CanonicalRelationship
from generator.world.signals import CanonicalSignal
from generator.world.truth import GroundTruthManifest


def build_minimal_world(
    blueprint: CaseBlueprint, master_seed: int
) -> CanonicalWorld:
    """Build a small deterministic investigation population around fraud campaigns."""
    world_seed = derive_seed(master_seed, "world")
    base_timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
        seconds=world_seed % 86_400
    )
    entities: list[CanonicalEntity] = []
    relationships: list[CanonicalRelationship] = []
    events: list[CanonicalEvent] = []
    signals: list[CanonicalSignal] = []
    campaigns: list[FraudCampaign] = []

    def add_entity(entity_type: str) -> str:
        entity_id = _opaque_identifier("entity", world_seed, len(entities))
        entities.append(CanonicalEntity(entity_id, entity_type))
        return entity_id

    def add_relationship(
        source_entity_id: str, target_entity_id: str, relationship_type: str
    ) -> str:
        relationship_id = _opaque_identifier(
            "relationship", world_seed, len(relationships)
        )
        relationships.append(
            CanonicalRelationship(
                relationship_id=relationship_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relationship_type=relationship_type,
            )
        )
        return relationship_id

    def add_login_transfer(
        account_id: str,
        beneficiary_id: str,
        login_timestamp: datetime,
        transfer_delay: timedelta,
    ) -> tuple[str, str]:
        login_event_id = _opaque_identifier("event", world_seed, len(events))
        transfer_event_id = _opaque_identifier("event", world_seed, len(events) + 1)
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
                occurred_at=login_timestamp + transfer_delay,
                target_entity_id=beneficiary_id,
            )
        )
        return login_event_id, transfer_event_id

    def add_signal(
        signal_type: str,
        supporting_entity_ids: tuple[str, ...],
        supporting_event_ids: tuple[str, ...],
        *,
        is_red_herring: bool = False,
    ) -> str:
        signal_id = _opaque_identifier("signal", world_seed, len(signals))
        signals.append(
            CanonicalSignal(
                signal_id=signal_id,
                signal_type=signal_type,
                supporting_entity_ids=supporting_entity_ids,
                supporting_event_ids=supporting_event_ids,
                is_red_herring=is_red_herring,
            )
        )
        return signal_id

    shared_network_id = add_entity("network")

    for campaign_index in range(blueprint.campaign_count):
        suffix = f"{world_seed:016x}-{campaign_index:03d}"
        campaign_id = f"campaign-{suffix}"
        device_id = add_entity("device")
        beneficiary_id = add_entity("beneficiary")
        account_ids: list[str] = []
        suspicious_event_ids: list[str] = []
        transfer_event_ids: list[str] = []
        campaign_timestamp = base_timestamp + timedelta(
            hours=campaign_index * 6,
            minutes=(world_seed >> (campaign_index * 5)) % 30,
        )
        login_spacing_seconds = 1 + (world_seed >> (campaign_index * 7)) % 15
        fast_account_index = (world_seed >> (campaign_index * 3)) % 2
        fast_delay_seconds = 20 + (world_seed >> (campaign_index * 11)) % 41
        slow_delay_minutes = 8 + (world_seed >> (campaign_index * 13)) % 13

        add_relationship(device_id, shared_network_id, "uses_network")
        for account_index in range(2):
            account_id = add_entity("account")
            history_beneficiary_id = add_entity("beneficiary")
            login_timestamp = campaign_timestamp + timedelta(
                seconds=account_index * login_spacing_seconds
            )
            account_ids.append(account_id)
            add_relationship(account_id, device_id, "uses_device")
            add_relationship(account_id, beneficiary_id, "transfers_to")
            add_relationship(account_id, history_beneficiary_id, "transfers_to")
            add_login_transfer(
                account_id,
                history_beneficiary_id,
                campaign_timestamp
                - timedelta(days=14 + campaign_index * 2 + account_index),
                timedelta(minutes=20 + (world_seed >> (account_index * 9)) % 90),
            )
            suspicious_login_id, suspicious_transfer_id = add_login_transfer(
                account_id,
                beneficiary_id,
                login_timestamp,
                timedelta(
                    seconds=fast_delay_seconds
                    if account_index == fast_account_index
                    else slow_delay_minutes * 60
                ),
            )
            suspicious_event_ids.extend(
                (suspicious_login_id, suspicious_transfer_id)
            )
            transfer_event_ids.append(suspicious_transfer_id)
        device_signal_id = add_signal(
            "shared_device_login_transfer",
            tuple(account_ids) + (device_id,),
            tuple(suspicious_event_ids),
        )
        beneficiary_signal_id = add_signal(
            "shared_beneficiary",
            tuple(account_ids) + (beneficiary_id,),
            tuple(transfer_event_ids),
        )
        network_signal_id = add_signal(
            "shared_network_infrastructure",
            (device_id, shared_network_id),
            (),
        )
        campaigns.append(
            FraudCampaign(
                campaign_id=campaign_id,
                mechanism=blueprint.scenario.fraud_mechanism,
                actor_entity_ids=(),
                fraudulent_entity_ids=tuple(account_ids)
                + (device_id, beneficiary_id, shared_network_id),
                fraudulent_event_ids=tuple(suspicious_event_ids),
                causal_signal_ids=(
                    device_signal_id,
                    beneficiary_signal_id,
                    network_signal_id,
                ),
            )
        )

    lookalike_device_id = add_entity("device")
    lookalike_beneficiary_id = add_entity("beneficiary")
    lookalike_timestamp = base_timestamp + timedelta(days=3)
    lookalike_account_ids: list[str] = []
    lookalike_event_ids: list[str] = []
    add_relationship(lookalike_device_id, shared_network_id, "uses_network")
    for account_index in range(2):
        account_id = add_entity("account")
        login_timestamp = lookalike_timestamp + timedelta(
            minutes=account_index * (25 + world_seed % 20)
        )
        lookalike_account_ids.append(account_id)
        add_relationship(account_id, lookalike_device_id, "uses_device")
        add_relationship(account_id, lookalike_beneficiary_id, "transfers_to")
        add_login_transfer(
            account_id,
            lookalike_beneficiary_id,
            lookalike_timestamp - timedelta(days=10 + account_index),
            timedelta(minutes=35 + account_index * 15),
        )
        login_event_id, transfer_event_id = add_login_transfer(
            account_id,
            lookalike_beneficiary_id,
            login_timestamp,
            timedelta(seconds=25 + world_seed % 31)
            if account_index == 0
            else timedelta(minutes=8 + (world_seed >> 8) % 13),
        )
        lookalike_event_ids.extend((login_event_id, transfer_event_id))
    add_signal(
        "shared_device_login_transfer",
        tuple(lookalike_account_ids)
        + (lookalike_device_id, lookalike_beneficiary_id),
        tuple(lookalike_event_ids),
        is_red_herring=True,
    )

    background_beneficiary_ids = [add_entity("beneficiary") for _ in range(18)]
    shared_background_devices: dict[int, str] = {}
    shared_background_accounts: dict[int, list[str]] = {}
    shared_background_events: dict[int, list[str]] = {}
    for account_index in range(44):
        shared_group = account_index // 2 if account_index in {
            0,
            1,
            12,
            13,
            24,
            25,
            36,
            37,
        } else None
        if shared_group is None:
            device_id = add_entity("device")
        else:
            if shared_group not in shared_background_devices:
                shared_background_devices[shared_group] = add_entity("device")
            device_id = shared_background_devices[shared_group]
        account_id = add_entity("account")
        primary_beneficiary_id = background_beneficiary_ids[
            (account_index * 3 + world_seed) % len(background_beneficiary_ids)
        ]
        secondary_beneficiary_id = background_beneficiary_ids[
            (account_index * 7 + (world_seed >> 5) + 1)
            % len(background_beneficiary_ids)
        ]
        if secondary_beneficiary_id == primary_beneficiary_id:
            secondary_beneficiary_id = background_beneficiary_ids[
                (background_beneficiary_ids.index(primary_beneficiary_id) + 1)
                % len(background_beneficiary_ids)
            ]
        add_relationship(account_id, device_id, "uses_device")
        add_relationship(account_id, primary_beneficiary_id, "transfers_to")
        add_relationship(account_id, secondary_beneficiary_id, "transfers_to")
        history_timestamp = base_timestamp - timedelta(days=30) + timedelta(
            days=account_index % 20,
            minutes=(world_seed >> (account_index % 16)) % 600,
        )
        first_delay = (
            timedelta(seconds=20 + (world_seed >> (account_index % 20)) % 41)
            if account_index % 13 == 0
            else timedelta(minutes=5 + (world_seed >> (account_index % 18)) % 116)
        )
        first_login_id, first_transfer_id = add_login_transfer(
            account_id,
            primary_beneficiary_id,
            history_timestamp,
            first_delay,
        )
        second_login_id, second_transfer_id = add_login_transfer(
            account_id,
            secondary_beneficiary_id,
            history_timestamp + timedelta(days=1 + account_index % 4),
            timedelta(minutes=10 + (world_seed >> (account_index % 22)) % 171),
        )
        if shared_group is not None:
            shared_background_accounts.setdefault(shared_group, []).append(account_id)
            shared_background_events.setdefault(shared_group, []).extend(
                (first_login_id, first_transfer_id, second_login_id, second_transfer_id)
            )

    first_shared_group = min(shared_background_devices)
    add_signal(
        "shared_device_activity",
        tuple(shared_background_accounts[first_shared_group])
        + (shared_background_devices[first_shared_group],),
        tuple(shared_background_events[first_shared_group]),
    )

    return CanonicalWorld(
        entities=tuple(entities),
        relationships=tuple(relationships),
        events=tuple(events),
        signals=tuple(signals),
        campaigns=tuple(campaigns),
    )


def build_ground_truth_manifest(
    blueprint: CaseBlueprint, world: CanonicalWorld
) -> GroundTruthManifest:
    """Assemble private ground truth from canonical campaign membership."""
    causal_signal_ids = _stable_unique(
        campaign.causal_signal_ids for campaign in world.campaigns
    )
    return GroundTruthManifest(
        campaign_ids=tuple(campaign.campaign_id for campaign in world.campaigns),
        fraudulent_entity_ids=_stable_unique(
            campaign.fraudulent_entity_ids for campaign in world.campaigns
        ),
        fraudulent_event_ids=_stable_unique(
            campaign.fraudulent_event_ids for campaign in world.campaigns
        ),
        causal_signal_ids=causal_signal_ids,
        red_herring_ids=tuple(
            signal.signal_id
            for signal in world.signals
            if signal.is_red_herring and signal.signal_id not in causal_signal_ids
        ),
        correct_hypothesis=blueprint.correct_hypothesis,
    )


def build_investigator_view_manifest(
    world: CanonicalWorld,
) -> InvestigatorViewManifest:
    """Expose all raw canonical-world evidence without fraud adjudication."""
    return InvestigatorViewManifest(
        visible_entity_ids=tuple(entity.entity_id for entity in world.entities),
        visible_event_ids=tuple(event.event_id for event in world.events),
        artifact_ids=(),
        visible_relationship_ids=tuple(
            relationship.relationship_id for relationship in world.relationships
        ),
    )


def build_canonical_case(
    case_id: str,
    blueprint: CaseBlueprint,
    metadata: GenerationMetadata,
) -> CanonicalCase:
    """Compose a complete in-memory case from existing deterministic builders."""
    world = build_minimal_world(blueprint, metadata.master_seed)
    return CanonicalCase(
        case_id=case_id,
        metadata=metadata,
        scenario=blueprint.scenario,
        world=world,
        ground_truth=build_ground_truth_manifest(blueprint, world),
        investigator_view=build_investigator_view_manifest(world),
        artifacts=(),
    )


def _stable_unique(identifier_groups: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Return identifiers in first-seen order without duplicates."""
    seen: set[str] = set()
    identifiers: list[str] = []
    for group in identifier_groups:
        for identifier in group:
            if identifier not in seen:
                seen.add(identifier)
                identifiers.append(identifier)
    return tuple(identifiers)


def _opaque_identifier(prefix: str, world_seed: int, index: int) -> str:
    """Build a deterministic identifier without interpretive role labels."""
    return f"{prefix}-{world_seed:016x}-{index:03d}"
