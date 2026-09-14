"""Development-only local Ollama generation for the fixed inspection case."""

from __future__ import annotations

import csv
from pathlib import Path

from generator.artifacts.context import (
    ArtifactTask,
    build_investigator_artifact_context,
)
from generator.artifacts.ollama import OllamaArtifactClient, OllamaConfig
from generator.artifacts.orchestration import (
    attach_investigator_artifacts,
    generate_artifacts,
)
from generator.dev.inspect_case import (
    build_development_case,
    export_case_for_inspection,
)


def build_development_artifact_tasks() -> tuple[ArtifactTask, ...]:
    """Select a fixed, visible-only package of five human artifacts."""
    case = build_development_case()
    context = build_investigator_artifact_context(
        case.scenario, case.world, case.investigator_view
    )
    assertion_ids = {
        assertion.evidence_ids[0]: assertion.assertion_id
        for assertion in context.assertions
    }
    entity_ids = case.investigator_view.visible_entity_ids
    relationship_ids = case.investigator_view.visible_relationship_ids
    event_ids = case.investigator_view.visible_event_ids
    return (
        ArtifactTask(
            "artifact-001", "customer_support_message", "customer_reported_concern", "factual",
            assertion_ids=(assertion_ids[entity_ids[3]], assertion_ids[event_ids[2]], assertion_ids[event_ids[3]]),
            ambiguity_instructions=("Use an incomplete customer recollection.",),
        ),
        ArtifactTask(
            "artifact-002", "customer_email", "customer_facing_notification", "factual",
            assertion_ids=(assertion_ids[entity_ids[5]], assertion_ids[event_ids[6]], assertion_ids[event_ids[7]]),
            ambiguity_instructions=("Keep the sender uncertain about what happened.",),
        ),
        ArtifactTask(
            "artifact-003", "analyst_note", "analyst_observation_note", "factual",
            assertion_ids=(
                assertion_ids[relationship_ids[1]], assertion_ids[relationship_ids[5]],
                assertion_ids[event_ids[2]], assertion_ids[event_ids[3]],
                assertion_ids[event_ids[6]], assertion_ids[event_ids[7]],
            ),
            operational_framing="Record observations without a final conclusion.",
        ),
        ArtifactTask(
            "artifact-004", "operational_note", "operational_observation_summary", "factual",
            assertion_ids=(
                assertion_ids[relationship_ids[0]], assertion_ids[relationship_ids[4]],
                assertion_ids[event_ids[0]], assertion_ids[event_ids[4]],
            ),
        ),
        ArtifactTask(
            "artifact-005", "analyst_note", "alternative_analyst_interpretation", "interpretive",
            assertion_ids=(
                assertion_ids[event_ids[2]], assertion_ids[event_ids[3]],
                assertion_ids[event_ids[6]], assertion_ids[event_ids[7]],
            ),
            ambiguity_instructions=(
                "Offer one plausible but unconfirmed explanation based on the visible facts.",
            ),
        ),
    )


def generate_development_artifacts(output_root: Path) -> Path:
    """Generate and export the fixed case using the configured local Ollama model."""
    case = build_development_case()
    context = build_investigator_artifact_context(
        case.scenario,
        case.world,
        case.investigator_view,
        operational_framing="This is an internal investigation record.",
    )
    artifacts = generate_artifacts(
        context,
        build_development_artifact_tasks(),
        OllamaArtifactClient(OllamaConfig.from_environment()),
    )
    attached_case = attach_investigator_artifacts(case, artifacts)
    case_directory = export_case_for_inspection(attached_case, output_root)
    artifact_directory = case_directory / "investigator_view"
    with (artifact_directory / "artifacts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=("artifact_id", "artifact_type", "content"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "content": artifact.content,
            }
            for artifact in attached_case.artifacts
        )
    return case_directory


def main() -> None:
    """Generate development artifacts beneath the local output directory."""
    print(generate_development_artifacts(Path("output")))


if __name__ == "__main__":
    main()
