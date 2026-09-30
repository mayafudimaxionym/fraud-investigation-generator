"""Durable run storage, split the way PO-4 requires.

PO-4 (approved): scenario definitions, harness definitions/code and **summary
records** are version-controlled under one validation directory. **Raw model
responses, run databases and logs stay out of version control, referenced by run id.**

So:

- `validation/runs/<experiment_id>/` holds the verbatim prompts, the verbatim
  responses and the per-run records. It is ignored by git and referenced by run id.
- `validation/qualification/summaries/<experiment_id>.json` holds the roll-up summary,
  which is version-controllable.

Every serialized record is scanned for evaluator-only material before it is written.
A hit raises rather than redacting: a record that quietly dropped leaked evaluator
material would hide exactly the failure the scan exists to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

from validation.qualification.isolation import assert_no_evaluator_material
from validation.qualification.presentation import build_semantic_acceptance_package
from validation.qualification.records import RawCapture, RunRecord, serialize_record
from validation.qualification.rollup import ExperimentRollUp
from validation.qualification.runner import RecordSink


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Out of version control. Referenced by run id.
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "validation" / "runs"

#: Version-controlled summary records.
DEFAULT_SUMMARY_DIRECTORY = Path(__file__).resolve().parent / "summaries"


class FileRecordSink(RecordSink):
    """Write verbatim captures and per-run records under one run directory."""

    def __init__(self, experiment_directory: Path) -> None:
        self._raw_directory = experiment_directory / "raw"
        self._record_directory = experiment_directory / "records"
        self._raw_directory.mkdir(parents=True, exist_ok=True)
        self._record_directory.mkdir(parents=True, exist_ok=True)

    @property
    def raw_directory(self) -> Path:
        return self._raw_directory

    @property
    def record_directory(self) -> Path:
        return self._record_directory

    def capture_raw(self, run_id: str, capture: RawCapture) -> None:
        """Persist the verbatim prompt and response before any parsing is attempted."""
        assert_no_evaluator_material(capture.prompt, f"the captured prompt for {run_id}")
        (self._raw_directory / f"{run_id}.prompt.txt").write_text(
            capture.prompt, encoding="utf-8"
        )
        if capture.raw_response is not None:
            # Written verbatim, without parsing or reformatting. An unparseable
            # response is data.
            (self._raw_directory / f"{run_id}.response.txt").write_text(
                capture.raw_response, encoding="utf-8"
            )
        else:
            (self._raw_directory / f"{run_id}.transport-failure.txt").write_text(
                f"{capture.transport_failure_category}\n{capture.transport_failure_message}\n",
                encoding="utf-8",
            )

    def record_run(self, record: RunRecord) -> None:
        """Persist the complete per-run record, scanned before it is written."""
        assert_no_evaluator_material(
            record.data_text(), f"the run record for {record.run_id}"
        )
        (self._record_directory / f"{record.run_id}.json").write_text(
            serialize_record(record), encoding="utf-8"
        )


def write_summary_record(
    rollup: ExperimentRollUp,
    summary_directory: Path = DEFAULT_SUMMARY_DIRECTORY,
) -> Path:
    """Write the version-controllable roll-up summary for one experiment."""
    summary_directory.mkdir(parents=True, exist_ok=True)
    assert_no_evaluator_material(rollup.data_text(), "the experiment summary record")
    serialized = json.dumps(rollup.as_record(), indent=2, sort_keys=True, ensure_ascii=False)
    path = summary_directory / f"{rollup.experiment_id}.json"
    path.write_text(serialized + "\n", encoding="utf-8")
    return path


def write_semantic_acceptance_packages(
    experiment_id: str,
    records: tuple[RunRecord, ...],
    experiment_directory: Path,
) -> tuple[Path, ...]:
    """Write one semantic acceptance package per candidate configuration, for reading."""
    package_directory = experiment_directory / "semantic-acceptance"
    package_directory.mkdir(parents=True, exist_ok=True)
    labels: list[str] = []
    for record in records:
        if record.configuration_label not in labels:
            labels.append(record.configuration_label)
    written: list[Path] = []
    for label in labels:
        for record in records:
            if record.configuration_label == label and record.semantic_sample:
                assert_no_evaluator_material(
                    record.data_text(), f"the semantic acceptance package for {label}"
                )
        package = build_semantic_acceptance_package(experiment_id, label, records)
        path = package_directory / f"{_safe_name(label)}.md"
        path.write_text(package, encoding="utf-8")
        written.append(path)
    return tuple(written)


def experiment_directory(experiment_id: str, run_root: Path = DEFAULT_RUN_ROOT) -> Path:
    """Resolve the out-of-version-control directory for one experiment id."""
    return run_root / _safe_name(experiment_id)


def _safe_name(value: str) -> str:
    """Keep run and configuration identifiers usable as a single path segment."""
    safe = "".join(
        character if character.isalnum() or character in "-._" else "-"
        for character in value
    ).strip("-.")
    if not safe:
        raise ValueError("identifier does not yield a usable file name")
    return safe
