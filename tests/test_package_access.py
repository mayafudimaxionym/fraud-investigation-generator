import csv
from pathlib import Path

import pytest

from generator.dev.package_case import export_development_investigation_package
from investigation.package_access import _authorized_file, load_investigator_package


EXPECTED_DATASETS = (
    ("visible_entities.csv", ("entity_id", "entity_type")),
    (
        "visible_relationships.csv",
        (
            "relationship_id",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
        ),
    ),
    (
        "visible_events.csv",
        (
            "event_id",
            "event_type",
            "subject_entity_id",
            "target_entity_id",
            "occurred_at",
        ),
    ),
)


def _package(tmp_path: Path) -> Path:
    return export_development_investigation_package(tmp_path)


def test_loads_the_frozen_development_package_with_all_authorized_context(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)

    context = load_investigator_package(package)

    assert context.investigation_request == (
        package / "investigator/context/investigation_request.txt"
    ).read_text(encoding="utf-8")
    assert context.customer_support_statement == (
        package / "investigator/context/customer_support.txt"
    ).read_text(encoding="utf-8")
    assert context.prior_analyst_note == (
        package / "investigator/context/prior_analyst_note.txt"
    ).read_text(encoding="utf-8")


def test_returns_only_safe_inventory_for_each_visible_dataset(tmp_path: Path) -> None:
    package = _package(tmp_path)

    context = load_investigator_package(package)

    assert tuple(
        (dataset.dataset_name, dataset.field_names) for dataset in context.datasets
    ) == EXPECTED_DATASETS
    assert tuple(dataset.row_count for dataset in context.datasets) == (119, 151, 200)
    raw_csv = (package / "investigator/data/visible_entities.csv").read_text(
        encoding="utf-8"
    )
    assert raw_csv not in repr(context)
    assert not hasattr(context, "rows")


def test_individual_structured_row_values_do_not_enter_agent_context(tmp_path: Path) -> None:
    package = _package(tmp_path)
    marker = "UNIQUE-STRUCTURED-ROW-MARKER"
    entity_file = package / "investigator/data/visible_entities.csv"
    with entity_file.open("a", encoding="utf-8", newline="") as csv_file:
        csv.writer(csv_file).writerow((marker, "account"))

    context = load_investigator_package(package)

    assert context.datasets[0].dataset_name == "visible_entities.csv"
    assert context.datasets[0].row_count == 120
    assert marker not in repr(context)


def test_evaluator_only_content_cannot_enter_agent_context(tmp_path: Path) -> None:
    package = _package(tmp_path)
    marker = "EVALUATOR-ONLY-SECRET"
    (package / "evaluator_only/marker.txt").write_text(marker, encoding="utf-8")

    context = load_investigator_package(package)

    assert marker not in repr(context)
    assert "evaluator_only" not in repr(context)


def test_missing_investigator_content_does_not_fall_back_to_evaluator_only(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    request = package / "investigator/context/investigation_request.txt"
    request.unlink()
    (package / "evaluator_only/investigation_request.txt").write_text(
        "private replacement", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="required investigator package content"):
        load_investigator_package(package)


def test_missing_or_malformed_required_investigator_content_fails_safely(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    (package / "investigator/context/customer_support.txt").unlink()

    with pytest.raises(ValueError, match="required investigator package content"):
        load_investigator_package(package)

    package = _package(tmp_path / "malformed")
    (package / "investigator/data/visible_events.csv").write_text(
        "wrong,headers\nvalue,only\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unexpected headers"):
        load_investigator_package(package)


def test_authorized_paths_cannot_escape_investigator_tree(tmp_path: Path) -> None:
    package = _package(tmp_path)
    investigator_directory = (package / "investigator").resolve()

    with pytest.raises(ValueError, match="escapes the permitted tree"):
        _authorized_file(
            investigator_directory, Path("../evaluator_only/ground_truth.csv")
        )


def test_authorized_symlink_cannot_resolve_outside_investigator_tree(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    context_file = package / "investigator/context/prior_analyst_note.txt"
    external_file = package / "evaluator_only/ground_truth.csv"
    context_file.unlink()
    try:
        context_file.symlink_to(external_file)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    with pytest.raises(ValueError, match="escapes the permitted tree"):
        load_investigator_package(package)
