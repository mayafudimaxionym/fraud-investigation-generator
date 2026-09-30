"""One end-to-end pass over the committed scenario and the real governed fixture.

Everything is real except the model: the version-controlled scenario, the frozen
synthetic package loaded through the product's governed loader, the product's prompt
builder, the product's contract, the durable storage split and the presentation. The
model itself is scripted, because running the qualification campaign is separate work
owned by the AI Model Qualification Researcher.
"""

from __future__ import annotations

import json
from pathlib import Path

from validation.qualification.counts import APPROVED_COUNTS
from validation.qualification.rollup import build_rollup
from validation.qualification.runner import run_sweep
from validation.qualification.scenarios import load_scenarios
from validation.qualification.storage import (
    FileRecordSink,
    experiment_directory,
    write_semantic_acceptance_packages,
    write_summary_record,
)

from qualification_support import (
    ScriptedClient,
    configuration,
    environment_probe,
    fixed_clock,
    valid_response_text,
)


def _committed_chain():
    return next(
        scenario for scenario in load_scenarios()
        if tuple(step.mode for step in scenario.steps)
        == ("INITIAL", "MODIFY", "DECLINE_REDIRECT")
    )


def test_full_sweep_at_the_approved_counts_over_the_real_fixture(tmp_path: Path) -> None:
    scenario = _committed_chain()
    if not (scenario.package_directory / "investigator").is_dir():
        return  # the generated fixture is not present in this checkout

    script = []
    for repetition in range(1, APPROVED_COUNTS.chain_repetitions + 1):
        script.extend([
            valid_response_text(f"initial-{repetition}"),
            valid_response_text(f"modify-{repetition}"),
            valid_response_text(f"decline-{repetition}"),
        ])
    directory = experiment_directory("experiment-e2e", tmp_path)
    sink = FileRecordSink(directory)

    records = run_sweep(
        (scenario,),
        (configuration("qwen3-30b-64k", "qwen3:30b"),),
        counts=APPROVED_COUNTS,
        client_factory=lambda _: ScriptedClient(script),
        environment_probe=environment_probe,
        sink=sink,
        experiment_id="experiment-e2e",
        clock=fixed_clock,
    )

    # 30 structural observations: 10 of each of the three semantic scenarios.
    assert len(records) == 30
    for mode in ("INITIAL", "MODIFY", "DECLINE_REDIRECT"):
        assert sum(1 for record in records if record.mode == mode) == 10

    # The governed context reached every prompt, and nothing else did.
    context_text = (
        scenario.package_directory / "investigator" / "context" / "investigation_request.txt"
    ).read_text(encoding="utf-8")
    for record in records:
        assert context_text.strip() in record.raw.prompt
        assert "visible_events.csv" in record.raw.prompt

    rollup = build_rollup("experiment-e2e", records, counts=APPROVED_COUNTS)
    summary_path = write_summary_record(rollup, tmp_path / "summaries")
    packages = write_semantic_acceptance_packages("experiment-e2e", records, directory)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scenarios = summary["configurations"][0]["scenarios"]
    assert len(scenarios) == 3
    for entry in scenarios:
        assert entry["attempted_runs"] == 10
        assert entry["structurally_valid_runs"] == 10
        assert entry["structural_validity_rate"] == 1.0
        assert entry["meets_required_structural_observations"] is True
        assert entry["semantic_plans_presented"] == 3
        assert entry["meets_required_semantic_observations"] is True
    assert summary["configurations"][0]["observation_counts_complete"] is True

    package = packages[0].read_text(encoding="utf-8")
    assert package.count("### ") == 9
    assert "## Incomplete package" not in package

    # Raw captures are durable per run id, outside version control.
    assert len(list((directory / "raw").glob("*.prompt.txt"))) == 30
    assert len(list((directory / "raw").glob("*.response.txt"))) == 30
    assert len(list((directory / "records").glob("*.json"))) == 30


def test_a_chain_broken_midway_reports_the_shortfall_end_to_end(tmp_path: Path) -> None:
    scenario = _committed_chain()
    if not (scenario.package_directory / "investigator").is_dir():
        return

    script = []
    for repetition in range(1, APPROVED_COUNTS.chain_repetitions + 1):
        # Every INITIAL is valid; every MODIFY is unparseable, so DECLINE has no real
        # prior state to run against and is never observed.
        script.extend([valid_response_text(f"initial-{repetition}"), "not json"])
    directory = experiment_directory("experiment-broken", tmp_path)

    records = run_sweep(
        (scenario,),
        (configuration(),),
        counts=APPROVED_COUNTS,
        client_factory=lambda _: ScriptedClient(script),
        environment_probe=environment_probe,
        sink=FileRecordSink(directory),
        experiment_id="experiment-broken",
        clock=fixed_clock,
    )

    rollup = build_rollup("experiment-broken", records, counts=APPROVED_COUNTS)
    by_mode = {
        scenario_rollup.mode: scenario_rollup
        for scenario_rollup in rollup.configurations[0].scenarios
    }

    assert by_mode["MODIFY"].failed_checks == {"JSON_PARSE": 10}
    assert by_mode["DECLINE_REDIRECT"].attempted_runs == 0
    assert by_mode["DECLINE_REDIRECT"].structural_validity_rate is None
    assert by_mode["DECLINE_REDIRECT"].not_attempted_reasons == {
        "CHAIN_PREDECESSOR_UNAVAILABLE": 10
    }
    assert rollup.configurations[0].observation_counts_complete is False

    package = write_semantic_acceptance_packages("experiment-broken", records, directory)[0]
    text = package.read_text(encoding="utf-8")
    assert "## Incomplete package" in text
    assert "`MODIFY`: 0 of 3 required runs presented." in text
    assert "`DECLINE_REDIRECT`: 0 of 3 required runs presented." in text
