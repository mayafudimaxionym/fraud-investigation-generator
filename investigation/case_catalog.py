"""Configured, governed case selection for the V0.5 investigator workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from investigation.models import InvestigationRecord
from investigation.package_access import DatasetInventory, InvestigatorPackageContext, load_investigator_package
from investigation.persistence import SQLiteInvestigationStore


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True)
class ConfiguredCasePackage:
    """Deployment-only configuration; its package path never reaches callers."""

    association_id: str
    case_reference: str
    package_directory: Path
    domain: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.association_id, "association_id")
        _require_non_blank(self.case_reference, "case_reference")
        if not isinstance(self.package_directory, Path):
            raise ValueError("package_directory must be a Path")
        if self.domain is not None:
            _require_non_blank(self.domain, "domain")


@dataclass(frozen=True)
class AvailableInvestigatorCase:
    """Safe case-selection metadata with no filesystem or evaluator information."""

    association_id: str
    case_reference: str
    domain: str | None
    datasets: tuple[DatasetInventory, ...]


class ConfiguredCaseCatalog:
    """Resolve only explicitly configured opaque package associations."""

    def __init__(self, cases: tuple[ConfiguredCasePackage, ...]) -> None:
        associations: set[str] = set()
        for case in cases:
            if not isinstance(case, ConfiguredCasePackage):
                raise ValueError("cases must contain ConfiguredCasePackage entries")
            if case.association_id in associations:
                raise ValueError("case catalog association IDs must be unique")
            associations.add(case.association_id)
        self._cases = cases

    def available_cases(self) -> tuple[AvailableInvestigatorCase, ...]:
        """Return only safe metadata for the fixed configured cases."""
        return tuple(
            AvailableInvestigatorCase(
                association_id=case.association_id,
                case_reference=case.case_reference,
                domain=case.domain,
                datasets=self.load_context(case.association_id).datasets,
            )
            for case in self._cases
        )

    def load_context(self, association_id: str) -> InvestigatorPackageContext:
        """Load a configured package through the existing governed loader."""
        return load_investigator_package(self._configured_case(association_id).package_directory)

    def _configured_case(self, association_id: str) -> ConfiguredCasePackage:
        _require_non_blank(association_id, "association_id")
        for case in self._cases:
            if case.association_id == association_id:
                return case
        raise ValueError("configured case association does not exist")


DEFAULT_LOCAL_CASE_CATALOG = ConfiguredCaseCatalog(
    (
        ConfiguredCasePackage(
            association_id="development-case-42",
            case_reference="development-case-42",
            package_directory=_REPOSITORY_ROOT / "output" / "development-case-42",
        ),
    )
)


def associate_legacy_investigation(
    store: SQLiteInvestigationStore,
    catalog: ConfiguredCaseCatalog,
    investigation_id: str,
    association_id: str,
) -> InvestigationRecord:
    """Explicitly attach one previously unassociated investigation to a safe case."""
    catalog.load_context(association_id)
    return store.set_package_association_if_missing(investigation_id, association_id)
