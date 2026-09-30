# Project Status

## Current stage

V0 — Agent / Human Approval Loop is **IMPLEMENTED / ACCEPTANCE VERIFIED**. V0.5 — Investigator-Ready Investigation Loop is **IMPLEMENTED / AUTOMATICALLY VERIFIED / NOT YET ACCEPTANCE-VERIFIED**. Remediation Tasks 1–4 and the approved human semantic-review boundary are implemented. Manual acceptance against commit `0d4a79e` failed: the tested model configuration did not pass every semantic scenario, resumed-operation completion refresh remained defective, and an interrupted model connection was misclassified. Deterministic remediation is under review; successful recorded manual acceptance remains pending.

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
- **Latest V0.5 manual acceptance attempt — FAILED / FOLLOW-UP REQUIRED.** Manual acceptance against commit `0d4a79e` used Ollama `0.34.3`, `qwen3:30b-a3b-instruct-2507-q4_K_M` digest `19e422b…b272fe`, a verified 65,536-token context, temperature `0`, seed `42`, and a 900-second timeout. Initial failed because its proposed action encompassed both plan steps rather than one narrower action. Modify materially responded but contradicted the requested 72-hour scope by reintroducing historical-data comparison. Decline/redirect passed. These semantic results remain a separate Planning decision.
- The same acceptance attempt reproduced the open completion-refresh defect after Back and Resume for initial and Decline operations, and found that an interrupted local-model HTTP connection was inaccurately persisted and presented as `PERSISTENCE_ERROR`. Deterministic remediations are implemented locally but remain open pending independent review and manual retest. V0.5 remains not acceptance-verified.
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

- The presentation-only recurring completion refresh and local-model transport-disconnect classification remediations are **committed in `a3bff81`**, not uncommitted. They remain pending independent review and manual retest. Browser callback, Streamlit lifecycle, transport, atomic failure, and explicit linked-retry coverage are included. The durable-operation dispatch, one-call contract, semantic contract, and human semantic-review boundary are unchanged.
- Local generated/runtime artifacts may exist outside version control, including `investigations.sqlite`, `output/`, external `antigravity_critic_v05*.md` audits, and manual-acceptance databases. They are not authoritative project state.

## Validation tooling

- The **Model Qualification Harness** is implemented under `validation/qualification/` per `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` §4, at the §2.1 observation counts (10 structural and 3 semantic runs of each of INITIAL, MODIFY and DECLINE/redirect, per candidate configuration). It is offline research tooling: no Streamlit, no browser, no investigation database, and nothing it produces is wired into the application. It consumes the product's own contract code rather than restating it, produces no automated quality score of any kind, and does not change product behavior. See `validation/README.md`.
- No qualification campaign has been run with it. Running experiments is separate work owned by the AI Model Qualification Researcher, and `validation/qualification/summaries/` is empty until one is run.

## Current blockers

- No recorded local model/version/settings/prompt configuration has passed every representative V0.5 semantic scenario. The recorded Qwen configuration passed Decline/redirect but failed Initial action narrowness and Modify scope consistency.
- The completion-refresh and transport-classification acceptance findings remain open until the local remediations are independently reviewed and manually retested.
- Factual customer, support, and operational artifacts are structured and grounded, but are not yet realistic human documents. This remains a future concern and is intentionally outside the frozen synthetic-case fixture.
- `python -m pip install -e .` has a known pre-existing setuptools flat-layout package-discovery tooling issue. It is not a V0 functional failure and did not prevent local runtime acceptance.

## Next approved step

Independently review and manually retest the completion-refresh and transport-classification remediations. Planning must separately decide the response to the recorded Qwen semantic failures before another qualified-model acceptance attempt. Do not mark V0.5 acceptance-verified until both deterministic findings are closed and one recorded model configuration passes all approved semantic scenarios.

No WAL change is approved without a demonstrated locking requirement. No further synthetic-case work is approved; the fixture remains frozen. V1 — Controlled Analytical Execution has not started and requires separate planning and approval.

## Architectural constraints

- Python owns canonical IDs, timestamps, relationships, events, fraud truth, causal truth, deterministic generation, and validation.
- Ollama may generate constrained language, ambiguity, and human artifacts only; it must not invent canonical facts.
- Ground truth remains separate from investigator-visible evidence.
- The case graph and behavioral/relational evidence take precedence over independent row realism.
- Cases must remain reproducible from recorded seed and version metadata.
- Future implementation proceeds in small approved increments. Update this document after a future approved step only when that step materially changes project state; update ADRs only when an architectural decision changes.
