"""Comparable per-run experiment records.

Section 4 requires **raw capture before parsing**: the exact prompt, the exact raw
response, the model digest, the Ollama version, the duration and any transport
failure are recorded before the contract is applied. An unparseable response is
data, not a lost run, so `RawCapture` is complete and writable on its own and
`StructuralOutcome` is attached afterwards.

A record carries no score of any kind. Section 4 prohibits any automated value
converting quality into an acceptance signal, because a number in an experiment
record will be read as a verdict however it is labelled. What a record carries about
content is the content itself, for a human to read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from validation.qualification.contract import StructuralOutcome


class NotAttemptedReason(str, Enum):
    """Why a scenario observation does not exist. Never silently dropped."""

    #: The preceding chain step produced no real prior state, so this step could not
    #: run against it. Fabricating prior state would defeat the point of chaining.
    CHAIN_PREDECESSOR_UNAVAILABLE = "CHAIN_PREDECESSOR_UNAVAILABLE"


@dataclass(frozen=True)
class RawCapture:
    """Everything captured verbatim before any parsing is attempted."""

    prompt: str
    prompt_sha256: str
    duration_seconds: float
    raw_response: str | None = None
    transport_failure_category: str | None = None
    transport_failure_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt:
            raise ValueError("prompt must be the exact rendered prompt text")
        if self.prompt_sha256 != sha256_text(self.prompt):
            raise ValueError("prompt_sha256 must be the digest of the recorded prompt")
        if not isinstance(self.duration_seconds, (int, float)) or self.duration_seconds < 0:
            raise ValueError("duration_seconds must be a non-negative number")
        if (self.raw_response is None) == (self.transport_failure_category is None):
            raise ValueError(
                "a capture records either a raw response or a transport failure category"
            )

    @property
    def transport_succeeded(self) -> bool:
        return self.raw_response is not None

    def as_record(self) -> dict[str, object]:
        return {
            "prompt": self.prompt,
            "prompt_sha256": self.prompt_sha256,
            "duration_seconds": self.duration_seconds,
            "raw_response": self.raw_response,
            "transport_failure_category": self.transport_failure_category,
            "transport_failure_message": self.transport_failure_message,
        }


@dataclass(frozen=True)
class PresentedPlan:
    """Parsed content held for human reading only. No derived judgement."""

    competing_explanations: tuple[str, ...]
    plan_steps: tuple[str, ...]
    action: str
    purpose: str
    why_now: str
    data_to_be_used: str
    expected_output: str

    def as_record(self) -> dict[str, object]:
        return {
            "competing_explanations": list(self.competing_explanations),
            "plan_steps": list(self.plan_steps),
            "proposal": {
                "action": self.action,
                "purpose": self.purpose,
                "why_now": self.why_now,
                "data_to_be_used": self.data_to_be_used,
                "expected_output": self.expected_output,
            },
        }


@dataclass(frozen=True)
class RunRecord:
    """One observation of one semantic scenario, for one candidate configuration."""

    run_id: str
    experiment_id: str
    recorded_at: str
    configuration_label: str
    configuration_settings: dict[str, object]
    environment: dict[str, object]
    scenario_id: str
    step_id: str
    mode: str
    chain_id: str
    chain_repetition: int
    step_index: int
    run_index: int
    semantic_sample: bool
    attempted: bool
    not_attempted_reason: str | None = None
    raw: RawCapture | None = None
    structural: StructuralOutcome | None = None
    plan: PresentedPlan | None = None

    def __post_init__(self) -> None:
        for field_name in ("run_id", "experiment_id", "configuration_label", "scenario_id",
                           "step_id", "mode", "chain_id", "recorded_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("chain_repetition", "step_index", "run_index"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.attempted:
            if self.raw is None:
                raise ValueError("an attempted run must record its raw capture")
            if self.not_attempted_reason is not None:
                raise ValueError("an attempted run must not record a not-attempted reason")
        else:
            if self.not_attempted_reason is None:
                raise ValueError("an unattempted run must record why")
            if self.raw is not None or self.structural is not None:
                raise ValueError("an unattempted run has no capture and no structural outcome")

    @property
    def structurally_valid(self) -> bool:
        return self.structural is not None and self.structural.structurally_valid

    def data_text(self) -> str:
        """Every data-bearing string in this record, for the evaluator-isolation scan.

        Deliberately excludes harness-authored explanatory prose. The scan asks whether
        evaluator-only *material* entered the record; a harness sentence that names the
        check "no evaluator-only references" is documentation, not a leak, and scanning
        it would train everyone to ignore a guard that cries wolf.
        """
        parts: list[str] = [
            self.run_id, self.experiment_id, self.configuration_label,
            self.scenario_id, self.step_id, self.mode, self.chain_id,
            self.not_attempted_reason or "",
            *(str(value) for value in self.configuration_settings.values()),
            *(str(value) for value in self.environment.values()),
        ]
        if self.raw is not None:
            parts.extend([
                self.raw.prompt,
                self.raw.raw_response or "",
                self.raw.transport_failure_message or "",
            ])
        if self.structural is not None:
            parts.append(self.structural.failure_detail or "")
        if self.plan is not None:
            parts.extend([
                *self.plan.competing_explanations,
                *self.plan.plan_steps,
                self.plan.action, self.plan.purpose, self.plan.why_now,
                self.plan.data_to_be_used, self.plan.expected_output,
            ])
        return "\n".join(parts)

    def as_record(self) -> dict[str, object]:
        """Serialize for durable per-run storage outside version control."""
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "recorded_at": self.recorded_at,
            "configuration_label": self.configuration_label,
            "configuration_settings": dict(self.configuration_settings),
            "environment": dict(self.environment),
            "scenario_id": self.scenario_id,
            "step_id": self.step_id,
            "mode": self.mode,
            "chain_id": self.chain_id,
            "chain_repetition": self.chain_repetition,
            "step_index": self.step_index,
            "run_index": self.run_index,
            "semantic_sample": self.semantic_sample,
            "attempted": self.attempted,
            "not_attempted_reason": self.not_attempted_reason,
            "raw": None if self.raw is None else self.raw.as_record(),
            "structural": None if self.structural is None else {
                "structurally_valid": self.structural.structurally_valid,
                "failed_check": self.structural.failed_check,
                "failure_detail": self.structural.failure_detail,
            },
            "plan": None if self.plan is None else self.plan.as_record(),
        }


def sha256_text(value: str) -> str:
    """Stable digest of exact text, used to compare prompts across runs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def serialize_record(record: RunRecord) -> str:
    """Render one record as canonical JSON text for scanning and writing."""
    return json.dumps(record.as_record(), indent=2, sort_keys=True, ensure_ascii=False)
