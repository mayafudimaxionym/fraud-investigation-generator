# Project Status

## Current stage

Foundation and initial deterministic world-generation stage. The project defines the Python-owned case model, information boundaries, deterministic validation rules, and a minimal in-memory canonical-world builder. It does not invoke Ollama or write investigation datasets.

## Completed

- Git is initialized, linked to GitHub, and the current commits are pushed.
- A minimal dependency-free Python project foundation exists.
- Deterministic sub-seed derivation and reproducibility metadata are defined.
- The canonical world includes entities, relationships, events, signals, private fraud campaigns, and the `CanonicalWorld` aggregate.
- `GroundTruthManifest` is separate from `InvestigatorViewManifest`.
- `ScenarioSpec` supports distinct competing hypotheses.
- `CaseBlueprint` declares private Python-owned correct-hypothesis and campaign-count constraints before generation.
- `CanonicalEvent` can optionally reference a canonical target entity, with deterministic target-reference validation.
- `build_minimal_world()` deterministically creates campaign-local shared-device fraud sequences with beneficiary convergence, plus a campaign-external shared-device lookalike with intentionally overlapping transfer timing and distinct beneficiaries.
- `build_ground_truth_manifest()` deterministically assembles campaign truth, causal signals, red herrings, and the approved hypothesis from a canonical world and blueprint.
- Deterministic validation covers relationship, event, signal, artifact, and campaign references; campaign-to-ground-truth membership alignment; event precedence; world-level reference consistency; ground-truth hypothesis alignment; ground-truth references; and investigator-view references.
- Structured Python-to-model artifact contracts exist. Python validates language-only model responses, rejects model-assigned identity fields, and attaches approved language to Python-assigned artifact IDs and types.

## Current uncommitted work

No uncommitted implementation work.

## Current blockers

- Python is unavailable on this agent shell's `PATH`, so the suite cannot be executed here. The latest user-run local suite passed 55/55.
- Git whitespace checks have passed for the implemented changes.

## Next approved step

Continue through closely related, low-risk implementation steps. Stop for approval before architectural decisions, new dependencies, Ollama integration, persistence or file-format choices, dataset generation, or substantial scope changes.

## Architectural constraints

- Python owns canonical IDs, timestamps, relationships, events, fraud truth, causal truth, deterministic generation, and validation.
- Ollama may generate constrained language, ambiguity, and human artifacts only; it must not invent canonical facts.
- Ground truth remains separate from investigator-visible evidence.
- The case graph and behavioral/relational evidence take precedence over independent row realism.
- Cases must remain reproducible from recorded seed and version metadata.
- Future implementation proceeds in small approved increments. Update this document after a future approved step only when that step materially changes project state; update ADRs only when an architectural decision changes.
