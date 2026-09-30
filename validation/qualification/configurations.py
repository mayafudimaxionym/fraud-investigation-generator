"""Candidate configurations and read-only environment capture.

Section 2.1: a **candidate configuration** is a recorded local model, version,
settings and prompt configuration. Sweeps vary the configuration without editing
scenario text, so a configuration owns the model and settings and a scenario owns
the investigator text.

The environment capture here issues only read-only `GET /api/version` and
`GET /api/tags` requests so a run record can carry the Ollama version and the exact
model digest. It is metadata capture, not a generation path, and it never blocks a
run: anything it cannot determine is recorded as unavailable rather than guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import Request, urlopen

from investigation.proposal_agent import ProposalOllamaConfig


#: Identifier for the prompt configuration under test. The product builds the prompt
#: from `build_proposal_prompt`, which the harness must not modify, so the prompt
#: configuration is identified rather than parameterised. Each run additionally
#: records the SHA-256 of its exact rendered prompt, which is the durable evidence.
PRODUCT_PROMPT_CONFIGURATION = "investigation.proposal_agent.build_proposal_prompt"


@dataclass(frozen=True)
class CandidateConfiguration:
    """One recorded model, settings and prompt configuration in a sweep."""

    label: str
    ollama: ProposalOllamaConfig
    prompt_configuration: str = PRODUCT_PROMPT_CONFIGURATION
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-empty string")
        if not isinstance(self.ollama, ProposalOllamaConfig):
            raise ValueError("ollama must be a ProposalOllamaConfig")
        if not isinstance(self.prompt_configuration, str) or not self.prompt_configuration.strip():
            raise ValueError("prompt_configuration must be a non-empty string")

    def recorded_settings(self) -> dict[str, object]:
        """The settings recorded with every run. Base URL is deliberately excluded."""
        return {
            "model": self.ollama.model,
            "timeout_seconds": self.ollama.timeout_seconds,
            "temperature": self.ollama.temperature,
            "seed": self.ollama.seed,
            "prompt_configuration": self.prompt_configuration,
        }


@dataclass(frozen=True)
class ModelEnvironment:
    """Read-only environment facts captured alongside a sweep."""

    ollama_version: str | None = None
    model_digest: str | None = None
    capture_error: str | None = None

    def as_record(self) -> dict[str, object]:
        return {
            "ollama_version": self.ollama_version,
            "model_digest": self.model_digest,
            "capture_error": self.capture_error,
        }


def capture_model_environment(config: ProposalOllamaConfig) -> ModelEnvironment:
    """Read the Ollama version and the configured model's digest. Never raises."""
    errors: list[str] = []
    version = _read_version(config, errors)
    digest = _read_model_digest(config, errors)
    return ModelEnvironment(
        ollama_version=version,
        model_digest=digest,
        capture_error="; ".join(errors) or None,
    )


def _read_version(config: ProposalOllamaConfig, errors: list[str]) -> str | None:
    payload = _read_json(f"{config.base_url}/api/version", config, errors, "version")
    if isinstance(payload, dict) and isinstance(payload.get("version"), str):
        return payload["version"]
    if payload is not None:
        errors.append("version response had an unexpected shape")
    return None


def _read_model_digest(config: ProposalOllamaConfig, errors: list[str]) -> str | None:
    payload = _read_json(f"{config.base_url}/api/tags", config, errors, "tags")
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        if payload is not None:
            errors.append("tags response had an unexpected shape")
        return None
    for item in payload["models"]:
        if isinstance(item, dict) and item.get("name") == config.model:
            digest = item.get("digest")
            return digest if isinstance(digest, str) else None
    errors.append("the configured model was not listed by the local service")
    return None


def _read_json(
    url: str, config: ProposalOllamaConfig, errors: list[str], label: str
) -> object | None:
    try:
        with urlopen(Request(url, method="GET"), timeout=config.timeout_seconds) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except (OSError, URLError, HTTPException, TimeoutError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{label} unavailable: {type(error).__name__}")
        return None
