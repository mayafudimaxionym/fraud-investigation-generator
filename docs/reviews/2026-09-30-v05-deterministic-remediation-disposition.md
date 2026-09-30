# Disposition: independent review of the V0.5 deterministic remediations

**Review target:** `a3bff81` "Fix V0.5 resumed polling and transport recovery", reviewed against branch `v05-remediation-streamlit-presentation`.
**Reviewer:** Independent Reviewer (Paperclip AXI-17).
**Dispositioned by:** Product & Architecture Planner, 2026-09-30.
**Out of review scope:** `6e3f147` prompt-quality work and the Qwen semantic findings; manual acceptance; model-configuration retest.

## Standing conclusion

**Neither open V0.5 deterministic acceptance finding is closed.** Nothing in this document records V0.5 as acceptance-verified, and nothing here relaxes the acceptance boundary in `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` or the verdict definitions in `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md`.

| # | Finding | Disposition | Owner |
|---|---|---|---|
| F1 | `PERSISTENCE_ERROR` still reachable from a transport failure | **Accepted.** Defect. Proposed semantics in ADR 007, **which is not approved** | Product Owner — ADR 007 discussion. Implementation is not engaged |
| F2 | No committed evidence that completion refresh after Back and Resume is fixed | **Accepted.** Already gated by approved spec; no new decision. Journey set now committed; the Back/Resume journeys do not yet hold the operation `RUNNING` across the boundary | QA Automation Developer |
| F3 | A `RUNNING` operation orphaned inside its own process has no path to `INTERRUPTED` | **Closed by Product Owner decision 2026-09-30:** recorded as a named V0.5 exclusion, not a defect. The Planner’s 1 Hz thread-cancellation escalation is disproved and withdrawn | Closed |
| F4 | `SERVICE_UNAVAILABLE` now covers two transport conditions | **Accepted as correct.** Recorded in ADR 007; no change required | Closed here |
| F5 | Browser-driving test infrastructure in the unit suite, skippable, duplicated | **Accepted and closed.** Playwright journey set is canonical and committed; the duplicate raw-CDP test is removed | Closed |

## Product Owner decisions recorded 2026-09-30

Two decisions were put to the Product Owner on AXI-17. Both were answered.

**ADR 007 is not approved.** The Product Owner declined approval and asked to discuss the decision before it is settled. ADR 007 therefore states a proposal, not an approved rule. Nothing in it is in force, and **no implementation work on F1 is authorized**. The F1 defect itself is not in dispute — what is unsettled is which failure category an unattributed failure receives, which is precisely what ADR 007 decides. Until that discussion concludes, `PERSISTENCE_ERROR` remains reachable from a transport failure on `HEAD`, and the second open V0.5 deterministic acceptance finding stays open on that ground alone.

**F3 is deferred, not dropped.** The Product Owner chose to decide it after the AXI-21 real-browser journey evidence is available, which matches the recommendation on AXI-17: the START and DECLINE completion-refresh journeys drive precisely the condition F3 describes, so AXI-21 reports the resulting `agent_operations.status` and `failure_category` as diagnostic evidence for this decision. F3 is not an Implementation item and must not be picked up as one.

Neither decision changes the standing conclusion above. Neither open V0.5 deterministic finding is closed, and nothing is recorded as acceptance-verified.

## F1 — accepted as a defect; the fix direction was already determined

Verified in source. `investigation/approval_loop.py` catches `(ValueError, RuntimeError, OSError)` around the whole governed generation and labels every one of them `PERSISTENCE_ERROR`. `a3bff81` translated three named transport exception types at the client boundary and left that default intact, so any transport failure outside those three names — `ssl.SSLError` and a bare socket `OSError` being the demonstrated cases — is still persisted and presented as *"The generated investigation state could not be saved safely."*

This is not a new product question. `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` already makes *"an interrupted model connection must not be recorded as a persistence failure"* a V0.5 deterministic acceptance boundary item. The finding says that criterion is not met, and it is not met.

What needed deciding was the failure-classification rule, not whether to fix it. That rule is recorded in `docs/decisions/007-durable-operation-failure-classification.md`: the durable-commit step owns `PERSISTENCE_ERROR`, an unattributed failure is `UNKNOWN_FAILURE`, and transport failures are classified by exception family rather than by a closed list of names. ADR 007 introduces no new failure category and no new investigator copy.

Implementation owns the code change once ADR 007 is approved. Implementation must not widen the enumeration alone; the default is the root cause.

## F2 — accepted; the approved spec already makes this gate

Verified in source. `tests/test_streamlit_lifecycle.py::_run_with_running_refresh` fabricates the widget trigger value, so the `AppTest` run never evaluates the refresh snippet. That is a legitimate seam for testing the *server's* response to a refresh trigger, and it is honest as far as it goes — but it cannot fail for the product reason, and the assertions `a3bff81` added pass unchanged against the pre-fix one-shot timer. The committed browser test drives a hand-built object literal in a bare HTML page with no Streamlit server, no component mounting, no Back and no Resume.

No new decision is needed. `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` §"Required real-browser journey set" already makes *"completion refresh after Back and Resume, for START and for DECLINE"* part of V0.5 deterministic acceptance, precisely because in-process tests cannot observe it. Finding 1 therefore cannot be recorded as closed on the committed evidence, and the in-process suite passing is not evidence to the contrary.

The reviewer's open question — whether the one-shot timer was the actual cause of the observed manual-acceptance failure — is answered by running those journeys, not by further reading. That is the highest-value evidence available and is the immediate next action.

## F3 — open; Product Owner decision required

Verified in source. `interrupt_operations_from_previous_process` sweeps only rows whose `runner_instance_id` differs from the current process, and runner identity is stable for the process lifetime by approved design. A `RUNNING` operation whose claiming script thread dies while the Streamlit process survives is therefore never swept: it stays `RUNNING`, owned by the live runner, and projects Agent Working indefinitely.

`a3bff81` changes the consequence. The refresh was a one-shot `setTimeout`; it is now a 1 Hz `setInterval`. A stalled operation that previously produced one rerun and then a static screen now reruns the whole application every second, indefinitely, with no Attention state and no investigator escape other than Back.

The canonical documents do not cover this case, and that is why it is not Implementation's to settle. `docs/ARCHITECTURE.md` scopes `INTERRUPTED` to *"ambiguous prior-process work"*, and the spec scopes the transition to *"server/process interruption"*. Same-process session loss may be a deliberate exclusion or an omission. Deciding it is a V0.5 scope question. The alternatives and the recommendation are in the Product Owner decision request on AXI-17.

## F4 — accepted as correct; no change required

`SERVICE_UNAVAILABLE` covering both an unreachable service and a connection interrupted mid-generation is compliant. `docs/ARCHITECTURE.md` requires categories sufficient to distinguish failures *where recovery differs*, and recovery here is identical: the request has terminated, persisted state is authoritative, and explicit **Try again** creates a new operation identity. Splitting the category would add an unapproved category for a distinction the investigator cannot act on. The revised copy states both conditions and leaks no host or URL.

The reviewer was right that the spec had not fixed this copy and that investigator wording is not Implementation's to change unilaterally. It is now recorded in ADR 007, so it is specified rather than merely tolerated.

## F5 — accepted; the Playwright journey set is canonical

Two real-browser mechanisms now exist for the same purpose: raw CDP over `websockets` inside `tests/test_streamlit_app.py`, and Playwright in the uncommitted `tests/browser/`. **`tests/browser/` is the canonical real-browser mechanism for V0.5**, because it is what the approved spec describes — a harness-controlled fake model transport configured through the existing `OLLAMA_*` deployment configuration, with an isolated server and database per scenario. The raw-CDP test in the unit suite duplicates it, silently disappears when Chrome/Edge or `websockets` is absent, and races on its debugging port. It is not the gate and must not be relied on as one.

This is test infrastructure only. It introduces no product change and no runtime dependency; `playwright` and `pytest-playwright` belong under `[project.optional-dependencies] test`.

## Verified intact — recorded so it is not re-litigated

The review confirmed, and this disposition accepts, that `a3bff81` leaves unchanged: durable-operation dispatch and the atomic single claim; one generation call per durable operation; the semantic contract and prompt content; the human semantic-review boundary in `docs/decisions/006-human-semantic-review-boundary.md`; and every architectural invariant in `docs/ARCHITECTURE.md` §17. No evaluator-only data and no internal exception text reaches an investigator surface. `tests/test_proposal_agent.py`'s interrupted-read regression test is genuine coverage of finding 2's mechanism and fails without the fix.

## Known stale state

`PROJECT_STATUS.md` "Current uncommitted work" describes the remediations as uncommitted. They are committed. The `tests/browser/` journey set and the `pyproject.toml` test-extra change were also uncommitted when this disposition was first written; they were committed in `52f4fc7` and `38f3c88`.

## Real-browser gate evidence, recorded 2026-09-30 (AXI-21)

The canonical Playwright journey set is now committed (`52f4fc7`, `38f3c88`) and was run against product `HEAD` `ab8e678`. This is the evidence the approved spec requires, and the Product Owner deferred the F3 decision until it existed. It is diagnostic evidence only; no acceptance verdict is issued here and neither deterministic finding is recorded as closed.

Results: five journeys PASS, one FAILS.

### Finding 2 (transport disconnect) — confirmed still open, now permanently gated

`test_transport_disconnect_is_not_persistence_failure` FAILS against `HEAD`. `tests/browser/injected_streamlit.py` raises a bare `OSError` from the generation request — precisely the unclassified transport failure the review identified, outside the three exception types `a3bff81` enumerates. The persisted row is `START / FAILED / PERSISTENCE_ERROR`, and the investigator is told their work may not have been saved.

This is the review's F1 reproduced end to end, through a real browser, against the real service and store. It removes any remaining doubt: **finding 2 is open, and the committed journey will keep failing until it is fixed.** The fix direction is ADR 007, which is not approved and is not in force.

### Finding 1 (completion refresh) — materially advanced, not yet closable as specified

What is genuinely demonstrated, for START: `test_working_precedes_dispatch_and_refresh_is_safe` holds the model response so the operation is durably `RUNNING`, reloads, resumes, confirms the Working screen and exactly one dispatch, confirms one refresh interval is active, then releases and confirms the completed proposal becomes visible **without a restart** and the interval is cleared (`created=1`, `cleared=1`, `active=0`). That is the defect condition, and it passes. The one-generation-call-per-durable-operation contract holds throughout.

What is not yet demonstrated: the approved spec requires *completion refresh after Back and Resume, for START and for DECLINE*. In both journeys named for that clause, `_initial_proposal` waits for the **Needs Review** heading before clicking **Back to Investigations**. The operation is therefore already `COMPLETED` at the Back boundary, and Resume re-renders it from persisted state without the refresh mechanism being involved. Neither journey holds the response across Back and Resume, and `DECLINE` has no coverage at all of a delayed result arriving across a navigation boundary.

The gap is in the journey construction, not in the product and not in the approved requirement. `FakeOllama.hold()` / `release()` already exist and are used elsewhere in the same module, so closing it is a narrow change to two existing journeys. Owner: QA Automation Developer. This is an application of already-approved acceptance criteria, not a new gate.

### F3 — the Planner's severity escalation is disproved; the reviewer's narrow case stands

The disposition above escalated F3 on the theory that a 1 Hz rerun of the session executing the generation could cancel the claiming script thread, converting a rare stall into a routine one. **The evidence contradicts that.** The Working journey holds an operation `RUNNING` with the refresh interval confirmed active, and both completion journeys persist `COMPLETED` with `failure_category` null. The 1 Hz refresh did not cancel the claiming thread or strand any operation. The escalation is withdrawn and should not be re-raised without new evidence.

F3 therefore reverts to exactly the scope the Independent Reviewer gave it: a `RUNNING` operation whose claiming thread dies while the Streamlit process survives is never swept to `INTERRUPTED`. No journey exercises that condition, and `docs/ARCHITECTURE.md` scopes `INTERRUPTED` to prior-process work, so it may be a deliberate exclusion. `test_interrupted_operation_requires_explicit_retry` confirms the prior-process path itself works correctly: `INTERRUPTED`, then an explicit linked retry to `COMPLETED`, with no implicit regeneration.

### F5 — closed

The duplicate raw-CDP browser test was removed from `tests/test_streamlit_app.py` in `52f4fc7`. One canonical real-browser mechanism now exists, the journey set is in version control, and the "spec-required gate is untracked" condition recorded above no longer holds.

## F3 resolved by Product Owner decision, 2026-09-30

Presented with the real-browser evidence, the Product Owner chose to **record the same-process stalled `RUNNING` case as a known V0.5 limitation and an explicit non-goal**, rather than add a duration-based transition to `INTERRUPTED` now or commission a further targeted journey.

This is recorded in `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md` under **Scope boundaries → Named exclusion: same-process stalled `RUNNING` operations**, so it is a deliberate exclusion in the canonical specification rather than a decision living only in issue history. It must not be raised again as a V0.5 defect. It is a V0.6 candidate.

F3 is closed. The open V0.5 deterministic findings remain the two original ones, and neither is closed.
