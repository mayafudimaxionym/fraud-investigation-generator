"""Governed access to the fixed investigator-facing V0 package."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


_CONTEXT_FILES = {
    "investigation_request": Path("context/investigation_request.txt"),
    "customer_support_statement": Path("context/customer_support.txt"),
    "prior_analyst_note": Path("context/prior_analyst_note.txt"),
}
_DATASET_HEADERS = {
    "visible_entities.csv": ("entity_id", "entity_type"),
    "visible_relationships.csv": (
        "relationship_id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
    ),
    "visible_events.csv": (
        "event_id",
        "event_type",
        "subject_entity_id",
        "target_entity_id",
        "occurred_at",
    ),
}


@dataclass(frozen=True)
class DatasetInventory:
    """Safe metadata describing one investigator-visible structured dataset."""

    dataset_name: str
    row_count: int
    field_names: tuple[str, ...]


@dataclass(frozen=True)
class InvestigatorPackageContext:
    """The complete V0 initial context allowed to reach a proposal agent."""

    investigation_request: str
    customer_support_statement: str
    prior_analyst_note: str
    datasets: tuple[DatasetInventory, ...]


def load_investigator_package(package_directory: Path) -> InvestigatorPackageContext:
    """Load only the fixed investigator-facing context and safe CSV inventory."""
    investigator_directory = _investigator_directory(package_directory)
    context_values = {
        field_name: _read_required_text(investigator_directory, relative_path)
        for field_name, relative_path in _CONTEXT_FILES.items()
    }
    datasets = tuple(
        _read_dataset_inventory(investigator_directory, dataset_name, expected_headers)
        for dataset_name, expected_headers in _DATASET_HEADERS.items()
    )
    return InvestigatorPackageContext(datasets=datasets, **context_values)


def _investigator_directory(package_directory: Path) -> Path:
    try:
        package_root = package_directory.resolve(strict=True)
        investigator_directory = (package_root / "investigator").resolve(strict=True)
    except OSError as error:
        raise ValueError("investigator package directory is unavailable") from error
    if not package_root.is_dir() or not investigator_directory.is_dir():
        raise ValueError("investigator package directory is unavailable")
    _require_within(package_root, investigator_directory)
    return investigator_directory


def _read_required_text(investigator_directory: Path, relative_path: Path) -> str:
    path = _authorized_file(investigator_directory, relative_path)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("required investigator context is unreadable") from error
    if not content.strip():
        raise ValueError("required investigator context must be non-empty")
    return content


def _read_dataset_inventory(
    investigator_directory: Path,
    dataset_name: str,
    expected_headers: tuple[str, ...],
) -> DatasetInventory:
    path = _authorized_file(investigator_directory, Path("data") / dataset_name)
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            headers = tuple(next(reader, ()))
            if headers != expected_headers:
                raise ValueError("investigator dataset has unexpected headers")
            row_count = 0
            for row in reader:
                if len(row) != len(headers):
                    raise ValueError("investigator dataset is malformed")
                row_count += 1
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError("investigator dataset is unreadable") from error
    return DatasetInventory(dataset_name, row_count, headers)


def _authorized_file(investigator_directory: Path, relative_path: Path) -> Path:
    try:
        path = (investigator_directory / relative_path).resolve(strict=True)
    except OSError as error:
        raise ValueError("required investigator package content is unavailable") from error
    _require_within(investigator_directory, path)
    if not path.is_file():
        raise ValueError("required investigator package content is unavailable")
    return path


def _require_within(parent: Path, child: Path) -> None:
    try:
        child.relative_to(parent)
    except ValueError as error:
        raise ValueError("investigator package path escapes the permitted tree") from error
