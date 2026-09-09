"""References exposed to an investigator for one generated case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvestigatorViewManifest:
    """Visible case references without any canonical fraud adjudication."""

    visible_entity_ids: tuple[str, ...]
    visible_event_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        identifier_groups = {
            "visible_entity_ids": self.visible_entity_ids,
            "visible_event_ids": self.visible_event_ids,
            "artifact_ids": self.artifact_ids,
        }
        for field_name, identifiers in identifier_groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{field_name} must not contain duplicates")
