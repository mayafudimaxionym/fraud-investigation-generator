import csv
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from generator.dev.package_case import export_development_investigation_package
from investigation.case_catalog import (
    AvailableInvestigatorCase,
    ConfiguredCaseCatalog,
    ConfiguredCasePackage,
    associate_legacy_investigation,
)
from investigation.models import InvestigationRecord
from investigation.package_access import DatasetInventory, InvestigatorPackageContext
from investigation.persistence import SQLiteInvestigationStore


BASE_TIME = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)


def _package(tmp_path: Path) -> Path:
    return export_development_investigation_package(tmp_path)


def _catalog(package: Path) -> ConfiguredCaseCatalog:
    return ConfiguredCaseCatalog(
        (
            ConfiguredCasePackage(
                "development-case-42",
                "Development case 42",
                package,
                "payments",
            ),
        )
    )


def _legacy_investigation(
    investigation_id: str = "investigation-001",
    *,
    package_association: str | None = None,
) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id,
        "unrelated-case-reference",
        BASE_TIME,
        BASE_TIME,
        "",
        package_association,
    )


def test_configured_catalog_returns_only_safe_case_metadata(tmp_path: Path) -> None:
    package = _package(tmp_path)
    available = _catalog(package).available_cases()

    assert available == (
        AvailableInvestigatorCase(
            "development-case-42",
            "Development case 42",
            "payments",
            available[0].datasets,
        ),
    )
    assert tuple(dataset.dataset_name for dataset in available[0].datasets) == (
        "visible_entities.csv",
        "visible_relationships.csv",
        "visible_events.csv",
    )
    assert not hasattr(available[0], "package_directory")
    assert str(package) not in repr(available)
    assert "evaluator_only" not in repr(available)


def test_catalog_rejects_duplicate_and_blank_association_ids(tmp_path: Path) -> None:
    package = _package(tmp_path)
    first = ConfiguredCasePackage("case-001", "Case one", package)
    duplicate = ConfiguredCasePackage("case-001", "Case two", package)
    try:
        ConfiguredCaseCatalog((first, duplicate))
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate association IDs must be rejected")

    try:
        ConfiguredCasePackage(" ", "Case one", package)
    except ValueError as error:
        assert "association_id" in str(error)
    else:
        raise AssertionError("blank association IDs must be rejected")


def test_catalog_resolves_only_known_configured_associations(tmp_path: Path) -> None:
    context = _catalog(_package(tmp_path)).load_context("development-case-42")

    assert context.investigation_request
    assert context.customer_support_statement
    assert context.prior_analyst_note
    assert context.datasets

    try:
        _catalog(_package(tmp_path / "second")).load_context("unknown-case")
    except ValueError as error:
        assert "does not exist" in str(error)
    else:
        raise AssertionError("unknown associations must be rejected")


def test_catalog_context_never_retains_raw_rows_or_evaluator_content(tmp_path: Path) -> None:
    package = _package(tmp_path)
    marker = "ROW_VALUE_MUST_NOT_REACH_CONTEXT"
    entities = package / "investigator" / "data" / "visible_entities.csv"
    with entities.open(encoding="utf-8", newline="") as source:
        rows = list(csv.reader(source))
    rows[1][1] = marker
    with entities.open("w", encoding="utf-8", newline="") as destination:
        csv.writer(destination).writerows(rows)

    evaluator_marker = "EVALUATOR_ONLY_MUST_NOT_REACH_CONTEXT"
    (package / "evaluator_only" / "ground_truth.csv").write_text(
        evaluator_marker, encoding="utf-8"
    )
    context = _catalog(package).load_context("development-case-42")

    assert marker not in repr(context)
    assert evaluator_marker not in repr(context)
    assert all(dataset.row_count > 0 for dataset in context.datasets)


def test_catalog_does_not_discover_unconfigured_output_packages(tmp_path: Path) -> None:
    configured = _package(tmp_path / "configured")
    unconfigured = _package(tmp_path / "output")
    catalog = _catalog(configured)

    assert tuple(case.association_id for case in catalog.available_cases()) == (
        "development-case-42",
    )
    assert unconfigured.is_dir()


def test_catalog_rejects_path_like_association_input(tmp_path: Path) -> None:
    catalog = _catalog(_package(tmp_path))
    try:
        catalog.load_context("../development-case-42")
    except ValueError as error:
        assert "does not exist" in str(error)
    else:
        raise AssertionError("an association ID must not become a package path")


def test_unknown_association_error_does_not_leak_configured_package_path(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    try:
        _catalog(package).load_context("C:/not-a-configured-package")
    except ValueError as error:
        assert str(package) not in str(error)
        assert "does not exist" in str(error)
    else:
        raise AssertionError("unknown associations must not become package paths")


def test_catalog_delegates_context_loading_to_the_governed_loader(tmp_path: Path) -> None:
    package = tmp_path / "configured-package"
    expected_context = InvestigatorPackageContext(
        "request", "support", "note", (DatasetInventory("visible_events.csv", 1, ("event_id",)),)
    )
    with patch(
        "investigation.case_catalog.load_investigator_package",
        return_value=expected_context,
    ) as loader:
        context = _catalog(package).load_context("development-case-42")

    assert context == expected_context
    loader.assert_called_once_with(package)


def test_explicit_legacy_association_persists_only_opaque_catalog_id(tmp_path: Path) -> None:
    package = _package(tmp_path / "package")
    database_path = tmp_path / "investigations.sqlite"
    original = _legacy_investigation()
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(original)
        associated = associate_legacy_investigation(
            store, _catalog(package), original.investigation_id, "development-case-42"
        )

        assert associated.package_association == "development-case-42"
        assert associated.objective == ""
        assert str(package) not in repr(associated)
        assert store.get_investigation(original.investigation_id) == associated


def test_legacy_association_rejects_missing_investigations_unknown_cases_and_overwrite(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "package")
    database_path = tmp_path / "investigations.sqlite"
    catalog = _catalog(package)
    with SQLiteInvestigationStore(database_path) as store:
        try:
            associate_legacy_investigation(
                store, catalog, "investigation-missing", "development-case-42"
            )
        except ValueError as error:
            assert "does not exist" in str(error)
        else:
            raise AssertionError("a missing investigation must be rejected")

        unassociated = _legacy_investigation()
        store.add_investigation(unassociated)
        try:
            associate_legacy_investigation(
                store, catalog, unassociated.investigation_id, "unknown-case"
            )
        except ValueError as error:
            assert "does not exist" in str(error)
        else:
            raise AssertionError("unknown association IDs must be rejected")
        assert store.get_investigation(unassociated.investigation_id) == unassociated

        associated = _legacy_investigation(
            "investigation-associated", package_association="existing-case"
        )
        store.add_investigation(associated)
        try:
            associate_legacy_investigation(
                store, catalog, associated.investigation_id, "development-case-42"
            )
        except ValueError as error:
            assert "already has" in str(error)
        else:
            raise AssertionError("existing package associations must not be overwritten")
        assert store.get_investigation(associated.investigation_id) == associated


def test_legacy_association_never_infers_a_catalog_case_from_case_reference(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    original = InvestigationRecord(
        "investigation-001",
        "development-case-42",
        BASE_TIME,
        BASE_TIME,
        "objective",
        None,
    )
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(original)
        try:
            associate_legacy_investigation(
                store, _catalog(_package(tmp_path / "package")), original.investigation_id, "unknown-case"
            )
        except ValueError as error:
            assert "does not exist" in str(error)
        else:
            raise AssertionError("catalog association must always be explicit")
        assert store.get_investigation(original.investigation_id) == original


def test_persistence_accepts_an_opaque_association_without_catalog_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "investigations.sqlite"
    original = _legacy_investigation()
    with SQLiteInvestigationStore(database_path) as store:
        store.add_investigation(original)
        associated = store.set_package_association_if_missing(
            original.investigation_id, "opaque-association-id"
        )

    assert associated.package_association == "opaque-association-id"
