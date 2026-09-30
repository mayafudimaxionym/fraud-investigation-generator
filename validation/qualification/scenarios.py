"""Version-controlled named scenario definitions, loaded from JSON under this package.

PO-4 (approved): scenario definitions, harness definitions/code and summary records
are version-controlled under one validation directory. Raw model responses, run
databases and logs stay out of version control, referenced by run id.

A scenario definition names a **chain** whose steps are the V0.5 semantic scenarios in
order: INITIAL -> MODIFY -> DECLINE_REDIRECT. Chaining is required by section 4 because
instruction adherence and constraint preservation are only observable across steps;
each non-initial step therefore runs against the **real generated prior state** from
the step before it, never against hand-written prior state.

Sweeps vary model and configuration without editing scenario text: a scenario carries
the package, objective, mode, instruction and guidance, and nothing about which model
runs it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from validation.qualification.counts import SEMANTIC_SCENARIO_MODES


SCENARIO_DIRECTORY = Path(__file__).resolve().parent / "scenarios"

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _require_non_blank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ScenarioStep:
    """One semantic scenario within a chain: a mode plus its investigator text."""

    step_id: str
    mode: str
    objective: str
    investigator_instruction: str | None = None
    decline_guidance: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.step_id, "step_id")
        if self.mode not in SEMANTIC_SCENARIO_MODES:
            raise ValueError(f"mode must be one of {SEMANTIC_SCENARIO_MODES}")
        if not isinstance(self.objective, str):
            raise ValueError("objective must be a string (it may be intentionally blank)")
        if self.mode == "INITIAL":
            if self.decline_guidance is not None:
                raise ValueError("INITIAL must not carry decline_guidance")
        elif self.mode == "MODIFY":
            _require_non_blank(self.investigator_instruction, "investigator_instruction")
            if self.decline_guidance is not None:
                raise ValueError("MODIFY must not carry decline_guidance")
        else:
            _require_non_blank(self.decline_guidance, "decline_guidance")
            if self.investigator_instruction is not None:
                raise ValueError(
                    "DECLINE_REDIRECT must use decline_guidance instead of an instruction"
                )


@dataclass(frozen=True)
class ScenarioDefinition:
    """A named, version-controlled chained scenario for one candidate configuration sweep."""

    scenario_id: str
    name: str
    description: str
    package_directory: Path
    steps: tuple[ScenarioStep, ...]

    def __post_init__(self) -> None:
        _require_non_blank(self.scenario_id, "scenario_id")
        _require_non_blank(self.name, "name")
        _require_non_blank(self.description, "description")
        if not isinstance(self.package_directory, Path):
            raise ValueError("package_directory must be a Path")
        if not self.steps:
            raise ValueError("a scenario must define at least one step")
        modes = tuple(step.mode for step in self.steps)
        if modes[0] != "INITIAL":
            raise ValueError("a chained scenario must begin with an INITIAL step")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("scenario step IDs must be unique")

    def step_for_mode(self, mode: str) -> ScenarioStep:
        """Return the single step covering one semantic scenario."""
        matches = tuple(step for step in self.steps if step.mode == mode)
        if len(matches) != 1:
            raise ValueError(f"scenario does not define exactly one {mode} step")
        return matches[0]


def load_scenario(path: Path) -> ScenarioDefinition:
    """Load one version-controlled scenario definition from JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ValueError(f"scenario definition is unreadable: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"scenario definition is not valid JSON: {path}") from error
    return _scenario_from_payload(payload, path)


def load_scenarios(directory: Path = SCENARIO_DIRECTORY) -> tuple[ScenarioDefinition, ...]:
    """Load every version-controlled scenario definition, ordered by scenario id."""
    if not directory.is_dir():
        raise ValueError(f"scenario directory does not exist: {directory}")
    scenarios = tuple(
        load_scenario(path) for path in sorted(directory.glob("*.json"))
    )
    if len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
        raise ValueError("scenario IDs must be unique across the scenario directory")
    return scenarios


def _scenario_from_payload(payload: object, path: Path) -> ScenarioDefinition:
    if not isinstance(payload, dict):
        raise ValueError(f"scenario definition must be a JSON object: {path}")
    unexpected = set(payload) - {
        "scenario_id", "name", "description", "package_directory", "steps"
    }
    if unexpected:
        raise ValueError(
            f"scenario definition has unexpected fields {sorted(unexpected)}: {path}"
        )
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"scenario definition requires a non-empty steps list: {path}")
    return ScenarioDefinition(
        scenario_id=payload.get("scenario_id"),
        name=payload.get("name"),
        description=payload.get("description"),
        package_directory=_resolve_package_directory(payload.get("package_directory"), path),
        steps=tuple(_step_from_payload(step, path) for step in raw_steps),
    )


def _step_from_payload(payload: object, path: Path) -> ScenarioStep:
    if not isinstance(payload, dict):
        raise ValueError(f"scenario step must be a JSON object: {path}")
    unexpected = set(payload) - {
        "step_id", "mode", "objective", "investigator_instruction", "decline_guidance"
    }
    if unexpected:
        raise ValueError(f"scenario step has unexpected fields {sorted(unexpected)}: {path}")
    return ScenarioStep(
        step_id=payload.get("step_id"),
        mode=payload.get("mode"),
        objective=payload.get("objective", ""),
        investigator_instruction=payload.get("investigator_instruction"),
        decline_guidance=payload.get("decline_guidance"),
    )


def _resolve_package_directory(value: object, path: Path) -> Path:
    """Resolve a repository-relative package path. Never an arbitrary working directory."""
    relative = _require_non_blank(value, "package_directory")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(
            f"scenario package_directory must be repository-relative so the definition "
            f"stays portable under version control: {path}"
        )
    return _REPOSITORY_ROOT / candidate
