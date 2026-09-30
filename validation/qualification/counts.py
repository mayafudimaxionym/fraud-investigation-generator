"""The approved observation counts, stated once.

Source of truth: `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 2.1,
settled by PO-2 and PO-8 (both approved).

The counts are **per semantic scenario, per candidate configuration**. Each of the
three V0.5 semantic scenarios (INITIAL, MODIFY, DECLINE/redirect) carries the full
count in its own right. The rejected reading -- a per-configuration total spread
across three scenarios -- reduces to one semantic run per scenario and reinstates
the single-observation problem PO-2 was approved to remove.
"""

from __future__ import annotations

from dataclasses import dataclass


#: Section 2.1: "10 runs of each scenario" -> 30 structural runs per configuration.
STRUCTURAL_RUNS_PER_SCENARIO = 10

#: Section 2.1: "3 runs of each scenario" -> 9 plans per configuration, each read in full.
SEMANTIC_RUNS_PER_SCENARIO = 3

#: The three V0.5 semantic scenarios, in chained order.
SEMANTIC_SCENARIO_MODES = ("INITIAL", "MODIFY", "DECLINE_REDIRECT")

#: Verbatim qualification required wherever N=3 is reported. Section 2.1 forbids
#: describing it as a reliability rate, and forbids pooling the nine runs into a
#: single stronger-sounding confidence claim.
SEMANTIC_SCREENING_GATE_QUALIFICATION = (
    "N=3 per scenario is a screening gate against gross instability. It is not a "
    "statistical reliability guarantee and does not establish a reliability rate. "
    "The gate is three-of-three within each scenario, judged independently per "
    "scenario; the nine runs are never pooled into a single confidence claim."
)

#: Section 2.1: unanimity across all nine runs is required before a configuration
#: may be presented for semantic acceptance, and the unit of semantic acceptance is
#: the candidate configuration as a whole. The judgement itself is Maya's (gate G4);
#: the harness never evaluates it.
SEMANTIC_ACCEPTANCE_RULE = (
    "Every one of the nine plans must be judged adequate by the Product Owner for "
    "the candidate configuration to be presented for semantic acceptance. A single "
    "inadequate run in a single scenario withholds the whole configuration. There is "
    "no partial or per-scenario pass. This judgement is made only by the Product "
    "Owner, reading every run in full; the harness records and presents, never judges."
)


@dataclass(frozen=True)
class ObservationCounts:
    """Runs per semantic scenario for one candidate configuration."""

    structural_runs_per_scenario: int = STRUCTURAL_RUNS_PER_SCENARIO
    semantic_runs_per_scenario: int = SEMANTIC_RUNS_PER_SCENARIO

    def __post_init__(self) -> None:
        for field_name in ("structural_runs_per_scenario", "semantic_runs_per_scenario"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.semantic_runs_per_scenario > self.structural_runs_per_scenario:
            raise ValueError(
                "semantic runs per scenario must not exceed structural runs per scenario; "
                "semantic runs are a labelled subset of the structural runs"
            )

    @property
    def chain_repetitions(self) -> int:
        """Chained executions needed to observe every scenario the required number of times.

        One chained execution (INITIAL -> MODIFY -> DECLINE_REDIRECT) yields one
        observation of each semantic scenario, so the structural count per scenario
        is also the number of chain repetitions.
        """
        return self.structural_runs_per_scenario

    def total_structural_runs(self, scenario_count: int = 3) -> int:
        """Total structural runs across scenarios. Reported per scenario, never as a rate."""
        return self.structural_runs_per_scenario * scenario_count

    def total_semantic_plans(self, scenario_count: int = 3) -> int:
        """Total plans the Product Owner reads in full, grouped by scenario."""
        return self.semantic_runs_per_scenario * scenario_count


APPROVED_COUNTS = ObservationCounts()
