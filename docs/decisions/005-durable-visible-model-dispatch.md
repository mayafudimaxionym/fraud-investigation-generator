# ADR 005: Durable Operation Boundary for Visible Streamlit Model Dispatch

## Decision

V0.5 will persist a narrowly scoped `AgentOperation` for each visible local-model request. The record distinguishes `PENDING_RENDER`, `RUNNING`, `COMPLETED`, `FAILED`, and `INTERRUPTED` states and records the applicable operation type, such as `START`, `MODIFY`, `DECLINE_REDIRECT`, or `DECLINE_RECONSIDER`.

The Streamlit execution that persists `PENDING_RENDER` must not call Ollama. It reruns to render the complete Working screen. A one-shot client-side render acknowledgement causes a later execution to atomically claim the operation from `PENDING_RENDER` to `RUNNING`. Only the successful claimant may invoke Ollama. Success persists the authoritative result and completes the operation; a terminated generation failure marks it failed; ambiguous process interruption marks it interrupted and requires an explicit retry with a new operation identity.

## Problem

Session state and a bare `st.rerun()` are presentation-local and cannot prove that a Working screen was painted before a blocking model call, prevent duplicate dispatch after refresh, or reconstruct interrupted work after restart. They also allow a successful persistence path to be disconnected from the investigator-visible screen that should present it.

## Alternatives considered

- Keep transient Streamlit session state and dispatch immediately after rerun. Rejected because the render/dispatch ordering and restart behavior are not durable.
- Add a generic queue, worker, or workflow engine. Rejected because V0.5 needs only a narrow visible local-model safety boundary and does not introduce background processing or V1 execution.
- Automatically replay `RUNNING` work after interruption. Rejected because an external Ollama request may already have run; replay could duplicate a material model invocation.

## Consequences

The application gains durable recovery and at-most-one automatic dispatch per operation. The qualifier is deliberate: it does not promise strict exactly-once external Ollama behavior across a process crash. A completed operation has one committed authoritative result; an ambiguous running operation requires visible Attention and a new explicit request. The successful authoritative result and the operation's `RUNNING` → `COMPLETED` transition commit atomically. A failed result/completion transaction cannot expose partial generated state as authoritative or mark the operation complete, while prior authoritative Modify or Decline human decisions remain preserved.

This decision does not authorize analytical execution, raw-data access, background jobs, or a general workflow system. It preserves evaluator isolation and the existing five-field proposal contract.
