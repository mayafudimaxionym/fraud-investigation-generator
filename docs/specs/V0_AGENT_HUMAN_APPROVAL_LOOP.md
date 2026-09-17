# V0 — Agent / Human Approval Loop

**Status:** DESIGN IN PROGRESS

## Goal

Build the local interaction loop:

`Investigator package → local investigation agent → structured analytical proposal → human approve / modify / decline → persisted decision`

V0 does not execute proposed analytical actions.

## Architectural compliance

V0 must comply with the invariants in `docs/ARCHITECTURE.md`.

## Approved requirements

- Run locally and on-premises.
- Use the frozen investigator package as evidence input.
- Keep evaluator-only material inaccessible to the agent.
- Use local inference only.
- Require human review before any proposed action could execute.
- Persist the human decision outside the chat.
- Do not execute actions in V0.

## Open decisions

The following product and architecture decisions remain unresolved:

- Proposal contract.
- Approval interaction.
- Modification semantics.
- Persistence representation.
- Minimum context.
- UI behavior.
- Boundary between agent and source systems.

Acceptance criteria will be finalized after these decisions are resolved and approved.

## Out of scope

See `ROADMAP.md` for deferred work.
