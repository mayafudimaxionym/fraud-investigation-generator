"""Evaluator isolation for the harness. Absolute, and enforced twice.

Section 4: ground truth, campaigns, signals and hypotheses must **never** enter a
prompt or an experiment record.

Two independent mechanisms, because one is structural and one is a backstop:

1. **Structural.** The harness only ever obtains investigator context through the
   product's governed loader `load_investigator_package`, which reads solely the
   package's `investigator/` subtree. Evaluator-only material is never loaded, so it
   cannot be rendered into a prompt. This is the real boundary.
2. **Backstop scan.** Every prompt is scanned before dispatch and every record is
   scanned before it is written, using the product's own evaluator-only token list. A
   hit aborts rather than redacting: a harness that quietly strips leaked evaluator
   material would hide the leak it exists to prevent.

The scan covers data-bearing content -- prompts, verbatim model output, recorded
labels, settings and categories -- and not the harness's own fixed explanatory prose.
That prose names the checks, including "no evaluator-only references", so scanning it
would fire on every record and turn the guard into noise everyone learns to ignore.
`RunRecord.data_text()` and `ExperimentRollUp.data_text()` define that surface.
"""

from __future__ import annotations

from pathlib import Path

from investigation.package_access import InvestigatorPackageContext, load_investigator_package

from validation.qualification.contract import forbidden_private_references


class EvaluatorIsolationError(RuntimeError):
    """Evaluator-only material reached a prompt or a record. The run must not proceed."""


def assert_no_evaluator_material(text: str, location: str) -> None:
    """Abort if evaluator-only material appears in prompt or record text."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    folded = text.casefold()
    hits = tuple(
        reference
        for reference in forbidden_private_references()
        if reference in folded
    )
    if hits:
        raise EvaluatorIsolationError(
            f"evaluator-only material reached {location}: {', '.join(sorted(hits))}"
        )


def load_governed_context(package_directory: Path) -> InvestigatorPackageContext:
    """Load scenario context through the product's governed loader and nothing else."""
    if not isinstance(package_directory, Path):
        raise ValueError("package_directory must be a Path")
    return load_investigator_package(package_directory)
