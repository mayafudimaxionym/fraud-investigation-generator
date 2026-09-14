"""Small, dependency-free Ollama adapter for constrained artifact language."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from generator.artifacts.contracts import (
    ArtifactGenerationRequest,
    ArtifactGenerationResponse,
    parse_artifact_generation_response,
)


class ArtifactModelClient(Protocol):
    """A fakeable provider of structured artifact-presentation responses."""

    def generate(self, request: ArtifactGenerationRequest) -> ArtifactGenerationResponse:
        """Generate one constrained language response."""


@dataclass(frozen=True)
class OllamaConfig:
    """Minimal local Ollama configuration."""

    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    seed: int = 42

    @classmethod
    def from_environment(cls) -> "OllamaConfig":
        """Load local-only settings without a configuration framework."""
        import os

        return cls(
            base_url=os.environ.get("OLLAMA_BASE_URL", cls.base_url).rstrip("/"),
            model=os.environ.get("OLLAMA_MODEL", cls.model),
            timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "60")),
            temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0")),
            seed=int(os.environ.get("OLLAMA_SEED", "42")),
        )


class OllamaArtifactClient:
    """HTTP adapter with no artifact business logic beyond prompt transport."""

    def __init__(self, config: OllamaConfig) -> None:
        self._config = config

    def generate(self, request: ArtifactGenerationRequest) -> ArtifactGenerationResponse:
        payload = {
            "model": self._config.model,
            "prompt": build_artifact_prompt(request),
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._config.temperature,
                "seed": self._config.seed,
            },
        }
        http_request = Request(
            f"{self._config.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self._config.timeout_seconds) as reply:
                body = json.loads(reply.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(f"Ollama artifact generation failed: {error}") from error
        response_text = body.get("response")
        if not isinstance(response_text, str):
            raise RuntimeError("Ollama artifact response did not contain string response")
        try:
            model_payload = json.loads(response_text)
        except json.JSONDecodeError as error:
            raise RuntimeError("Ollama artifact response was not JSON") from error
        if not isinstance(model_payload, dict):
            raise RuntimeError("Ollama artifact response JSON must be an object")
        return parse_artifact_generation_response(model_payload)


def build_artifact_prompt(request: ArtifactGenerationRequest) -> str:
    """Create a selection-only prompt sent to Ollama."""
    response_shape = (
        '{"selected_assertion_ids": ["..."]}'
        if request.mode == "factual"
        else '{"selected_assertion_ids": ["..."], "interpretation": "..."}'
    )
    assertions = "\n".join(
        f"- {assertion.assertion_id}: {assertion.rendered_fact}"
        for assertion in request.assertions
    ) or "- No assertions were supplied."
    ambiguity = "\n".join(f"- {item}" for item in request.ambiguity_instructions)
    return (
        "Return JSON only. Do not write an artifact. Python will render all factual prose.\n"
        f"Artifact type: {request.artifact_type}\n"
        f"Purpose: {request.purpose}\n"
        f"Mode: {request.mode}\n"
        f"Required response shape: {response_shape}\n"
        "Select zero or more supplied assertion IDs in the desired presentation order. "
        "Each selected_assertion_id may appear at most once. "
        "Do not return content, facts, canonical IDs, labels, or metadata. "
        "For factual mode, do not return interpretation. "
        "For interpretive mode only, interpretation may be a plausible non-authoritative human explanation, "
        "but it must not add concrete events, relationships, outcomes, identities, timestamps, or canonical IDs.\n"
        f"Operational framing: {request.operational_framing or 'None'}\n"
        f"Eligible Python-rendered assertions:\n{assertions}\n"
        f"Ambiguity instructions:\n{ambiguity or '- None'}"
    )
