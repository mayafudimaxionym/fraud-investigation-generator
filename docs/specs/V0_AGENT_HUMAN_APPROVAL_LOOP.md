# V0 — Agent / Human Approval Loop

**Status:** APPROVED FOR IMPLEMENTATION

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
- The original proposal becomes `MODIFIED` and is no longer pending.
- The agent produces a revised proposal containing the five mandatory proposal fields.
- The revised proposal is a new `PROPOSED` proposal with lineage to the original proposal.
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

V0 proposal statuses are:

- `PROPOSED` — awaiting a human decision.
- `APPROVED` — the exact proposal was approved.
- `DECLINED` — the exact proposal was declined.
- `MODIFIED` — the human requested modification of the proposal; the original proposal is no longer pending and a new proposal must be created for the revised action.

Historical proposals must not be overwritten by revised proposals.

### Human decisions

Persist every human review decision. Each decision must retain:

- Stable decision ID.
- Proposal ID to which the decision applies.
- Decision type: Approve, Modify, or Decline.
- Timestamp.
- Human-provided instruction or reason when applicable.

For Modify, the immutable human modification instruction is retained separately, the original proposal's status becomes `MODIFIED`, the resulting revised proposal is stored as a new `PROPOSED` proposal, and lineage between the original and revised proposal is preserved.

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

This decision defines what must be persisted; the V0 persistence representation is defined below.

## V0 persistence representation

V0 uses SQLite for local persistence.

### Requirements

- SQLite runs locally within the application environment.
- No external database server or cloud persistence service is required.
- The database remains inside the local and on-premise boundary.
- Python's standard SQLite support is sufficient; do not introduce a database dependency unless implementation later demonstrates a concrete need.

### V0 storage scope

The SQLite persistence model stores only the V0 records already approved in this specification:

- Investigations.
- Proposals.
- Human decisions.

Do not introduce persistence structures for future milestones, including hypotheses, findings, analytical results, institutional knowledge, general agent memory, chat transcripts, or generated analytical code.

### Persistence boundary

Application and agent logic should interact with persistence through a small persistence abstraction or layer rather than issuing arbitrary SQLite operations throughout the application.

SQLite is the V0 persistence implementation behind that boundary. This preserves the ability to change persistence implementation later without making SQLite itself part of the investigation-agent contract.

### History

The SQLite representation must preserve the already-approved immutable historical semantics:

- Proposals are retained rather than overwritten.
- Decisions are retained rather than overwritten.
- Revised proposals are new records.
- Proposal revision lineage is preserved.
- An investigation can be reconstructed after application restart without chat history or LLM memory.

This decision selects the V0 persistence implementation only. It does not design the future V1 or V2 persistence model.

## Initial agent context

When an investigation starts, the agent receives enough investigator-visible context to understand the investigation and decide what analytical action to propose next.

### Context provided automatically

The agent receives the contents of the investigator-facing contextual artifacts:

- Investigation request.
- Customer or support statement.
- Prior analyst note.

The agent also receives a safe inventory of the investigator-visible structured datasets. For each available structured dataset, this inventory may include descriptive metadata needed to understand what data is available, such as:

- Dataset or file name.
- Dataset description when available.
- Row count.
- Field or column names.
- Basic schema or type information when available.

This inventory describes available data. It is not analytical access to the dataset contents.

### Raw structured data

The agent must not automatically receive the raw row contents of investigator-visible structured datasets as LLM context. This includes raw visible entities, visible relationships, and visible events.

Knowing that a dataset exists is distinct from accessing or analyzing its underlying records.

When the agent determines that structured data should be analyzed, it proposes a next analytical action using the already-approved five-field proposal contract, including the specific data sources requested.

In V0, that proposal can be reviewed and approved, modified, or declined, but no analytical execution occurs. In the later controlled-execution milestone, approved analytical access will be performed through the controlled analytical executor rather than by giving the agent unrestricted direct access to the raw dataset.

## Evaluator isolation

Evaluator-only material is completely outside the investigator runtime boundary.

The investigation agent must not receive:

- Evaluator-only file contents.
- Evaluator-only filenames or inventory.
- Evaluator-only schemas or metadata.
- Ground-truth information derived from evaluator-only sources.

The investigator-facing loading and context mechanism must operate only on investigator-visible material.

Evaluator isolation must not rely solely on prompt instructions telling the LLM to ignore evaluator data.

## Architectural distinction

Local and on-premise operation and governed agent data access are separate requirements. Running the LLM locally does not grant the agent unrestricted access to locally stored raw data.

The intended boundary is:

```text
Agent
  → understands available investigator-visible context/data inventory
  → proposes analytical action
  → human review
  → controlled executor in a later milestone
  → raw structured data
  → bounded analytical result
  → agent
```

## V0 user interface

V0 uses a minimal local Streamlit interface. Its purpose is to exercise the approved agent and human approval loop; it is not the final production interface.

V0 uses a single investigation screen rather than multiple application sections or dashboards.

### Main screen

The screen contains three functional areas:

1. Investigation context.
2. Investigation agent interaction.
3. Decision history.

### Investigation context

Display the active investigation or case identity and make the investigation request readily visible.

The other investigator-facing contextual artifacts—the customer or support statement and prior analyst note—must be available for inspection without their full contents continuously occupying the main screen. Expandable UI elements are appropriate.

Display the approved safe inventory of investigator-visible structured datasets, including available metadata such as dataset name, row count, and fields or schema where available.

Do not expose evaluator-only information. Do not make browsing raw structured dataset rows part of the V0 agent workflow.

### Investigator instruction

Provide a text input through which the human investigator can give the investigation agent an instruction.

After receiving the instruction, the agent presents its provisional investigation plan and exactly one proposed next analytical action. The provisional plan is informational and does not grant execution authority.

### Proposed next analytical action

Display the already-approved five mandatory proposal fields clearly:

- Action.
- Purpose.
- Why now.
- Data to be used.
- Expected output.

Provide three human decision controls: Approve, Modify, and Decline.

### Approve interaction

Approve persists the already-defined `APPROVED` decision.

Because V0 does not execute analytical actions, the UI must clearly indicate:

`Approved — analytical execution is not implemented in V0.`

Do not generate or simulate an analytical result.

### Modify interaction

Selecting Modify allows the investigator to provide an instruction describing how the proposed action should change. The agent then produces a new proposal containing all five mandatory fields.

The revised proposal requires a new Approve, Modify, or Decline decision. The original proposal and modification decision remain in immutable history.

### Decline interaction

Selecting Decline allows the investigator to provide an optional reason or instruction. The decline can be submitted without a reason. The `DECLINED` decision is persisted.

The agent may then reconsider its provisional investigation plan and propose a new next action. Any replacement action is a new proposal and requires separate human review.

### Decision history

The screen displays the persisted proposal and decision trail sufficiently to show what occurred during the V0 interaction. The history should make proposal revisions and their decisions understandable, including Modify lineage.

Do not build a sophisticated audit or history interface in V0.

### Explicit V0 UI exclusions

Do not add:

- Dashboards.
- Graph visualization.
- Knowledge-base views.
- Multiple-agent interfaces.
- Analytical-result views.
- Raw CSV browsing as part of the agent workflow.
- Notebook or code-execution interfaces.
- Production navigation architecture.
- Enterprise authentication.
- Final-product visual design.

Keep the UI deliberately minimal.

## V0 source-system boundary

For V0, the frozen investigator package is the investigation source.

Do not design or implement integrations for email, external PDF ingestion, Excel, databases, VS Code, Google Colab, or external enterprise systems. Those are future integration concerns and do not block V0.

The previously approved investigator-visible structured-data boundary remains authoritative.

## Design decisions still open

No further V0 product or architecture design decisions remain open.

Future-milestone questions are not V0 blockers. Implementation may make ordinary engineering choices within the approved architecture and this specification. Any implementation discovery that requires changing approved product behavior or an architectural invariant must be escalated rather than silently resolved.

## Acceptance criteria

V0 is complete when all of the following are demonstrated:

### 1. Local startup

The V0 application can be started locally and opened in a browser without requiring a cloud service.

### 2. Safe case loading

The application loads the frozen investigator package.

The agent receives:

- The three approved investigator-facing contextual artifacts.
- The approved safe inventory of investigator-visible structured datasets.

The agent does not receive:

- Raw structured dataset rows automatically.
- Evaluator-only contents.
- Evaluator-only filenames or inventory.
- Evaluator-only schemas or metadata.
- Evaluator-derived ground truth.

### 3. Investigator instruction → agent proposal

The human investigator can provide a natural-language investigation instruction to the local agent.

The agent returns:

- A provisional investigation plan.
- Exactly one proposed next analytical action.

The proposed action contains all five mandatory fields:

- Action.
- Purpose.
- Why now.
- Data to be used.
- Expected output.

### 4. Approve works

The investigator can approve the proposed action.

The system:

- Persists the exact proposal.
- Persists the approval.
- Clearly shows that the action is approved but not executed in V0.

No analytical execution or simulated analytical result occurs.

### 5. Modify works end-to-end

The investigator can provide a natural-language modification instruction.

The system preserves:

- The original proposal.
- The Modify decision.
- The human modification instruction.

The agent produces a new five-field proposal.

The revised proposal:

- Is stored as a new proposal.
- Preserves lineage to the original proposal.
- Requires a new Approve, Modify, or Decline decision.

### 6. Decline works end-to-end

The investigator can decline a proposal with or without an optional reason or instruction.

The system persists:

- The declined proposal.
- The Decline decision.
- The optional human reason or instruction when supplied.

The agent may reconsider its provisional plan and produce a new proposal.

Neither the declined action nor any replacement action is implicitly authorized.

### 7. Persistence survives restart

After the application is closed and reopened, the investigation and complete proposal and decision trail can be reconstructed from local SQLite persistence.

This includes:

- Proposals.
- Decisions.
- Proposal revision lineage.
- Modification instructions.
- Decline reasons or instructions when supplied.

Reconstruction must not depend on:

- Chat history.
- LLM memory.

### 8. Architecture boundaries are demonstrated

V0 demonstrates that:

- The LLM operates locally.
- The Streamlit application operates locally.
- SQLite persistence operates locally.
- No cloud LLM or cloud data dependency is required.
- Raw structured datasets are not automatically exposed to the agent.
- Evaluator-only information is outside the investigator runtime boundary.
- Proposed analytical actions are not executed in V0.
- The frozen synthetic investigation fixture is not expanded or redesigned.

## Out of scope

See `ROADMAP.md` for deferred work.
