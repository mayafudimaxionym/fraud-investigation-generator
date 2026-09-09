"""Reproducibility metadata for generated investigation cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GenerationMetadata:
    """Identifiers needed to reproduce a generated case."""

    master_seed: int
    generator_version: str
    scenario_version: str
    schema_version: str
    artifact_model: str | None = None
    prompt_version: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        """Return a JSON-serializable metadata record."""
        return asdict(self)
