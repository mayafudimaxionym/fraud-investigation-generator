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

- Task 1 delivered and merged the narrow `AgentOperation` domain lifecycle and SQLite persistence primitives for pending preparation, atomic claim, failure/interruption, retry lineage, and atomic successful completion. These primitives are not yet connected to the V0.5 service, read model, or Streamlit controller.

**Approved remaining sequence:**

1. Resolve whether the persisted effective objective is the sole initial investigator input or a separate initial instruction is also persisted. Every value that influences a model request must be authoritative persisted state before `PENDING_RENDER`.
2. Implement durable service orchestration: prepare without model invocation, claim once, preflight/generate only for the claimant, atomically complete successful results, persist safe failure categories, interrupt ambiguous previous-process work, and create explicit linked retry operations.
3. Realign the read model: project pending/running operations as Agent working, failed/interrupted operations as Attention, allow authoritative Modify-without-revision intermediate/failure states, include operation activity, and group the landing page by safe package association while retaining unassociated legacy recovery entries.
4. Remediate Streamlit presentation: render Working before dispatch, use one-shot acknowledgement, make Back presentation-only, reconstruct Resume from persistence, and use deterministic deployment-level database configuration.
5. Add the required automated real Streamlit lifecycle/integration coverage and repeat manual acceptance.
6. Update status documentation after acceptance. Packaging discovery and narrow local-artifact ignores may be handled as separate non-blocking maintenance.

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
