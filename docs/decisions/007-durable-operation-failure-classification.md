# ADR 007: Durable Operation Failure Classification Boundary

**Status:** Proposed — **not approved**. The Product Owner declined approval on 2026-09-30 and asked to discuss the decision first; that discussion is open on Paperclip AXI-17. This ADR is **not in force**: Implementation must not act on it, and no code change may be made against it until it is approved and this status line says so. Raised by the AXI-17 independent review of `a3bff81`.

## Decision

A persisted safe failure category is a claim about what happened to the investigator's request. It must be true. Two rules follow.

**1. `PERSISTENCE_ERROR` is reserved for a failed durable write.** It asserts that a generated result or an operation completion did not commit to the database. It must not carry any other failure. The step that performs the atomic durable commit classifies its own failures as `PERSISTENCE_ERROR`, because that is the only boundary that knows a write was attempted and did not succeed.

**2. An unclassified failure is `UNKNOWN_FAILURE`.** The outer durable-operation boundary must not assume a cause for an exception it did not classify. Where it cannot attribute a failure to a named category it records `UNKNOWN_FAILURE`, whose investigator presentation is already approved: *"The agent request ended with an unknown safe failure category."* No new category is introduced; `UNKNOWN_FAILURE` is already in `AGENT_OPERATION_FAILURE_CATEGORIES` and already has approved investigator copy.

**Transport failures are classified by exception family, not by a closed list of named types.** A transport failure is any failure of the model request/response cycle that surfaces as an `OSError` — which includes `urllib.error.URLError`, `ConnectionError`, `ssl.SSLError`, and a bare socket `OSError` — or as an `http.client.HTTPException`. Enumerating individual transport exception types is not sufficient, because any type outside the enumeration escapes untranslated and is then mislabelled by the outer boundary. Timeout and HTTP-status classification continue to take precedence over the transport family, as they do today.

**A transport failure reaching or reading from the local model service is `SERVICE_UNAVAILABLE`.** One category covers both "the service could not be reached" and "the connection was interrupted mid-generation". `docs/ARCHITECTURE.md` requires categories sufficient to distinguish failures *where recovery differs*; recovery for both is identical — the request has terminated, persisted state is authoritative, and explicit **Try again** creates a new operation identity. The investigator copy states both conditions: *"The local model service is unavailable or its connection was interrupted."*

**Unchanged by this decision:** one generation call per durable operation; no invisible retry; durable-operation dispatch and the atomic single claim; internal exception text is never investigator-visible.

## Problem

`a3bff81` translated three named transport exception types at the model client boundary (`URLError`, `ConnectionError`, `HTTPException`). It did not close the outer default. The durable-operation boundary in `investigation/approval_loop.py` catches `(ValueError, RuntimeError, OSError)` and labels every one of them `PERSISTENCE_ERROR`.

Any transport failure outside those three named types is therefore still recorded as `FAILED` with `failure_category = PERSISTENCE_ERROR` and presented to the investigator as *"The generated investigation state could not be saved safely."* That is a false statement about authoritative persisted state, and it is the same defect the V0.5 acceptance boundary item was written to close: *"an interrupted model connection must not be recorded as a persistence failure"* (`docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md`).

`ssl.SSLError` is the demonstrated case — it is an `OSError` and is not a `ConnectionError`, a `URLError`, or an `HTTPException`. A socket torn down under an in-flight read is a second case; Windows can surface it as a bare `OSError`. The independent review reproduced the escape at the client boundary and the resulting `PERSISTENCE_ERROR` end to end.

The root cause is the default, not the enumeration. Widening the enumeration alone leaves the next unenumerated exception mislabelled in exactly the same way.

## Reason

Choosing `PERSISTENCE_ERROR` as the default for unattributed failures inverts the safe direction. It converts *"we do not know what failed"* into a specific and load-bearing assertion that the database write failed — the one category that tells an investigator their generated work may have been lost. `UNKNOWN_FAILURE` is the honest default and was already added to the vocabulary for precisely this shape of case; the service layer simply never used it.

Classifying transport failures by family rather than by name makes the classification closed under future transport conditions instead of correct only for the three that were observed.

Keeping one `SERVICE_UNAVAILABLE` category for both transport conditions avoids adding an unapproved category for a distinction the investigator cannot act on differently. It is a deliberate application of the "where recovery differs" test rather than a gap.

## Consequences

- A store-write failure must still produce `PERSISTENCE_ERROR`. Existing coverage for the legitimate `PERSISTENCE_ERROR` path must continue to pass and must not be relaxed to `UNKNOWN_FAILURE`.
- Coverage must include at least one transport exception type that is an `OSError` but is not one of the three types `a3bff81` enumerated, asserted end to end through the persisted `failure_category` rather than only at the client boundary.
- This decision does not authorize broadening any handler to bare `Exception`. It constrains which category an unattributed failure receives, not how widely exceptions are caught.
- `investigation/models.py` is unchanged; no category is added or removed.

## Non-goals

- No change to the semantic contract, to prompt content, or to the human semantic-review boundary in `docs/decisions/006-human-semantic-review-boundary.md`.
- No change to the number of generation calls per durable operation.
- No new runtime dependency.
