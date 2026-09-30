"""Storage split, and the architectural boundary around the harness.

PO-4 (approved): scenario definitions, harness code and summary records are
version-controlled; raw model responses, run databases and logs stay out of version
control, referenced by run id.

Section 4: the harness has no Streamlit, no browser and no investigation database, and
nothing it produces may be wired into the application.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from validation.qualification.counts import ObservationCounts
from validation.qualification.isolation import EvaluatorIsolationError
from validation.qualification.records import RunRecord
from validation.qualification.rollup import build_rollup
from validation.qualification.runner import run_sweep
from validation.qualification.storage import (
    FileRecordSink,
    experiment_directory,
    write_semantic_acceptance_packages,
    write_summary_record,
)

from qualification_support import (
    ScriptedClient,
    chained_scenario,
    configuration,
    context,
    environment_probe,
    fixed_clock,
    transport_failure,
    valid_response_text,
)


def _sweep(tmp_path: Path, script, counts=ObservationCounts(1, 1)):
    directory = experiment_directory("experiment-test", tmp_path)
    sink = FileRecordSink(directory)
    records = run_sweep(
        (chained_scenario(),),
        (configuration(),),
        counts=counts,
        client_factory=lambda _: ScriptedClient(script),
        environment_probe=environment_probe,
        context_loader=lambda _: context(),
        sink=sink,
        experiment_id="experiment-test",
        clock=fixed_clock,
    )
    return records, directory, sink


def test_raw_prompt_and_verbatim_response_are_written_per_run_id(tmp_path: Path) -> None:
    records, _, sink = _sweep(
        tmp_path,
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
    )

    for record in records:
        prompt_path = sink.raw_directory / f"{record.run_id}.prompt.txt"
        response_path = sink.raw_directory / f"{record.run_id}.response.txt"
        assert prompt_path.read_text(encoding="utf-8") == record.raw.prompt
        assert response_path.read_text(encoding="utf-8") == record.raw.raw_response
        assert json.loads(
            (sink.record_directory / f"{record.run_id}.json").read_text(encoding="utf-8")
        )["run_id"] == record.run_id


def test_an_unparseable_response_is_stored_verbatim_rather_than_discarded(
    tmp_path: Path,
) -> None:
    """Section 4: an unparseable response is data, not a lost run."""
    records, _, sink = _sweep(tmp_path, ["I will not return JSON."])

    initial = records[0]
    stored = (sink.raw_directory / f"{initial.run_id}.response.txt").read_text(encoding="utf-8")
    assert stored == "I will not return JSON."
    assert initial.structurally_valid is False


def test_a_transport_failure_is_stored_with_its_category(tmp_path: Path) -> None:
    records, _, sink = _sweep(tmp_path, [transport_failure()])

    stored = (
        sink.raw_directory / f"{records[0].run_id}.transport-failure.txt"
    ).read_text(encoding="utf-8")
    assert "SERVICE_UNAVAILABLE" in stored


def test_summary_record_is_written_separately_from_the_raw_run_directory(
    tmp_path: Path,
) -> None:
    records, directory, _ = _sweep(
        tmp_path,
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
    )
    summary_directory = tmp_path / "summaries"

    path = write_summary_record(
        build_rollup("experiment-test", records, counts=ObservationCounts(1, 1)),
        summary_directory,
    )

    assert path == summary_directory / "experiment-test.json"
    assert directory not in path.parents
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["experiment_id"] == "experiment-test"
    assert "no quality score" in summary["no_automated_quality_signal"]


def test_semantic_acceptance_packages_are_written_per_configuration(tmp_path: Path) -> None:
    records, directory, _ = _sweep(
        tmp_path,
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
    )

    written = write_semantic_acceptance_packages("experiment-test", records, directory)

    assert len(written) == 1
    assert written[0].name == "test-config.md"
    assert "## Scenario — Initial (`INITIAL`)" in written[0].read_text(encoding="utf-8")


def test_a_record_carrying_evaluator_material_is_refused_rather_than_redacted(
    tmp_path: Path,
) -> None:
    records, _, _ = _sweep(
        tmp_path / "other",
        [valid_response_text("i"), valid_response_text("m"), valid_response_text("d")],
    )
    sink = FileRecordSink(experiment_directory("experiment-test", tmp_path))
    leaking = replace(records[0], configuration_label="ground truth leak")

    try:
        sink.record_run(leaking)
    except EvaluatorIsolationError:
        assert not list(sink.record_directory.glob("*.json"))
        return
    raise AssertionError("a record carrying evaluator-only material must be refused")


def test_the_run_directory_is_ignored_by_version_control() -> None:
    """PO-4: raw responses and logs stay out of version control."""
    ignore_rules = (
        Path(__file__).resolve().parents[1] / ".gitignore"
    ).read_text(encoding="utf-8")

    assert "/validation/runs/" in ignore_rules


def test_the_harness_does_not_depend_on_streamlit_or_the_investigation_database() -> None:
    """Section 4: no Streamlit, no browser, no investigation database."""
    package = Path(__file__).resolve().parents[1] / "validation"
    forbidden = ("streamlit", "investigation.persistence", "investigation.app",
                 "investigation.approval_loop", "investigation.read_model", "sqlite3")

    for path in sorted(package.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        imports = "\n".join(
            line for line in source.splitlines()
            if line.startswith(("import ", "from ")) or line.strip().startswith(
                ("import ", "from ")
            )
        )
        for name in forbidden:
            assert name not in imports, f"{path.name} must not import {name}"
