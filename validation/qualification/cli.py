"""Command line entry point for the Model Qualification Harness.

Offline research tooling. No Streamlit, no browser, no investigation database.

Running a qualification campaign is the AI Model Qualification Researcher's work, not
this module's: the harness only makes a campaign runnable and reproducible. A sweep
therefore requires an explicit `--confirm-run`, so importing, inspecting or
dry-running the harness never dispatches a single model request by accident.

    py -3 -m validation.qualification --list-scenarios
    py -3 -m validation.qualification --model qwen3:30b --label qwen3-30b-64k --dry-run
    py -3 -m validation.qualification --model qwen3:30b --label qwen3-30b-64k --confirm-run

Sweeps vary the model and settings on the command line. Scenario text is never edited
to sweep: `--model` may be repeated to compare candidate configurations against the
same version-controlled scenarios.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from investigation.proposal_agent import ProposalOllamaConfig

from validation.qualification.configurations import CandidateConfiguration
from validation.qualification.counts import APPROVED_COUNTS, ObservationCounts
from validation.qualification.rollup import build_rollup
from validation.qualification.runner import run_sweep
from validation.qualification.scenarios import ScenarioDefinition, load_scenarios
from validation.qualification.storage import (
    DEFAULT_RUN_ROOT,
    DEFAULT_SUMMARY_DIRECTORY,
    FileRecordSink,
    experiment_directory,
    write_semantic_acceptance_packages,
    write_summary_record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validation.qualification",
        description=(
            "Offline Model Qualification Harness. Produces structural counts and a "
            "semantic acceptance package for a human to read. It produces no quality "
            "score and no acceptance verdict."
        ),
    )
    parser.add_argument(
        "--list-scenarios", action="store_true",
        help="list the version-controlled scenarios and exit",
    )
    parser.add_argument(
        "--model", action="append", default=[], metavar="MODEL",
        help="a local model to sweep; repeat for several candidate configurations",
    )
    parser.add_argument(
        "--label", action="append", default=[], metavar="LABEL",
        help="label for the matching --model; defaults to the model name",
    )
    parser.add_argument(
        "--scenario", action="append", default=[], metavar="SCENARIO_ID",
        help="restrict the sweep to named scenarios; defaults to all of them",
    )
    parser.add_argument(
        "--structural-runs", type=int, default=APPROVED_COUNTS.structural_runs_per_scenario,
        metavar="N",
        help=(
            "runs of each scenario for structural validity "
            f"(section 2.1 requires {APPROVED_COUNTS.structural_runs_per_scenario}; "
            "a lower value produces evidence that does not meet the approved counts "
            "and is reported as an incomplete package)"
        ),
    )
    parser.add_argument(
        "--semantic-runs", type=int, default=APPROVED_COUNTS.semantic_runs_per_scenario,
        metavar="N",
        help=(
            "runs of each scenario presented for reading in full "
            f"(section 2.1 requires {APPROVED_COUNTS.semantic_runs_per_scenario})"
        ),
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT, metavar="PATH",
                        help="where raw captures and per-run records are written")
    parser.add_argument("--summary-dir", type=Path, default=DEFAULT_SUMMARY_DIRECTORY,
                        metavar="PATH", help="where the version-controlled summary is written")
    parser.add_argument("--experiment-id", default=None, metavar="ID",
                        help="reuse a specific experiment id instead of generating one")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be run, dispatch nothing",
    )
    parser.add_argument(
        "--confirm-run", action="store_true",
        help="actually dispatch model requests; required for a real sweep",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    scenarios = _selected_scenarios(arguments.scenario)
    if arguments.list_scenarios:
        _print_scenarios(scenarios)
        return 0

    if not arguments.model:
        parser.error("at least one --model is required for a sweep")
    if arguments.label and len(arguments.label) != len(arguments.model):
        parser.error("supply either no --label or exactly one per --model")

    try:
        counts = ObservationCounts(
            structural_runs_per_scenario=arguments.structural_runs,
            semantic_runs_per_scenario=arguments.semantic_runs,
        )
    except ValueError as error:
        parser.error(str(error))
    configurations = _configurations(arguments.model, arguments.label)
    experiment_id = arguments.experiment_id or f"experiment-{uuid.uuid4()}"

    _print_plan(scenarios, configurations, counts, experiment_id)
    if counts.structural_runs_per_scenario < APPROVED_COUNTS.structural_runs_per_scenario or (
        counts.semantic_runs_per_scenario < APPROVED_COUNTS.semantic_runs_per_scenario
    ):
        print(
            "WARNING: the requested counts are below the approved section 2.1 counts. "
            "The resulting evidence does not satisfy the observation counts for semantic "
            "acceptance.",
        )
    if arguments.dry_run or not arguments.confirm_run:
        print(
            "\nNothing dispatched. Re-run with --confirm-run to execute the sweep."
            if not arguments.dry_run
            else "\nDry run. Nothing dispatched."
        )
        return 0

    directory = experiment_directory(experiment_id, arguments.run_root)
    sink = FileRecordSink(directory)
    records = run_sweep(
        scenarios,
        configurations,
        counts=counts,
        sink=sink,
        experiment_id=experiment_id,
    )
    summary_path = write_summary_record(
        build_rollup(experiment_id, records, counts=counts), arguments.summary_dir
    )
    packages = write_semantic_acceptance_packages(experiment_id, records, directory)

    print(f"\nRuns recorded: {len(records)}")
    print(f"Raw captures and per-run records (not version-controlled): {directory}")
    print(f"Summary record (version-controllable): {summary_path}")
    for path in packages:
        print(f"Semantic acceptance package for reading in full: {path}")
    print(
        "\nNo verdict has been produced. Structural results are counts; semantic "
        "adequacy is decided only by the Product Owner, reading every presented run "
        "in full."
    )
    return 0


def _selected_scenarios(requested: Sequence[str]) -> tuple[ScenarioDefinition, ...]:
    available = load_scenarios()
    if not requested:
        return available
    by_id = {scenario.scenario_id: scenario for scenario in available}
    missing = [scenario_id for scenario_id in requested if scenario_id not in by_id]
    if missing:
        raise SystemExit(f"unknown scenario id(s): {', '.join(missing)}")
    return tuple(by_id[scenario_id] for scenario_id in requested)


def _configurations(
    models: Sequence[str], labels: Sequence[str]
) -> tuple[CandidateConfiguration, ...]:
    environment_defaults = _environment_defaults()
    resolved_labels = labels or models
    return tuple(
        CandidateConfiguration(
            label=label,
            ollama=replace(environment_defaults, model=model),
        )
        for model, label in zip(models, resolved_labels, strict=True)
    )


def _environment_defaults() -> ProposalOllamaConfig:
    """Reuse the product's own deployment configuration seam, model supplied per sweep.

    `ProposalOllamaConfig.from_environment()` requires `OLLAMA_MODEL` to be set, but a
    sweep supplies the model per candidate configuration, so the same environment
    variables are read here and the model is filled in from `--model`.
    """
    return ProposalOllamaConfig(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        model="placeholder",
        timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300")),
        temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0")),
        seed=int(os.environ.get("OLLAMA_SEED", "42")),
    )


def _print_scenarios(scenarios: Sequence[ScenarioDefinition]) -> None:
    for scenario in scenarios:
        print(f"{scenario.scenario_id} - {scenario.name}")
        for step in scenario.steps:
            print(f"    {step.step_id}: {step.mode}")


def _print_plan(
    scenarios: Sequence[ScenarioDefinition],
    configurations: Sequence[CandidateConfiguration],
    counts: ObservationCounts,
    experiment_id: str,
) -> None:
    print(f"Experiment: {experiment_id}")
    print(
        f"Counts per semantic scenario: {counts.structural_runs_per_scenario} structural, "
        f"{counts.semantic_runs_per_scenario} presented for reading in full"
    )
    for configuration in configurations:
        print(f"Candidate configuration: {configuration.label} ({configuration.ollama.model})")
    for scenario in scenarios:
        modes = ", ".join(step.mode for step in scenario.steps)
        print(
            f"Scenario {scenario.scenario_id}: {counts.chain_repetitions} chained runs of "
            f"[{modes}]"
        )
    total = len(configurations) * sum(
        len(scenario.steps) * counts.chain_repetitions for scenario in scenarios
    )
    print(f"Model requests to dispatch: {total} (one per observation, never retried)")


if __name__ == "__main__":
    sys.exit(main())
