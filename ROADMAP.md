# Project Roadmap

## Product goal

Build an on-premises agent-driven fraud investigation framework with human controls over AI analytical work and persistent institutional memory.

## Completed

- **Synthetic investigation fixture — COMPLETE / FROZEN.** The deterministic investigation package is accepted test infrastructure and must not be expanded unless framework testing exposes a concrete requirement.
- **Architecture baseline — COMPLETE.** `docs/ARCHITECTURE.md` defines the approved architectural invariants.

## Completed milestone

### V0 — Agent / Human Approval Loop — IMPLEMENTED / ACCEPTANCE VERIFIED

**Goal:**

`Investigator package → local investigation agent → structured analytical proposal → human approve / modify / decline → persisted decision`

V0 does not execute proposed analysis.

Formal local acceptance verified governed case loading, local proposal generation, persisted Approve / Modify / Decline decisions, Modify revision lineage, SQLite restart reconstruction, no analytical execution, and evaluator isolation.

**Exit criteria:**

- Runs locally.
- Uses investigator-visible evidence only.
- Uses a local LLM.
- Produces a structured analytical proposal.
- Renders a human review step.
- Supports approve, modify, and decline decisions.
- Persists the decision outside the chat.
- Never provides ground truth to the agent.
- Uses no cloud or external LLM.

## Current milestone

### V0.5 — Investigator-Ready Investigation Loop — REMEDIATION IN PROGRESS

Manual acceptance exposed a Streamlit lifecycle discrepancy: successful persisted work was not reliably presented through the interactive UI. The approved remediation adds a narrow durable visible-dispatch boundary, corrected lifecycle/recovery presentation, deterministic database location, and automated real Streamlit lifecycle/integration verification while preserving V0's governed local loop. It does not authorize analytical execution. V1 Controlled Analytical Execution remains deferred and has not started.

**Completed remediation increment:**

- Task 1 delivered and merged the narrow `AgentOperation` domain lifecycle and SQLite persistence primitives for pending preparation, atomic claim, failure/interruption, retry lineage, and atomic successful completion.
- Task 2 connected those primitives to durable service orchestration. The effective objective is the sole initial investigator input. START, MODIFY, and DECLINE can be prepared without model invocation; only an atomic claimant dispatches; success completes atomically; failure categories, interruption, and explicit linked retry are durable. The compatibility UI path remains synchronous until the Streamlit remediation task.
- Task 3 realigned the read model with durable operations. Context integrity retains precedence; latest attempts project Working or operation-specific Attention; Modify revision integrity is attempt-aware; simultaneous active operations fail projection; operation activity participates in ordering; and the landing list groups by safe package association while preserving unassociated legacy recovery entries.

**Approved remaining sequence:**

1. After Task 3 integration, remediate Streamlit presentation: persist model-bound actions before rerendering; render Working before dispatch; use a real one-shot browser acknowledgement rather than an immediate server rerun; atomically claim with a process-scoped runner identity; interrupt ambiguous prior-process work without replay; make Back presentation-only; reconstruct Resume from persistence; expose operation-specific recovery and explicit retry; and use a repository-root database default with an explicit absolute deployment override.
2. Add the required automated real Streamlit lifecycle/integration coverage and repeat manual acceptance.
3. Update status documentation after acceptance. Packaging discovery may be handled as separate non-blocking maintenance.

WAL mode is not part of the approved remediation unless a reproducible locking test demonstrates the need. The frozen synthetic fixture is not modified as part of V0.5 remediation.

## Next milestones

### V1 — Controlled execution

Controlled analytical execution remains deferred and has not started.

### V2 — Investigation state

Define investigation state after controlled execution boundaries are established.

### V3 — Iterative investigation

Define iterative investigation after the state model is established.

### V4 — Institutional memory

Define institutional memory after iterative investigation behavior is established.

## Explicitly deferred

- Cloud or external LLM integration.
- Autonomous action execution.
- Expanding the frozen synthetic fixture without a concrete framework-testing requirement.
- Persistence-format choices beyond the current V0 design needs.
- Detailed specifications for V1–V4 before their own product and architecture decisions are resolved.
