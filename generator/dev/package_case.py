"""Development-only investigator package for the fixed synthetic case."""

from __future__ import annotations

from pathlib import Path
from shutil import rmtree

from generator.case import CanonicalCase
from generator.dev.inspect_case import (
    build_development_case,
    write_case_csv_exports,
)


def export_development_investigation_package(output_root: Path) -> Path:
    """Export the fixed case with physically separated investigator materials."""
    case = build_development_case()
    case_directory = output_root / case.case_id
    if case_directory.exists():
        if not case_directory.is_dir():
            raise ValueError("development package path must be a directory")
        rmtree(case_directory)
    investigator_directory = case_directory / "investigator"
    context_directory = investigator_directory / "context"
    write_case_csv_exports(
        case,
        case_directory / "evaluator_only",
        investigator_directory / "data",
    )
    context_directory.mkdir(parents=True, exist_ok=True)
    for filename, content in build_investigator_text_fixtures(case).items():
        (context_directory / filename).write_text(content, encoding="utf-8", newline="\n")
    return case_directory


def build_investigator_text_fixtures(case: CanonicalCase) -> dict[str, str]:
    """Return fixed investigator-only context without reading private truth."""
    entity_ids = case.investigator_view.visible_entity_ids
    return {
        "investigation_request.txt": (
            "Review the potentially related activity in the supplied records.\n\n"
            "Determine the strongest supported explanation, identify the affected "
            "activity and evidence, consider plausible alternatives, and state the "
            "limitations of the available information."
        ),
        "customer_support.txt": (
            "Customer support message\n\n"
            "I sometimes share the device at home and cannot remember the exact "
            "timing of my recent logins. I thought the transfers were mine, but I "
            "am not completely sure which one I made."
        ),
        "prior_analyst_note.txt": (
            "Prior analyst note\n\n"
            f"{entity_ids[3]} and {entity_ids[5]} both use {entity_ids[1]}. "
            "The nearby login and transfer records may reflect ordinary shared "
            "access. Treat routine shared use as a working explanation unless "
            "additional evidence indicates otherwise."
        ),
    }


def main() -> None:
    """Export the final fixed investigator package beneath the local output directory."""
    print(export_development_investigation_package(Path("output")))


if __name__ == "__main__":
    main()
