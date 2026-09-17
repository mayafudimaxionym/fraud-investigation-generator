# Project Status

## Current stage

Synthetic-case fixture complete and frozen for the current agent-driven investigation-framework test. The project provides deterministic canonical generation, a separated investigator package, evaluator-only truth material, and bounded artifact generation while Python retains all canonical truth and validation ownership.

## Architecture baseline

- `docs/ARCHITECTURE.md` is the authoritative architecture and scope reference for the fraud investigation framework.
- New framework implementation must preserve the architectural invariants defined there.
- Any proposed implementation that conflicts with an invariant or materially changes the architecture must be identified explicitly and approved before implementation.
- The synthetic investigation package is frozen test infrastructure and should not be expanded unless framework testing exposes a concrete requirement.

## Development governance

- `AGENTS.md` provides standing AI-development instructions.
- `ROADMAP.md` is the authoritative milestone and sequencing reference.
- `docs/specs/V0_AGENT_HUMAN_APPROVAL_LOOP.md` is the current V0 milestone specification and is **DESIGN IN PROGRESS**.
- V0 implementation must not resolve its open product decisions through convenient defaults; those decisions require Product & Architecture planning and approval.
- `docs/ARCHITECTURE.md` remains the architecture baseline, and the synthetic-case fixture remains frozen unless framework testing identifies a concrete requirement.

## Completed

- Git is initialized, linked to GitHub, and the current commits are pushed.
- A minimal dependency-free Python project foundation exists.
- Deterministic sub-seed derivation and reproducibility metadata are defined.
- The canonical world includes entities, relationships, events, signals, private fraud campaigns, and the `CanonicalWorld` aggregate.
- `GroundTruthManifest` is separate from `InvestigatorViewManifest`.
- `ScenarioSpec` supports distinct competing hypotheses.
- `CaseBlueprint` declares private Python-owned correct-hypothesis and campaign-count constraints before generation.
- `CanonicalEvent` can optionally reference a canonical target entity, with deterministic target-reference validation.
- `InvestigatorViewManifest` supports optional visible relationship references with deterministic reference validation.
- `build_investigator_view_manifest()` deterministically exposes all raw entity, relationship, and event references without campaign or signal adjudication.
- `build_canonical_case()` deterministically composes a complete in-memory case from the existing world, truth, and investigator-view builders.
- A development-only seed-42 CSV inspection utility exports private/internal and investigator-visible views without defining the final persistence contract.
- `build_minimal_world()` deterministically creates a small investigation population with coordinated fraud campaigns, normal account history, legitimate background activity, overlapping lookalikes, shared beneficiaries/devices, and non-exclusive shared network infrastructure.
- `build_ground_truth_manifest()` deterministically assembles campaign truth, causal signals, red herrings, and the approved hypothesis from a canonical world and blueprint.
- Deterministic validation covers relationship, event, signal, artifact, and campaign references; campaign-to-ground-truth membership alignment; event precedence; world-level reference consistency; ground-truth hypothesis alignment; ground-truth references; and investigator-view references.
- Structured Python-to-model artifact contracts exist. Python validates language-only model responses, rejects model-assigned identity fields, and attaches approved language to Python-assigned artifact IDs and types.
- Investigator-only artifact contexts are explicitly built from visible entities, relationships, events, and safe scenario framing; they cannot receive ground truth, campaigns, signals, hypotheses, or campaign membership.
- A dependency-free Ollama adapter requests JSON language-only responses with configurable local settings, timeout handling, and deterministic-ish generation options. Tests use a fake client and do not require Ollama.
- Python deterministically derives investigator-visible `ArtifactAssertion` atoms from entities, relationships, and events. Factual model responses can only select/order/omit those assertions; Python renders final factual prose. Interpretive artifacts retain that factual spine and add a separately labeled non-authoritative interpretation.
- Python validates selected assertion IDs, canonical IDs mentioned in interpretations, and attaches artifacts immutably to a new `CanonicalCase` while updating the investigator view.
- A development-only local Ollama script generates five fixed requests for `development-case-42` and exports artifact text with investigator-visible structured data for review.
- The final deterministic `development-case-42` investigator package exports visible CSV evidence and three Python-owned text fixtures under `investigator/`, with private CSV records and ground truth physically separated under `evaluator_only/`.
- The final package exporter removes and recreates only its own fixed case directory, guaranteeing that obsolete development exports cannot survive in the package.
- Package tests verify directory-level truth separation and direct-conclusion leakage safeguards in the fixed text fixtures.

## Current uncommitted work

No uncommitted implementation work.

## Current blockers

- Python is unavailable on this agent shell's `PATH`, so the suite cannot be executed here. The accepted user-run local suite passed 81/81.
- Factual customer, support, and operational artifacts are structured and grounded, but are not yet realistic human documents. This remains a future concern and is intentionally outside the frozen synthetic-case fixture.
- Git whitespace checks have passed for the implemented changes.

## Next approved step

No further synthetic-case work is approved. The fixture is frozen for the current investigation-framework test; the next program phase is the main agent-driven investigation framework.

## Architectural constraints

- Python owns canonical IDs, timestamps, relationships, events, fraud truth, causal truth, deterministic generation, and validation.
- Ollama may generate constrained language, ambiguity, and human artifacts only; it must not invent canonical facts.
- Ground truth remains separate from investigator-visible evidence.
- The case graph and behavioral/relational evidence take precedence over independent row realism.
- Cases must remain reproducible from recorded seed and version metadata.
- Future implementation proceeds in small approved increments. Update this document after a future approved step only when that step materially changes project state; update ADRs only when an architectural decision changes.
