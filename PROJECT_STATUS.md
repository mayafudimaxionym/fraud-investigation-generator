# Project Status

## Current stage

V0 — Agent / Human Approval Loop is **IMPLEMENTED / ACCEPTANCE VERIFIED**. V0.5 — Investigator-Ready Investigation Loop is **IMPLEMENTED / AUTOMATICALLY VERIFIED / NOT YET ACCEPTANCE-VERIFIED**. Remediation Tasks 1–4, the required Streamlit lifecycle automation, and the approved human semantic-review boundary are implemented and passing. Qualified-model selection and recorded manual acceptance remain pending.

## Architecture baseline

- `docs/ARCHITECTURE.md` is the authoritative architecture and scope reference for the fraud investigation framework.
- New framework implementation must preserve the architectural invariants defined there.
- Any proposed implementation that conflicts with an invariant or materially changes the architecture must be identified explicitly and approved before implementation.
- The synthetic investigation package is frozen test infrastructure and should not be expanded unless framework testing exposes a concrete requirement.

## Development governance

- `AGENTS.md` provides standing AI-development instructions.
- `ROADMAP.md` is the authoritative milestone and sequencing reference.
- `docs/specs/V0_AGENT_HUMAN_APPROVAL_LOOP.md` is the approved V0 milestone specification; its implementation and formal acceptance are complete.
- `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` is the approved V0.5 behavior, scope, and acceptance specification. Durable-operation persistence, service orchestration, read projection, Streamlit presentation, deterministic structural validation, and lifecycle automation are implemented and automatically verified. Qualified-model testing and manual semantic acceptance remain pending, so V0.5 is not yet acceptance-verified.
- Future milestones still require separate planning and approval.
- `docs/ARCHITECTURE.md` remains the architecture baseline, and the synthetic-case fixture remains frozen unless framework testing identifies a concrete requirement.

## Completed

- Git is initialized, linked to GitHub, and the current commits are pushed.
- **V0 Agent / Human Approval Loop — IMPLEMENTED / ACCEPTANCE VERIFIED.** Tasks 1–6 delivered minimal V0 domain contracts, local SQLite persistence, governed investigator-package access, a local proposal agent, approval-loop orchestration, and a local Streamlit UI. Task 7 formal local acceptance verified all eight V0 acceptance criteria.
- V0 runs with local Streamlit, local SQLite, and local Ollama (`llama3:8b`). It loads only governed investigator-package context and safe dataset inventory metadata; evaluator-only material, private truth, and raw structured rows remain outside the agent boundary.
- The local proposal agent returns one structured five-field next-action proposal and a provisional plan. Approve, Modify, and Decline are persisted; Modify retains the original proposal and decision while creating a lineage-preserving revised proposal.
- SQLite restart reconstruction of proposal/decision history and Modify lineage is verified without chat history or LLM memory. Analytical execution, analytical results, and raw-data querying are intentionally not implemented in V0.
- Formal acceptance and final automated verification passed **150 tests, 1 skipped**. The skip is the Windows physical-symlink environment limitation; direct path-escape protection remains tested.
- A Streamlit/SQLite thread-affinity lifecycle defect found during acceptance was corrected and verified: each Streamlit execution creates and closes its own SQLite-backed approval service, avoiding reuse of a thread-affine connection.
- **V0.5 remediation Task 1 — COMPLETE / MERGED.** `AgentOperation` defines the approved `PENDING_RENDER`, `RUNNING`, `COMPLETED`, `FAILED`, and `INTERRUPTED` lifecycle. SQLite persistence supports atomic START preparation, authoritative Modify/Decline plus pending-operation transitions, single-claim dispatch, explicit retry lineage, previous-process interruption, and atomic success completion for START, MODIFY, and decline reconsideration.
- Task 1 persistence tests cover operation-trigger integrity, terminal-state safety, retry provenance, interruption, and rollback of partial generated results. The current full automated baseline is **270 passed, 1 skipped**; the skip remains the Windows physical-symlink environment limitation.
- **V0.5 remediation Task 2 — IMPLEMENTED / AUTOMATED VERIFICATION PASSED.** The effective objective is the sole initial investigator input. The service can prepare START, MODIFY, and DECLINE as durable `PENDING_RENDER` operations without invoking the model; atomically claim and dispatch one operation; persist safe failure categories; complete generated results through Task 1's atomic boundaries; interrupt ambiguous previous-process work; and create explicit linked retry attempts without duplicating human decisions.
- Task 2 adds service coverage for pre-dispatch durability, single-claim dispatch, authoritative Modify-before-generation state, categorized failure, retry identity/provenance, objective reconstruction, interruption without replay, and schema-v3 failure migration. The current full automated baseline is **275 passed, 1 skipped**.
- **V0.5 remediation Task 3 — IMPLEMENTED / AUTOMATED VERIFICATION PASSED.** Read projection now preserves context-integrity precedence, derives Working and operation-specific Attention from the latest durable attempt, exposes only investigator-safe operation state, validates Modify revisions against matching attempts, rejects simultaneous active operations, and includes operation timestamps in activity ordering.
- The landing projection now emits one current/latest investigation per safe package association while retaining separate unassociated legacy recovery entries. Focused coverage verifies context precedence, working, failure, interruption, retry supersession, Modify integrity, active-operation conflicts, activity timestamps, and package grouping. The current full automated baseline is **290 passed, 1 skipped**.
- **V0.5 remediation Task 4 — IMPLEMENTED / AUTOMATED VERIFICATION PASSED.** Streamlit persists each model-bound request before rerendering, renders Working before a one-shot browser acknowledgement and atomic claim, uses process-scoped runner identity, reconstructs Resume from authoritative persistence, preserves presentation-only Back navigation, exposes operation-specific recovery and explicit retry, and uses deterministic database configuration.
- **Required Streamlit lifecycle automation — IMPLEMENTED / PASSING.** Real Streamlit/session/rerun integration coverage verifies START, MODIFY, DECLINE/redirect, failure/retry, interruption, refresh idempotency, one generation call per durable operation, authoritative final projection, and human semantic-review context.
- **V0.5 semantic-enforcement boundary — APPROVED.** Python validates response structure, explicit private-reference safeguards, canonical-state ownership, durable lifecycle, lineage, and atomicity, but does not use lexical heuristics to certify arbitrary natural-language meaning. Semantic adequacy of direction, action narrowness, and responsiveness to Modify/Decline text is judged by the investigator at runtime and by manual acceptance for the qualified local model configuration. One generation call remains permitted per durable operation; no second semantic evaluator, automatic repair call, structured investigator controls, or hidden retry is added.
- `llama3:8b` is no longer a required qualified V0.5 baseline. It may remain configurable, but V0.5 acceptance must record a local model/version/settings/prompt configuration that passes representative INITIAL, MODIFY, and DECLINE/redirect semantic scenarios.
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

- Task 4 presentation/lifecycle remediation and the human semantic-review boundary are implemented and automatically verified for independent review.
- Local generated/runtime artifacts may exist outside version control, including `investigations.sqlite`, `output/`, external `antigravity_critic_v05*.md` audits, and manual-acceptance databases. They are not authoritative project state.

## Current blockers

- Factual customer, support, and operational artifacts are structured and grounded, but are not yet realistic human documents. This remains a future concern and is intentionally outside the frozen synthetic-case fixture.
- `python -m pip install -e .` has a known pre-existing setuptools flat-layout package-discovery tooling issue. It is not a V0 functional failure and did not prevent local runtime acceptance.

## Next approved step

Perform **qualified-model testing and manual V0.5 acceptance** using a recorded local model, model version, settings, and prompt configuration. Manual acceptance must verify meaningful direction, action narrowness, and representative Modify/Decline responsiveness. Do not mark V0.5 acceptance-verified until that recorded configuration passes the approved scenarios.

No WAL change is approved without a demonstrated locking requirement. No further synthetic-case work is approved; the fixture remains frozen. V1 — Controlled Analytical Execution has not started and requires separate planning and approval.

## Architectural constraints

- Python owns canonical IDs, timestamps, relationships, events, fraud truth, causal truth, deterministic generation, and validation.
- Ollama may generate constrained language, ambiguity, and human artifacts only; it must not invent canonical facts.
- Ground truth remains separate from investigator-visible evidence.
- The case graph and behavioral/relational evidence take precedence over independent row realism.
- Cases must remain reproducible from recorded seed and version metadata.
- Future implementation proceeds in small approved increments. Update this document after a future approved step only when that step materially changes project state; update ADRs only when an architectural decision changes.
