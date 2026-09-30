"""Roll-ups: structural validity rate and failure categories, per scenario.

Section 4 requires comparable per-run records **plus** roll-ups of validity rate and
failure categories. Section 2.1 approves the structural validity rate explicitly --
repetition is cheap and "buys a genuinely useful validity rate" -- and equally
explicitly sets **no automatic pass threshold**. This module therefore reports counts
and one rate, and never a verdict.

Three things this module deliberately does not produce:

- **No quality score.** The rate here measures machine conformance to the product's
  structural contract. It says nothing about whether the planning is any good, and it
  is labelled that way in the output because a number in an experiment record will be
  read as a verdict however it is labelled (section 4).
- **No semantic rate.** Semantic adequacy is counted only as plans presented for
  reading. Adequacy itself is Maya's judgement at gate G4.
- **No pooled nine-run claim.** Every figure is reported per scenario. Section 2.1
  forbids aggregating the nine semantic runs into a single stronger-sounding
  confidence claim; the gate is three-of-three within each scenario.

Under-observation is reported, not hidden. When a chained scenario's predecessor
failed, the downstream observation does not exist, and the roll-up shows attempted
runs below the required count so the shortfall is visible instead of looking like a
complete result.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from validation.qualification.contract import CHECK_COVERAGE
from validation.qualification.counts import (
    APPROVED_COUNTS,
    ObservationCounts,
    SEMANTIC_ACCEPTANCE_RULE,
    SEMANTIC_SCREENING_GATE_QUALIFICATION,
)
from validation.qualification.records import RunRecord


STRUCTURAL_RATE_BASIS = (
    "Machine conformance to the product's structural contract, over attempted runs of "
    "this one scenario. It is not a quality measure, not a semantic result, and not a "
    "pass mark: section 2.1 sets no automatic pass threshold for structural validity."
)

SEMANTIC_COUNT_BASIS = (
    "Plans captured and presented for the Product Owner to read in full. This is a "
    "count of runs presented, never a count of runs judged adequate. Adequacy is "
    "decided only by the Product Owner at gate G4."
)


@dataclass(frozen=True)
class ScenarioRollUp:
    """Counts for one semantic scenario within one candidate configuration."""

    scenario_id: str
    step_id: str
    mode: str
    required_structural_runs: int
    required_semantic_runs: int
    attempted_runs: int
    not_attempted_runs: int
    not_attempted_reasons: dict[str, int]
    transport_failures: dict[str, int]
    structurally_valid_runs: int
    structurally_invalid_runs: int
    failed_checks: dict[str, int]
    semantic_plans_presented: int

    @property
    def structural_validity_rate(self) -> float | None:
        """Valid over attempted, for this scenario only. None when nothing was attempted."""
        if self.attempted_runs == 0:
            return None
        return self.structurally_valid_runs / self.attempted_runs

    @property
    def meets_required_structural_observations(self) -> bool:
        return self.attempted_runs >= self.required_structural_runs

    @property
    def meets_required_semantic_observations(self) -> bool:
        return self.semantic_plans_presented >= self.required_semantic_runs

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "step_id": self.step_id,
            "mode": self.mode,
            "required_structural_runs": self.required_structural_runs,
            "required_semantic_runs": self.required_semantic_runs,
            "attempted_runs": self.attempted_runs,
            "not_attempted_runs": self.not_attempted_runs,
            "not_attempted_reasons": dict(sorted(self.not_attempted_reasons.items())),
            "transport_failures": dict(sorted(self.transport_failures.items())),
            "structurally_valid_runs": self.structurally_valid_runs,
            "structurally_invalid_runs": self.structurally_invalid_runs,
            "failed_checks": dict(sorted(self.failed_checks.items())),
            "structural_validity_rate": self.structural_validity_rate,
            "structural_validity_rate_basis": STRUCTURAL_RATE_BASIS,
            "meets_required_structural_observations": (
                self.meets_required_structural_observations
            ),
            "semantic_plans_presented": self.semantic_plans_presented,
            "semantic_plans_presented_basis": SEMANTIC_COUNT_BASIS,
            "meets_required_semantic_observations": (
                self.meets_required_semantic_observations
            ),
        }


@dataclass(frozen=True)
class ConfigurationRollUp:
    """Per-scenario counts for one candidate configuration. Never pooled across scenarios."""

    configuration_label: str
    configuration_settings: dict[str, object]
    environment: dict[str, object]
    scenarios: tuple[ScenarioRollUp, ...]

    @property
    def observation_counts_complete(self) -> bool:
        """Whether every scenario reached its own required counts. Not a quality claim."""
        return all(
            scenario.meets_required_structural_observations
            and scenario.meets_required_semantic_observations
            for scenario in self.scenarios
        )

    def as_record(self) -> dict[str, object]:
        return {
            "configuration_label": self.configuration_label,
            "configuration_settings": dict(self.configuration_settings),
            "environment": dict(self.environment),
            "scenarios": [scenario.as_record() for scenario in self.scenarios],
            "observation_counts_complete": self.observation_counts_complete,
            "observation_counts_complete_basis": (
                "Whether each scenario individually reached its required run counts. "
                "It says nothing about structural validity and nothing about semantic "
                "adequacy."
            ),
        }


@dataclass(frozen=True)
class ExperimentRollUp:
    """The version-controllable summary record for one sweep (PO-4)."""

    experiment_id: str
    counts: ObservationCounts
    configurations: tuple[ConfigurationRollUp, ...]

    def data_text(self) -> str:
        """Data-bearing strings only, for the evaluator-isolation scan.

        A roll-up carries no model output, so the data surface is the recorded labels,
        settings, environment and category names. The fixed explanatory prose -- which
        names the checks, including "no evaluator-only references" -- is documentation
        and is excluded so the guard stays meaningful.
        """
        parts: list[str] = [self.experiment_id]
        for configuration in self.configurations:
            parts.append(configuration.configuration_label)
            parts.extend(str(value) for value in configuration.configuration_settings.values())
            parts.extend(str(value) for value in configuration.environment.values())
            for scenario in configuration.scenarios:
                parts.extend([scenario.scenario_id, scenario.step_id, scenario.mode])
                parts.extend(scenario.failed_checks)
                parts.extend(scenario.transport_failures)
                parts.extend(scenario.not_attempted_reasons)
        return "\n".join(parts)

    def as_record(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "observation_counts": {
                "structural_runs_per_scenario": self.counts.structural_runs_per_scenario,
                "semantic_runs_per_scenario": self.counts.semantic_runs_per_scenario,
                "basis": (
                    "docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md section 2.1 "
                    "(PO-2 and PO-8, approved). Counts are per semantic scenario, per "
                    "candidate configuration."
                ),
            },
            "structural_check_coverage": dict(sorted(CHECK_COVERAGE.items())),
            "semantic_screening_gate_qualification": SEMANTIC_SCREENING_GATE_QUALIFICATION,
            "semantic_acceptance_rule": SEMANTIC_ACCEPTANCE_RULE,
            "no_automated_quality_signal": (
                "This record contains no quality score, no rubric score and no "
                "model-judged verdict. ADR 006 rejects that class of false assurance. "
                "Semantic adequacy is judged only by the Product Owner, reading every "
                "presented run in full."
            ),
            "configurations": [
                configuration.as_record() for configuration in self.configurations
            ],
        }


def build_rollup(
    experiment_id: str,
    records: Sequence[RunRecord],
    *,
    counts: ObservationCounts = APPROVED_COUNTS,
) -> ExperimentRollUp:
    """Roll up records per configuration and per scenario. Never across scenarios."""
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id must be a non-empty string")
    configurations: list[ConfigurationRollUp] = []
    for label in _ordered_unique(record.configuration_label for record in records):
        for_label = [record for record in records if record.configuration_label == label]
        configurations.append(ConfigurationRollUp(
            configuration_label=label,
            configuration_settings=dict(for_label[0].configuration_settings),
            environment=dict(for_label[0].environment),
            scenarios=tuple(
                _scenario_rollup(
                    [
                        record for record in for_label
                        if (record.scenario_id, record.step_id) == key
                    ],
                    counts,
                )
                for key in _ordered_unique(
                    (record.scenario_id, record.step_id) for record in for_label
                )
            ),
        ))
    return ExperimentRollUp(
        experiment_id=experiment_id,
        counts=counts,
        configurations=tuple(configurations),
    )


def _scenario_rollup(
    records: Sequence[RunRecord], counts: ObservationCounts
) -> ScenarioRollUp:
    attempted = [record for record in records if record.attempted]
    unattempted = [record for record in records if not record.attempted]
    transport_failures = Counter(
        record.raw.transport_failure_category
        for record in attempted
        if record.raw is not None and record.raw.transport_failure_category is not None
    )
    failed_checks = Counter(
        record.structural.failed_check
        for record in attempted
        if record.structural is not None and not record.structural.structurally_valid
    )
    return ScenarioRollUp(
        scenario_id=records[0].scenario_id,
        step_id=records[0].step_id,
        mode=records[0].mode,
        required_structural_runs=counts.structural_runs_per_scenario,
        required_semantic_runs=counts.semantic_runs_per_scenario,
        attempted_runs=len(attempted),
        not_attempted_runs=len(unattempted),
        not_attempted_reasons=dict(
            Counter(record.not_attempted_reason for record in unattempted)
        ),
        transport_failures=dict(transport_failures),
        structurally_valid_runs=sum(1 for record in attempted if record.structurally_valid),
        structurally_invalid_runs=sum(
            1 for record in attempted if not record.structurally_valid
        ),
        failed_checks=dict(failed_checks),
        semantic_plans_presented=sum(
            1 for record in records if record.semantic_sample and record.plan is not None
        ),
    )


def _ordered_unique(values: Iterable[object]) -> list:
    seen: list = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
