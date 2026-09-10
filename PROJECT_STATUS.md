# Project Status

## Current stage

Foundation and domain-contract stage. The project defines the Python-owned case model, information boundaries, and initial deterministic validation rules. It does not yet generate cases, invoke Ollama, or write investigation datasets.

## Completed

- Git is initialized, linked to GitHub, and the current commits are pushed.
- A minimal dependency-free Python project foundation exists.
- Deterministic sub-seed derivation and reproducibility metadata are defined.
- The canonical world includes entities, relationships, events, signals, private fraud campaigns, and the `CanonicalWorld` aggregate.
- `GroundTruthManifest` is separate from `InvestigatorViewManifest`.
- `ScenarioSpec` supports distinct competing hypotheses.
- Deterministic validation covers relationship, event, signal, artifact, and campaign references; event precedence; world-level reference consistency; ground-truth hypothesis alignment; ground-truth references; and investigator-view references.
- Structured Python-to-model artifact contracts exist. Python validates language-only model responses, rejects model-assigned identity fields, and attaches approved language to Python-assigned artifact IDs and types.

## Current uncommitted work

The private `FraudCampaign` contract, its world membership, campaign-reference validation, and ground-truth campaign resolution are uncommitted pending review and approval.

## Current blockers

- Python is unavailable on this agent shell's `PATH`, so the pytest suite has not yet been executed.
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
