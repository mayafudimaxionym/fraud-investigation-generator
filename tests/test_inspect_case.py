import csv
import json
from pathlib import Path

from generator.dev.inspect_case import build_development_case, export_development_case


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_development_case_export_writes_expected_layout_and_is_reproducible(
    tmp_path: Path,
) -> None:
    first_case_directory = export_development_case(tmp_path / "first")
    second_case_directory = export_development_case(tmp_path / "second")
    expected_files = {
        Path("internal/entities.csv"),
        Path("internal/relationships.csv"),
        Path("internal/events.csv"),
        Path("internal/signals.csv"),
        Path("internal/campaigns.csv"),
        Path("internal/ground_truth.csv"),
        Path("investigator_view/visible_entities.csv"),
        Path("investigator_view/visible_relationships.csv"),
        Path("investigator_view/visible_events.csv"),
    }

    assert first_case_directory.name == "development-case-42"
    assert {
        path.relative_to(first_case_directory)
        for path in first_case_directory.rglob("*.csv")
    } == expected_files
    for relative_path in expected_files:
        assert (first_case_directory / relative_path).read_bytes() == (
            second_case_directory / relative_path
        ).read_bytes()


def test_development_case_export_matches_visible_selection_without_truth_leakage(
    tmp_path: Path,
) -> None:
    case = build_development_case()
    case_directory = export_development_case(tmp_path)
    visible_directory = case_directory / "investigator_view"
    entity_rows = _read_rows(visible_directory / "visible_entities.csv")
    relationship_rows = _read_rows(visible_directory / "visible_relationships.csv")
    event_rows = _read_rows(visible_directory / "visible_events.csv")
    visible_content = "\n".join(
        path.read_text(encoding="utf-8") for path in visible_directory.glob("*.csv")
    )
    private_ids = (
        set(case.ground_truth.campaign_ids)
        | set(case.ground_truth.causal_signal_ids)
        | set(case.ground_truth.red_herring_ids)
    )

    assert [row["entity_id"] for row in entity_rows] == list(
        case.investigator_view.visible_entity_ids
    )
    assert [row["relationship_id"] for row in relationship_rows] == list(
        case.investigator_view.visible_relationship_ids
    )
    assert [row["event_id"] for row in event_rows] == list(
        case.investigator_view.visible_event_ids
    )
    assert set(entity_rows[0]) == {"entity_id", "entity_type"}
    assert set(relationship_rows[0]) == {
        "relationship_id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
    }
    assert set(event_rows[0]) == {
        "event_id",
        "event_type",
        "subject_entity_id",
        "target_entity_id",
        "occurred_at",
    }
    assert "campaign_id" not in visible_content
    assert "causal_signal_ids" not in visible_content
    assert "red_herring_ids" not in visible_content
    assert "correct_hypothesis" not in visible_content
    assert case.ground_truth.correct_hypothesis not in visible_content
    assert all(private_id not in visible_content for private_id in private_ids)


def test_development_case_export_includes_internal_ground_truth_records(
    tmp_path: Path,
) -> None:
    case = build_development_case()
    case_directory = export_development_case(tmp_path)
    entity_rows = _read_rows(case_directory / "internal/entities.csv")
    relationship_rows = _read_rows(case_directory / "internal/relationships.csv")
    event_rows = _read_rows(case_directory / "internal/events.csv")
    signal_rows = _read_rows(case_directory / "internal/signals.csv")
    campaign_rows = _read_rows(case_directory / "internal/campaigns.csv")
    ground_truth_rows = _read_rows(case_directory / "internal/ground_truth.csv")
    ground_truth_by_field = {
        row["field"]: row["value"] for row in ground_truth_rows
    }

    assert [row["entity_id"] for row in entity_rows] == [
        entity.entity_id for entity in case.world.entities
    ]
    assert [row["relationship_id"] for row in relationship_rows] == [
        relationship.relationship_id for relationship in case.world.relationships
    ]
    assert [row["event_id"] for row in event_rows] == [
        event.event_id for event in case.world.events
    ]
    assert [row["signal_id"] for row in signal_rows] == [
        signal.signal_id for signal in case.world.signals
    ]
    assert [row["campaign_id"] for row in campaign_rows] == [
        campaign.campaign_id for campaign in case.world.campaigns
    ]
    assert json.loads(ground_truth_by_field["campaign_ids"]) == list(
        case.ground_truth.campaign_ids
    )
    assert ground_truth_by_field["correct_hypothesis"] == (
        case.ground_truth.correct_hypothesis
    )
