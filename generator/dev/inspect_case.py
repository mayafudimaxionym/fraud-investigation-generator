"""Development-only CSV export for manually inspecting one generated case."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from generator.case import CanonicalCase
from generator.events.models import CanonicalEvent
from generator.metadata import GenerationMetadata
from generator.scenario.blueprint import CaseBlueprint
from generator.scenario.spec import ScenarioSpec
from generator.world.generation import build_canonical_case

DEVELOPMENT_CASE_ID = "development-case-42"
DEVELOPMENT_MASTER_SEED = 42


def build_development_case() -> CanonicalCase:
    """Build the fixed case used only for local development inspection."""
    blueprint = CaseBlueprint(
        scenario=ScenarioSpec(
            domain="payments",
            scale="small",
            fraud_mechanism="account takeover",
            competing_hypotheses=("account takeover", "merchant dispute abuse"),
            required_signals=("temporal",),
            required_artifacts=("client email",),
        ),
        correct_hypothesis="account takeover",
        campaign_count=2,
    )
    metadata = GenerationMetadata(
        master_seed=DEVELOPMENT_MASTER_SEED,
        generator_version="0.1.0",
        scenario_version="1",
        schema_version="1",
    )
    return build_canonical_case(DEVELOPMENT_CASE_ID, blueprint, metadata)


def export_development_case(output_root: Path) -> Path:
    """Write development-only inspection CSVs and return the case directory."""
    return export_case_for_inspection(build_development_case(), output_root)


def export_case_for_inspection(case: CanonicalCase, output_root: Path) -> Path:
    """Write a supplied in-memory case for local inspection only."""
    case_directory = output_root / case.case_id
    internal_directory = case_directory / "internal"
    investigator_directory = case_directory / "investigator_view"
    internal_directory.mkdir(parents=True, exist_ok=True)
    investigator_directory.mkdir(parents=True, exist_ok=True)

    _write_csv(
        internal_directory / "entities.csv",
        ("entity_id", "entity_type"),
        (
            {"entity_id": entity.entity_id, "entity_type": entity.entity_type}
            for entity in case.world.entities
        ),
    )
    _write_csv(
        internal_directory / "relationships.csv",
        (
            "relationship_id",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
        ),
        (
            {
                "relationship_id": relationship.relationship_id,
                "source_entity_id": relationship.source_entity_id,
                "target_entity_id": relationship.target_entity_id,
                "relationship_type": relationship.relationship_type,
            }
            for relationship in case.world.relationships
        ),
    )
    _write_csv(
        internal_directory / "events.csv",
        (
            "event_id",
            "event_type",
            "subject_entity_id",
            "target_entity_id",
            "occurred_at",
        ),
        (_event_row(event) for event in case.world.events),
    )
    _write_csv(
        internal_directory / "signals.csv",
        (
            "signal_id",
            "signal_type",
            "supporting_entity_ids",
            "supporting_event_ids",
        ),
        (
            {
                "signal_id": signal.signal_id,
                "signal_type": signal.signal_type,
                "supporting_entity_ids": _json_array(signal.supporting_entity_ids),
                "supporting_event_ids": _json_array(signal.supporting_event_ids),
            }
            for signal in case.world.signals
        ),
    )
    _write_csv(
        internal_directory / "campaigns.csv",
        (
            "campaign_id",
            "mechanism",
            "actor_entity_ids",
            "fraudulent_entity_ids",
            "fraudulent_event_ids",
            "causal_signal_ids",
        ),
        (
            {
                "campaign_id": campaign.campaign_id,
                "mechanism": campaign.mechanism,
                "actor_entity_ids": _json_array(campaign.actor_entity_ids),
                "fraudulent_entity_ids": _json_array(campaign.fraudulent_entity_ids),
                "fraudulent_event_ids": _json_array(campaign.fraudulent_event_ids),
                "causal_signal_ids": _json_array(campaign.causal_signal_ids),
            }
            for campaign in case.world.campaigns
        ),
    )
    _write_csv(
        internal_directory / "ground_truth.csv",
        ("field", "value"),
        (
            {"field": "campaign_ids", "value": _json_array(case.ground_truth.campaign_ids)},
            {
                "field": "fraudulent_entity_ids",
                "value": _json_array(case.ground_truth.fraudulent_entity_ids),
            },
            {
                "field": "fraudulent_event_ids",
                "value": _json_array(case.ground_truth.fraudulent_event_ids),
            },
            {
                "field": "causal_signal_ids",
                "value": _json_array(case.ground_truth.causal_signal_ids),
            },
            {
                "field": "red_herring_ids",
                "value": _json_array(case.ground_truth.red_herring_ids),
            },
            {
                "field": "correct_hypothesis",
                "value": case.ground_truth.correct_hypothesis,
            },
        ),
    )

    entities_by_id = {entity.entity_id: entity for entity in case.world.entities}
    relationships_by_id = {
        relationship.relationship_id: relationship
        for relationship in case.world.relationships
    }
    events_by_id = {event.event_id: event for event in case.world.events}
    _write_csv(
        investigator_directory / "visible_entities.csv",
        ("entity_id", "entity_type"),
        (
            {
                "entity_id": entities_by_id[entity_id].entity_id,
                "entity_type": entities_by_id[entity_id].entity_type,
            }
            for entity_id in case.investigator_view.visible_entity_ids
        ),
    )
    _write_csv(
        investigator_directory / "visible_relationships.csv",
        (
            "relationship_id",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
        ),
        (
            {
                "relationship_id": relationships_by_id[relationship_id].relationship_id,
                "source_entity_id": relationships_by_id[relationship_id].source_entity_id,
                "target_entity_id": relationships_by_id[relationship_id].target_entity_id,
                "relationship_type": relationships_by_id[relationship_id].relationship_type,
            }
            for relationship_id in case.investigator_view.visible_relationship_ids
        ),
    )
    _write_csv(
        investigator_directory / "visible_events.csv",
        (
            "event_id",
            "event_type",
            "subject_entity_id",
            "target_entity_id",
            "occurred_at",
        ),
        (
            _event_row(events_by_id[event_id])
            for event_id in case.investigator_view.visible_event_ids
        ),
    )
    return case_directory


def _event_row(event: CanonicalEvent) -> dict[str, str]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "subject_entity_id": event.subject_entity_id,
        "target_entity_id": event.target_entity_id or "",
        "occurred_at": event.occurred_at.isoformat(),
    }


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: Iterable[Mapping[str, str]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Export the fixed inspection case beneath the local output directory."""
    case_directory = export_development_case(Path("output"))
    print(case_directory)


if __name__ == "__main__":
    main()
