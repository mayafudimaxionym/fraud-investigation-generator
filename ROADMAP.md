# Project Roadmap

## Product goal

Build an on-premises agent-driven fraud investigation framework with human controls over AI analytical work and persistent institutional memory.

## Completed

- **Synthetic investigation fixture — COMPLETE / FROZEN.** The deterministic investigation package is accepted test infrastructure and must not be expanded unless framework testing exposes a concrete requirement.
- **Architecture baseline — COMPLETE.** `docs/ARCHITECTURE.md` defines the approved architectural invariants.

## Current milestone

### V0 — Agent / Human Approval Loop

**Goal:**

`Investigator package → local investigation agent → structured analytical proposal → human approve / modify / decline → persisted decision`

V0 does not execute proposed analysis.

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

## Next milestones

### V1 — Controlled execution

Define controlled execution only after V0 is complete and evaluated.

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
- Detailed specifications for V1–V4 before V0 decisions are resolved.
