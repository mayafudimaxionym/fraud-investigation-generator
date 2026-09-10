"""Validation of canonical fraud-campaign references."""

from __future__ import annotations

from generator.world.model import CanonicalWorld


def validate_campaign_references(world: CanonicalWorld) -> tuple[str, ...]:
    """Return errors for campaign members absent from the canonical world."""
    entity_ids = {entity.entity_id for entity in world.entities}
    event_ids = {event.event_id for event in world.events}
    signal_ids = {signal.signal_id for signal in world.signals}
    errors: list[str] = []

    for campaign in world.campaigns:
        for entity_id in campaign.actor_entity_ids:
            if entity_id not in entity_ids:
                errors.append(f"{campaign.campaign_id}: missing actor {entity_id}")
        for entity_id in campaign.fraudulent_entity_ids:
            if entity_id not in entity_ids:
                errors.append(
                    f"{campaign.campaign_id}: missing fraudulent entity {entity_id}"
                )
        for event_id in campaign.fraudulent_event_ids:
            if event_id not in event_ids:
                errors.append(
                    f"{campaign.campaign_id}: missing fraudulent event {event_id}"
                )
        for signal_id in campaign.causal_signal_ids:
            if signal_id not in signal_ids:
                errors.append(
                    f"{campaign.campaign_id}: missing causal signal {signal_id}"
                )

    return tuple(errors)
