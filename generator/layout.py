"""Filesystem layout for generated cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaseOutputPaths:
    """Separate canonical truth from investigator-visible case materials."""

    case_directory: Path
    ground_truth_directory: Path
    investigator_view_directory: Path


def case_output_paths(output_root: Path, case_id: str) -> CaseOutputPaths:
    """Return the output layout for one case without creating directories."""
    if not case_id or Path(case_id).name != case_id:
        raise ValueError("case_id must be a single non-empty path segment")

    case_directory = output_root / case_id
    return CaseOutputPaths(
        case_directory=case_directory,
        ground_truth_directory=case_directory / "ground_truth",
        investigator_view_directory=case_directory / "investigator_view",
    )
