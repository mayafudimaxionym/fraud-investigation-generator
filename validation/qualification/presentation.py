"""The semantic acceptance package: nine plans, grouped by scenario, labelled.

Section 2.1 states this as a **presentation requirement, not optional**: the package
presents the plans grouped by scenario, each labelled with its scenario and run index,
so the Product Owner can see stability *within* a scenario rather than an
undifferentiated set.

The package presents and labels. It does not judge. Every run is rendered in full, in
the model's own words, with an empty line for the Product Owner's judgement. There is
no score, no ranking, no ordering by apparent quality, and no summary of how the runs
compare -- section 4 prohibits any automated value that converts quality into an
acceptance signal, and ADR 006 reserves semantic adequacy to human judgement.

Per-scenario grouping is also what keeps the reported gate honest. The gate is
three-of-three within each scenario. Section 2.1 forbids pooling the nine runs into a
single stronger-sounding claim, so this package never renders a nine-run total as a
result, and it states the screening-gate qualification wherever N=3 appears.

A shortfall is stated, never smoothed over. If a scenario has fewer presented runs
than section 2.1 requires -- typically because a chained predecessor failed and no
real prior state existed -- the package says so at the top and in that scenario.
"""

from __future__ import annotations

from collections.abc import Sequence

from validation.qualification.counts import (
    APPROVED_COUNTS,
    ObservationCounts,
    SEMANTIC_ACCEPTANCE_RULE,
    SEMANTIC_SCREENING_GATE_QUALIFICATION,
)
from validation.qualification.records import RunRecord


_SCENARIO_HEADING = {
    "INITIAL": "Initial",
    "MODIFY": "Modify",
    "DECLINE_REDIRECT": "Decline / redirect",
}


def build_semantic_acceptance_package(
    experiment_id: str,
    configuration_label: str,
    records: Sequence[RunRecord],
    *,
    counts: ObservationCounts = APPROVED_COUNTS,
) -> str:
    """Render the semantic acceptance package for one candidate configuration."""
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    if not isinstance(configuration_label, str) or not configuration_label.strip():
        raise ValueError("configuration_label must be a non-empty string")
    selected = [
        record for record in records
        if record.configuration_label == configuration_label
        and record.semantic_sample
        and record.plan is not None
    ]
    grouped = _group_by_scenario(selected, records, configuration_label)

    lines: list[str] = [
        f"# Semantic acceptance package — {configuration_label}",
        "",
        f"- Experiment: `{experiment_id}`",
        f"- Candidate configuration: `{configuration_label}`",
    ]
    lines.extend(_configuration_lines(selected))
    lines.extend([
        "",
        "## How to read this package",
        "",
        f"- **Runs required per scenario:** {counts.semantic_runs_per_scenario}, each read in full.",
        "- **Grouping:** plans are grouped by scenario and labelled with their run index, so "
        "stability within a scenario is visible.",
        f"- **Screening gate:** {SEMANTIC_SCREENING_GATE_QUALIFICATION}",
        f"- **Who decides:** {SEMANTIC_ACCEPTANCE_RULE}",
        "- **No automated judgement appears anywhere in this package.** The harness captured "
        "and labelled these runs. It did not score, rank, rate or order them by quality, and "
        "it reports no opinion on any of them.",
        "",
    ])
    lines.extend(_shortfall_lines(grouped, counts))

    for mode, mode_records in grouped:
        heading = _SCENARIO_HEADING.get(mode, mode)
        lines.extend([
            f"## Scenario — {heading} (`{mode}`)",
            "",
            f"Runs presented: {len(mode_records)} of {counts.semantic_runs_per_scenario} "
            f"required for this scenario.",
            "",
        ])
        if not mode_records:
            lines.extend([
                "_No run of this scenario was captured. This scenario is unobserved; it is "
                "not an adequate result and not an inadequate one._",
                "",
            ])
            continue
        for record in sorted(mode_records, key=lambda item: item.run_index):
            lines.extend(_run_section(record, mode, heading, counts))
    return "\n".join(lines).rstrip() + "\n"


def _group_by_scenario(
    selected: Sequence[RunRecord],
    all_records: Sequence[RunRecord],
    configuration_label: str,
) -> list[tuple[str, list[RunRecord]]]:
    """Group in the order the scenarios were defined, keeping unobserved ones visible."""
    ordered_modes: list[str] = []
    for record in all_records:
        if record.configuration_label == configuration_label and record.mode not in ordered_modes:
            ordered_modes.append(record.mode)
    return [
        (mode, [record for record in selected if record.mode == mode])
        for mode in ordered_modes
    ]


def _configuration_lines(selected: Sequence[RunRecord]) -> list[str]:
    if not selected:
        return []
    settings = selected[0].configuration_settings
    environment = selected[0].environment
    lines = [f"- Model: `{settings.get('model')}`"]
    digest = environment.get("model_digest")
    version = environment.get("ollama_version")
    lines.append(f"- Model digest: `{digest}`" if digest else "- Model digest: not captured")
    lines.append(f"- Ollama version: `{version}`" if version else "- Ollama version: not captured")
    lines.append(
        f"- Settings: temperature `{settings.get('temperature')}`, seed `{settings.get('seed')}`, "
        f"timeout `{settings.get('timeout_seconds')}`s"
    )
    lines.append(f"- Prompt configuration: `{settings.get('prompt_configuration')}`")
    return lines


def _shortfall_lines(
    grouped: Sequence[tuple[str, Sequence[RunRecord]]], counts: ObservationCounts
) -> list[str]:
    short = [
        (mode, len(mode_records))
        for mode, mode_records in grouped
        if len(mode_records) < counts.semantic_runs_per_scenario
    ]
    if not short:
        return []
    lines = [
        "## Incomplete package",
        "",
        "This package does not meet the section 2.1 observation counts. It is presented as "
        "incomplete evidence, and the configuration is not ready to be put to semantic "
        "acceptance on it:",
        "",
    ]
    lines.extend(
        f"- `{mode}`: {presented} of {counts.semantic_runs_per_scenario} required runs presented."
        for mode, presented in short
    )
    lines.append("")
    return lines


def _run_section(
    record: RunRecord, mode: str, heading: str, counts: ObservationCounts
) -> list[str]:
    assert record.plan is not None
    plan = record.plan
    lines = [
        f"### {heading} — run {record.run_index} of {counts.semantic_runs_per_scenario}",
        "",
        f"- Scenario: `{mode}`",
        f"- Run index within this scenario: {record.run_index}",
        f"- Run id: `{record.run_id}`",
        f"- Chain: `{record.chain_id}` (step {record.step_index}; prior state for this run was "
        "generated by the preceding step of this same chain)",
        f"- Structural contract: {'satisfied' if record.structurally_valid else 'not satisfied'}",
        "",
        "**Competing explanations**",
        "",
    ]
    lines.extend(
        f"{index}. {item}" for index, item in enumerate(plan.competing_explanations, start=1)
    )
    lines.extend(["", "**Provisional plan steps**", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(plan.plan_steps, start=1))
    lines.extend([
        "",
        "**Proposed next action**",
        "",
        f"- Action: {plan.action}",
        f"- Purpose: {plan.purpose}",
        f"- Why now: {plan.why_now}",
        f"- Data to be used: {plan.data_to_be_used}",
        f"- Expected output: {plan.expected_output}",
        "",
        "**Product Owner judgement for this run:** _(adequate / inadequate, and why)_",
        "",
    ])
    return lines
