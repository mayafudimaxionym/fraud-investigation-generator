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

## Agent planning and action authority

The investigation agent maintains a provisional multi-step investigation plan.

The plan:

- Communicates the agent's current investigative direction.
- May contain multiple anticipated analytical steps.
- Is provisional and may change as evidence and findings develop.
- Does not itself authorize analytical execution.

At each investigation cycle, the agent proposes exactly one next analytical action for human review. Only that next analytical action may be approved, modified, or declined.

Approval authorizes only the proposed next action. It does not authorize later steps in the provisional investigation plan.

After an action result becomes available, or after human modification or decline, the agent may reassess its hypotheses and provisional plan before proposing the next action.

## Open decisions

The following product and architecture decisions remain unresolved:

- Proposal contract details, except for the provisional-plan and one-next-action approval scope defined above.
- Approval interaction details.
- Modification semantics.
- Persistence representation.
- Minimum context.
- UI behavior.
- Boundary between agent and source systems.

Acceptance criteria will be finalized after these decisions are resolved and approved.

## Out of scope

See `ROADMAP.md` for deferred work.
