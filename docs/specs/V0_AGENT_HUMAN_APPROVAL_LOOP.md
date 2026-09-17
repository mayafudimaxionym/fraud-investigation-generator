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

## Next analytical action proposal

At each investigation cycle, the agent presents exactly one next analytical action for human review.

Before the human can approve, modify, or decline the action, the proposal must contain these five mandatory fields:

1. **Action** — a concise description of the analytical action the agent wants performed.
2. **Purpose** — the investigation question or hypothesis the action is intended to examine.
3. **Why now** — why the agent considers this the appropriate next step given the current investigation context, evidence, findings, hypotheses, and provisional plan.
4. **Data to be used** — the specific investigator-visible data sources or artifacts the proposed action requires. The proposal must not reference evaluator-only data or other inaccessible sources.
5. **Expected output** — a description of the analytical result or artifact the action is expected to produce.

The proposal contract describes analytical intent and requested data access. V0 does not require the proposal to expose implementation or execution details such as generated Python, pandas operations, SQL, executor commands, or low-level execution parameters. Those belong to the controlled analytical execution layer introduced after V0.

## Human modification

If the human selects **Modify**, the requested modification applies to the proposed next action. The agent must incorporate the human instruction and produce a revised proposal for review.

The modification does not itself authorize execution. The revised proposal must again contain the five mandatory proposal fields and remains subject to Approve, Modify, or Decline.

## Human decision semantics

### Approve

Approve authorizes the exact proposed next analytical action.

In V0:

- The proposal becomes `APPROVED`.
- The approval is persisted.
- No analytical execution occurs.
- The system must make clear that the action is approved but not executed in V0.

These semantics carry forward into V1, where an approved action may be passed to the controlled analytical executor.

Approval applies only to that specific proposed action and does not authorize later actions in the provisional investigation plan.

### Decline

Decline means that the proposed analytical action is not authorized.

- The proposal becomes `DECLINED`.
- The decision is persisted.
- The human may optionally provide a decline reason or instruction.
- The decline reason becomes part of the investigation history.
- The agent may use that feedback to reconsider its provisional plan and propose a different next action.

A declined action must not be executed.

Declining an action does not authorize a similar or replacement action. Any replacement action must be presented as a new proposal and reviewed separately.

### Modify

- Modify applies to the current proposed action.
- The human provides an instruction describing the requested change.
- The agent produces a revised proposal containing the five mandatory proposal fields.
- Modification itself does not authorize execution.
- The revised proposal requires a new Approve, Modify, or Decline decision.

### Decision history

Human decisions are immutable historical events. The system must preserve what decision was made on a proposal rather than silently rewriting that historical decision later.

If the investigator subsequently changes direction, that change must be represented by a subsequent proposal or decision event rather than altering the earlier historical record.

## V0 persistence content

V0 must persist enough structured state to reconstruct the complete proposal and decision trail after the application is closed and reopened.

### Investigation record

Persist a minimal investigation record containing:

- Stable investigation ID.
- Reference to the investigator-visible case or fixture being investigated.
- Creation timestamp.
- Last-updated timestamp.

This record provides identity and context for the proposal and decision history. V0 does not require the full investigation-state model planned for later milestones.

### Proposals

Persist every analytical-action proposal. Each proposal must retain:

- Stable proposal ID.
- All five mandatory proposal fields: Action, Purpose, Why now, Data to be used, and Expected output.
- Proposal status.
- Creation timestamp.
- Lineage to the prior proposal when the proposal is a revision produced through Modify.

Historical proposals must not be overwritten by revised proposals.

### Human decisions

Persist every human review decision. Each decision must retain:

- Stable decision ID.
- Proposal ID to which the decision applies.
- Decision type: Approve, Modify, or Decline.
- Timestamp.
- Human-provided instruction or reason when applicable.

For Modify, the human modification instruction is retained, the resulting revised proposal is stored as a new proposal, and lineage between the original and revised proposal is preserved.

For Decline, the optional decline reason or instruction is retained when supplied.

### Persistence behavior

After closing and reopening an investigation, the system must be able to reconstruct the ordered proposal and decision history without relying on chat history or LLM memory.

Previously persisted proposals and decisions are immutable historical records. Later actions append new records rather than rewriting earlier history.

### Explicitly not required in V0 persistence

V0 does not yet require persistence of:

- Hypotheses.
- Findings.
- Analytical results.
- Institutional knowledge entries.
- General agent memory.
- Full chat transcripts.
- Generated analytical code.

These belong to later milestones unless a concrete V0 requirement demonstrates otherwise.

This decision defines what must be persisted, not how it is physically stored. Persistence representation and technology remain open design decisions.

## Design decisions still open

The following product and architecture decisions remain unresolved:

- UI-presentation details for the approval interaction.
- Persistence representation or technology.
- Minimum context.
- UI behavior.
- Boundary between agent and source systems.

Acceptance criteria will be finalized after these decisions are resolved and approved.

## Out of scope

See `ROADMAP.md` for deferred work.
