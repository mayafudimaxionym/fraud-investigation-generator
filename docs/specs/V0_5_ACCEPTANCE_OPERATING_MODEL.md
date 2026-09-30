# V0.5 — Acceptance Operating Model & Validation Architecture

**Status:** APPROVED in part — see §8. Product Owner decisions PO-1, PO-2, PO-3, PO-4 and PO-5 are approved and recorded here. Material authored by the Product & Architecture Planner that has not been separately approved remains PROPOSED pending gate G1.

**Scope of this document:** product behavior, V0.5 validation architecture, and V0.5 acceptance requirements.

**Companion document:** agent orchestration, capacity handling, task sizing, role ownership and provider governance live in `docs/AGENT_OPERATING_MODEL.md`. That split was approved as PO-5. Organizational policy is not restated here.

**Related canonical documents:** `docs/ARCHITECTURE.md`, `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md`, `docs/decisions/006-human-semantic-review-boundary.md`, `docs/decisions/005-durable-visible-model-dispatch.md`, `docs/decisions/003-ollama-artifact-boundary.md`.

---

## Why this is needed

The `0d4a79e` acceptance attempt failed for two unrelated reasons in one session:

- **The application behaved wrongly** — after Back and Resume, completion refresh did not happen; an interrupted model connection was recorded as `PERSISTENCE_ERROR` instead of a transport failure. Deterministic, reproducible, nothing to do with prose quality.
- **The model's planning was weak** — the initial proposed action covered both plan steps instead of being narrower; a Modify result responded to the instruction but contradicted the requested 72-hour scope.

Mixed together, a prose problem can block a code fix and a lifecycle bug can be blamed on the model. They need different tooling, different evidence, and different decision rights.

---

## 1. Already approved — unchanged by this document

From ADR 006 and the V0.5 specification:

- Python validates **structure only** — exact JSON shape, one five-field proposal, at least two competing explanations, at least two ordered plan steps, no duplicates, no model-assigned IDs/status/authorization, no evaluator-only references, plus lineage and atomicity invariants. No keyword overlap, edit distance, similarity, embeddings, or fixed stage labels.
- **Semantic adequacy is a human judgment**, at runtime by the investigator and at acceptance by the Product Owner.
- **One generation call per durable `AgentOperation`.** No second adjudication call, no repair call, no hidden retry.
- **Automated Streamlit lifecycle/integration coverage is already required and already passing.**
- `llama3:8b` is not a required baseline; acceptance must record a configuration that passes representative INITIAL/MODIFY/DECLINE scenarios.
- The 14-item acceptance boundary; the frozen synthetic fixture.
- Two deterministic findings are open with local remediations pending review and retest.
- The Qwen semantic failures are recorded as a **separate, still-open** Planning decision (see PO-3).

---

## 2. Responsibility split — who owns what

| Question | Owner | Decides? |
|---|---|---|
| **A.** Does the application behave correctly? | QA & Workflow Validation Engineer | Reports PASS/FAIL/BLOCKED. Does not define expected behavior. |
| **B.** Does a response satisfy the machine-checkable contract? | Product validator at runtime **and** the qualification harness offline | Reports counts only |
| **C.** Is the generated planning semantically strong? | AI Model Qualification Researcher | **Analyses and recommends only — never "good enough."** |
| **D.** Is V0.5 accepted? | **Maya (Product Owner)** | **Decides** |

**Deliberate overlap:** B is checked in two places on purpose — that redundancy is what tells us whether a structural failure is a product defect or a model-fitness problem. Both must derive from **one** contract definition (§7).

**Must never merge.** QA must not judge prose. A structurally valid but weak direction is a **PASS** for QA — ADR 006 states that weak-but-valid content becomes authoritative and goes to Needs Review, so QA asserting otherwise would reintroduce the rejected lexical validator through the test suite. The Researcher must not accept the application or convert analysis into a verdict. Neither role defines expected behavior. No agent makes the semantic acceptance decision.

### 2.1 Observation counts for a candidate configuration (PO-2, approved; scope settled by PO-8, approved)

A **candidate configuration** is a recorded local model, version, settings and prompt configuration.

**Counts are per semantic scenario, per candidate configuration (PO-8, approved).** V0.5 acceptance uses three semantic scenarios — INITIAL, MODIFY, DECLINE/redirect. Each scenario carries the full count in its own right. The alternative reading, 3 semantic runs spread across three scenarios, would yield one run per scenario and reinstate exactly the single-observation problem PO-2 was approved to remove; it is rejected.

| Evidence class | Runs required | Total per candidate configuration | Judged by | Passing rule |
|---|---|---|---|---|
| **Structural validity** | **10 runs of each scenario** | 30 runs | Machine (the product's contract code) | Reported as counts and failure categories; no automatic pass threshold is set here |
| **Semantic adequacy** | **3 runs of each scenario** | **9 plans**, each read in full | **Maya**, reading every run in full | **Unanimous — all 9 runs** (3 of 3 in every scenario) must be judged adequate for the configuration to be presented for semantic acceptance |

A single inadequate run in a single scenario is sufficient to withhold the configuration from semantic acceptance. There is no partial or per-scenario pass: the unit of semantic acceptance is the candidate configuration as a whole.

**N=3 per scenario is a screening gate against gross instability. It is not a statistical reliability guarantee.** Three adequate runs out of three bound the true failure rate only loosely — roughly "below about 60%" at conventional confidence, per scenario. Detecting a one-in-twenty failure mode would require dozens of runs, which is out of proportion at this milestone. No document, report, or acceptance record may describe N=3 as establishing a reliability rate, and the nine-run total must not be aggregated into a single stronger-sounding confidence claim: the gate is three-of-three within each scenario, not nine-of-nine pooled.

The counts are asymmetric because the costs are asymmetric: structural validity is machine-counted and costs only local compute, so repetition is cheap and buys a genuinely useful validity rate; semantic adequacy costs Maya's reading time, so it stays small and every run is presented in full.

**Presentation requirement.** A semantic acceptance package presents the nine plans grouped by scenario, each labelled with its scenario and run index, so Maya can see stability within a scenario rather than an undifferentiated set.

---

## 3. QA & Workflow Validation architecture

**Position.** The existing in-process Streamlit lifecycle tests stay as the primary deterministic gate and are not replaced. QA adds what in-process tests structurally cannot see: **a real browser driving a real running Streamlit server.** Both open findings are exactly that kind — "completion refresh does not happen in a real browser after Back and Resume" is a browser-and-server fact.

**Determinism without touching product code.** The seam already exists: `ProposalOllamaConfig.from_environment()` reads `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` / `OLLAMA_TEMPERATURE` / `OLLAMA_SEED`, and the client uses exactly two endpoints — `GET /api/tags` (preflight) and `POST /api/generate`. QA therefore points the real application at a **harness-controlled fake Ollama endpoint**, scripted per scenario to produce a valid response, an invalid response, a slow response, a timeout, a mid-response disconnect, a 404 model-unavailable, or an unreachable service. Every failure category and every Working/Needs-Review timing becomes reproducible, and generation calls become countable — which is how the one-call contract gets proven. This is test infrastructure using existing deployment configuration. **No product change, no new product dependency.**

**Required behaviors.** Isolated server and database per scenario with clean startup and shutdown, never touching the real `investigations.sqlite`; stable locators and condition-based waits, never fixed sleeps; arbitrary objective / Modify instruction / Decline guidance text as scenario parameters; Modify asserted as original-`MODIFIED`-plus-instruction-before-generation, Working-before-dispatch, exactly one dispatch, correct lineage, no duplicate on rerender; Decline committed before reconsideration with an independent replacement and no second Decline on retry; every failure category, ambiguous `RUNNING` → `INTERRUPTED` with no auto-redispatch, safe refresh during `PENDING_RENDER` and `RUNNING`, Back not cancelling pending work, Resume reconstruction, and a visible result after delayed success **without restart**; declared expected-vs-actual per step; structured evidence (scenario id, commit, config, persisted rows, page snapshots, logs) sufficient for Implementation to reproduce without asking questions; and any single scenario runnable in isolation.

**Evidence rule.** Where the database or read projection is stronger evidence than the page, assert against that. Browser assertions cover what is genuinely presentational — what the investigator sees, when, and in what order. Clicking drives the journey; it is not proof that state is correct.

**Verdicts.**

- **PASS** — every declared expected outcome met, with evidence.
- **FAIL** — a declared outcome not met and the scenario's own setup was sound; carries a reproduction.
- **BLOCKED** — no trustworthy verdict exists: the application would not start, the fake transport misbehaved, a locator is gone, the environment is wrong, or the expected behavior is not defined in any canonical document.

BLOCKED is never reported as a product defect. BLOCKED-as-FAIL sends Implementation to fix working code; BLOCKED-as-PASS falsely advances acceptance.

**Recorded non-goal:** no in-house Playwright replacement is designed now — post-V1 consideration only.

---

## 4. Model Qualification Harness

**Principle.** Answers "how good is this model at this job?" with no Streamlit, no browser, and no investigation database. Offline research tooling, not a product component.

**Consistency with ADR 006, stated explicitly.** The harness is not a second generation call, not a semantic-adjudication boundary, and not a repair or retry path. It lives entirely outside the product's request path, so it does not weaken the one-call contract. Nothing it produces may be wired into the application.

**Seam (reuse, do not modify):** `InvestigatorPackageContext`, `ProposalGenerationRequest` (INITIAL / MODIFY / DECLINE_REDIRECT), `build_proposal_prompt`, `ProposalOllamaConfig` / `OllamaProposalClient`, `parse_proposal_model_response` and its contract checks.

**Capabilities.** Version-controlled named scenarios (package, objective text, mode, prior direction, source proposal, instruction, guidance); **multi-turn chaining** (INITIAL → MODIFY → DECLINE against the real generated prior state — instruction adherence and constraint preservation are only observable across steps); sweeps across models and configurations without editing scenario text; **repetition at the counts recorded in §2.1**; raw capture of the exact prompt, exact raw response, model digest, Ollama version, duration and any transport failure **before parsing** (an unparseable response is data, not a lost run); deterministic structural validation reusing the product's contract; comparable per-run records plus roll-ups of validity rate and failure categories; and evaluator isolation — ground truth, campaigns, signals and hypotheses must never enter a prompt or an experiment record.

**Structural checks (machine, reported as counts):** parses as JSON; exact approved shape; one five-field proposal; at least two competing explanations; at least two ordered plan steps; no exact duplicates after trivial normalization; no model-assigned IDs/status/timestamps/authorization; no evaluator-only references; generation succeeded, or failed with a recorded category.

**Semantic criteria (human, supported by analysis):** comprehensiveness; investigative usefulness; whether explanations are genuinely distinct; prioritization and sequencing; whether the action is narrower than the direction; whether Modify materially follows the instruction; whether stated constraints such as a 72-hour window are preserved rather than silently contradicted; whether a Decline replacement addresses the guidance; omissions; groundedness.

**Hard prohibition.** No automated score, rubric-scoring model, or LLM-as-judge converting quality into an acceptance signal. ADR 006 rejected exactly this class of false assurance, and a number in an experiment record will be read as a verdict however it is labelled.

---

## 5. Evidence and routing

**Minimum evidence per role.** **QA** — scenario id, commit, config, expected vs actual, persisted state, page evidence, logs, verdict, reproduction. **Implementation** — what changed, which canonical requirement it satisfies, the test added, the verification result, and what it did *not* change. **Researcher** — scenario/model/config matrix, run counts at the §2.1 counts, structural counts and failure categories, written analysis with quoted excerpts, recommendation framed as a recommendation. **Planner** — disposition of each ambiguity, document updated or escalated. **Maya** — recorded decision.

| Finding | Goes to |
|---|---|
| Deterministic defect (FAIL + reproduction) | Implementation; QA reruns that scenario only |
| Expected behavior ambiguous (BLOCKED) | Product & Architecture — QA never invents the expectation |
| Test-infrastructure defect | Whoever owns the automation code (see `docs/AGENT_OPERATING_MODEL.md`); not an acceptance blocker in itself |
| Structural contract failure | Validator bug → Implementation. Model cannot satisfy the contract → Researcher evidence → Product & Architecture → Maya. Never resolved by quietly loosening the contract. |
| Semantic weakness | Researcher analysis → **Maya**. Never routed to Implementation as a "fix". |
| All QA scenarios PASS | Recorded as deterministic acceptance evidence — necessary, not sufficient |

**Escalation rule for both validation roles:** if producing a verdict would require deciding what the product *should* do, stop and escalate.

---

## 6. Human decision gates

- **G1** — approve this operating model.
- **G2** — approve the §8 decisions.
- **G3** — accept the deterministic QA result as application acceptance evidence.
- **G4** — **decide whether a candidate configuration's planning is good enough**, having read every semantic run required by §2.1.
- **G5** — approve the recorded qualified configuration.
- **G6** — declare V0.5 acceptance-verified.
- **G7** — approve any product-behavior, contract, fixture or acceptance-criteria change arising from validation.

No gate is satisfied by agent agreement, by silence, or by an automated score.

---

## 7. Effect on existing V0.5 architecture

**Additive validation infrastructure only.** No product behavior change, no model-contract change, and no change to the operation lifecycle, the one-call contract, the semantic boundary, evaluator isolation, or the frozen fixture.

**One genuine architecture constraint: the machine-checkable contract must have a single definition.** The harness consumes the product's validation code rather than restating it. Two definitions drift, and a drifted harness reports model fitness against a contract the product does not enforce. *Candidate ADR — not yet written; promoting it requires Maya's approval (OPEN-3).*

**Specification changes made under the approved decisions:**

- **PO-1 (approved)** — `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` records the required real-browser journey set.
- **PO-2 (approved)** — `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` acceptance boundary items 4, 6 and 7, its semantic-enforcement boundary, and the qualification paragraph of `docs/decisions/006-human-semantic-review-boundary.md` now state the observation counts and the screening-gate qualification explicitly.

No other specification change and no other ADR amendment.

**Deliberately not resolved — schema-constrained generation / model-contract compatibility.** The product currently requests Ollama's free-form JSON mode (`format: "json"`) and validates the parsed result in Python. Moving to schema-constrained decoding is a separate decision that was explicitly excluded from this work and **requires a separately scoped task**. The harness will incidentally produce relevant evidence (structural validity rates per model); **that evidence must not be used to change the generation call** without a separate proposal and Maya's approval. See §8, OPEN-1.

---

## 8. Product Owner decisions

### Approved

**PO-1 — APPROVED (option b).** A minimal Playwright journey set gates the relevant V0.5 deterministic acceptance, covering only the real-browser behaviors in-process tests cannot prove and that have already failed: completion refresh after Back/Resume for START and DECLINE, Working-before-dispatch, transport-disconnect classification, refresh during `PENDING_RENDER` and `RUNNING`, and interrupted-operation recovery. Remaining journeys are built afterwards as regression coverage and do not gate acceptance.

**PO-2 — APPROVED (asymmetric repetition).** Structural validity: **10 runs**. Semantic adequacy: **3 runs**, all of which must be judged adequate for the configuration to be presented for semantic acceptance. **N=3 is a screening gate against gross instability, not a statistical reliability guarantee.** Scope of the counts settled by PO-8 below. Recorded in full in §2.1 and reflected in the V0.5 specification and ADR 006.

**PO-3 — APPROVED.** The open Qwen semantic findings become the Researcher's first commissioned experiment: is the narrowness/scope failure specific to that configuration, general to the prompt, or general to local models of that size? Not decided on a single observation.

**PO-4 — APPROVED.** Scenario definitions, harness definitions/code and summary records are version-controlled under one validation directory. Raw model responses, screenshots, run databases and logs stay out of version control, referenced by run id. No existing loose file in the repository root has been moved, deleted or committed under this decision; reconciling those artifacts is separate work (§10).

**PO-5 — APPROVED (split the documents).** Product behavior and V0.5 acceptance requirements stay in this specification. Agent orchestration and governance material moved to `docs/AGENT_OPERATING_MODEL.md`. Organizational truth is not left only in Paperclip.

**PO-6 and PO-7 — APPROVED.** Both are organizational governance decisions; they are recorded in `docs/AGENT_OPERATING_MODEL.md`.

**PO-8 — APPROVED (per scenario).** The PO-2 counts apply **per semantic scenario** within a candidate configuration: 10 structural runs and 3 semantic runs of each of INITIAL, MODIFY and DECLINE/redirect — 30 structural runs and 9 plans read per configuration. Unanimity is required across all nine. The per-configuration-total reading is rejected because it reduces to one semantic run per scenario. Recorded in full in §2.1 and reflected in the V0.5 specification and ADR 006.

### Open

**OPEN-1 — Schema-constrained generation / model-contract compatibility.** Deliberately not investigated here. Requires a separately scoped task before any change to the generation call. **Unresolved.**

**OPEN-2 — Qwen semantic findings.** Open; sequenced under PO-3 as the Researcher's first commissioned experiment, not yet commissioned.

**OPEN-3 — Single-contract-definition ADR.** §7 records the constraint; promoting it to a numbered ADR requires Maya's approval.

---

## 9. Proposed sequence after approval

1. **Product & Architecture** — record approved decisions in the specification and ADRs *(done for PO-1 through PO-7)*; prepare two scoped implementation handoffs.
2. **Independent Reviewer, then QA** — the already-pending review and retest of the two deterministic remediations. Not blocked by harness work and should not wait for it.
3. **QA automation build** — fake-Ollama transport plus the PO-1 journey set. Owner per `docs/AGENT_OPERATING_MODEL.md`. No product code change.
4. **QA** — run it against the current branch; report PASS/FAIL/BLOCKED with evidence.
5. **Implementation** — fix any FAIL preserving approved behavior; QA reruns only the affected scenarios.
6. **Implementation** — Model Qualification Harness (may run in parallel with 4–5).
7. **Researcher** — the PO-3 experiment; analysis and recommendation at the §2.1 counts.
8. **Maya** — G4/G5: judge semantic adequacy, approve a qualified configuration.
9. **Maya** — G6: declare V0.5 acceptance-verified, or direct further work.

---

## 10. Explicitly outside scope

Any product behavior, contract or fixture change · resolving schema-constrained generation (OPEN-1) · resolving the Qwen findings · any automated semantic scoring or LLM-as-judge · a second generation call, repair call or hidden retry · an in-house Playwright replacement (post-V1 only) · background jobs, queues, workflow engines · V1 analytical execution · WAL or other SQLite concurrency changes · implementing a provider usage monitor · defining capacity thresholds · reconciling the loose acceptance artifacts currently in the repository root.
