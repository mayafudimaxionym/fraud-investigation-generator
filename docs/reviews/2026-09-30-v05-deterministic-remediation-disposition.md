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
| F2 | No committed evidence that completion refresh after Back and Resume is fixed | **Accepted.** Already gated by approved spec; no new decision | QA Automation Developer |
| F3 | A `RUNNING` operation orphaned inside its own process has no path to `INTERRUPTED`, and now reruns at 1 Hz forever | **Open — deferred by Product Owner decision** until the AXI-21 real-browser evidence is in | Product Owner, after AXI-21 |
| F4 | `SERVICE_UNAVAILABLE` now covers two transport conditions | **Accepted as correct.** Recorded in ADR 007; no change required | Closed here |
| F5 | Browser-driving test infrastructure in the unit suite, skippable, duplicated | **Accepted.** Playwright journey set is canonical | QA Automation Developer |

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

`PROJECT_STATUS.md` "Current uncommitted work" describes the remediations as uncommitted. They are committed. The genuinely uncommitted work is `tests/browser/` and the `pyproject.toml` test-extra change.
