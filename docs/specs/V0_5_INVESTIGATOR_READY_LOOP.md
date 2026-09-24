# V0.5 — Investigator-Ready Investigation Loop

**Status:** Product design approved; architecture approved; implementation in progress.

## Purpose and baseline

V0.5 makes the existing local human-agent investigation loop usable by a fraud investigator without implementation knowledge while improving analytical discipline. It extends, rather than rewrites, V0:

```text
Investigation → agent reasoning → one proposed next analytical action
→ human decision → persisted state
```

V0 contracts and history remain intact: `InvestigationRecord`, the five-field `AnalyticalActionProposal`, immutable `HumanDecision`, proposal statuses, Modify revision lineage, SQLite, the governed package loader, local Ollama, local Streamlit, evaluator isolation, and no execution of approved actions.

V0.5 does not execute analytical actions. Controlled analytical execution remains V1.

## Investigator experience

Normal operation begins at an **Investigations** page with **New investigation** and a recent-investigations list. Summaries show investigator-relevant case reference/name, domain where available, lifecycle state, relevant current/latest action, last activity, and **Resume**.

Normal operation must not require entering UUIDs, package/filesystem paths, SQLite paths, Ollama commands, environment variables, model IDs, or timeout values. Lifecycle presentation should be derived from authoritative persisted facts rather than an independently mutable duplicate status where possible.

Primary investigator-facing states are:

- **Ready**;
- **Agent working**;
- **Needs review**;
- **Approved**;
- **Attention**.

Examples include an active `PROPOSED` proposal as Needs review, a latest `APPROVED` proposal as Approved, a synchronous model request as Agent working, and a committed decline followed by failed replacement generation as Attention.

## Starting and resuming investigations

The investigator selects an available safe case/package through the UI. Case selection summarizes only permitted investigator-facing contextual material and dataset inventory.

An optional **Investigation Objective** is prefilled as editable text:

> Investigate the reported suspicious activity, identify relevant patterns and relationships, and assess the plausible explanations without assuming any explanation is established in advance.

The investigator may keep, edit, replace, or delete it. The effective objective, including an intentional blank, is persisted at investigation level.

For legacy investigations, `None` means that no effective objective was recorded, while `""` means the investigator intentionally chose a blank objective. An investigator may establish missing legacy objective metadata exactly once; this is metadata completion, not analytical history, and cannot edit or replace an already established objective.

The initial flow is:

```text
safe investigator context + effective objective
→ agent
→ InvestigationDirection v1 + Proposal 1
→ persist together
→ Needs review
```

After successful initial agent generation, `InvestigationDirection` v1 and Proposal 1 must be persisted atomically: both persist or neither persists. A persistence failure must not leave either record committed without the other. A generation failure creates neither. No partial direction/proposal pair may become authoritative persisted investigation state.

Resume uses the persisted safe package association and authoritative persisted state; it does not rely on transient Streamlit state or require the investigator to re-enter a package path. An approved investigation prominently shows **LAST ACTION APPROVED**, the approved five-field action, current direction, history, and investigator context. Needs review returns to the outstanding proposal; Attention returns to its recovery action.

## Governed context and analytical discipline

Initial agent context remains limited to:

- investigation request;
- customer/support statement;
- prior analyst note; and
- safe investigator-visible structured-dataset inventory, including available descriptive metadata such as name, description, row count, fields, and basic schema information.

Raw structured rows are not automatically placed in prompts. Nothing from `evaluator_only/` may enter investigator runtime, prompts, inventory, metadata, UI, or derived investigator-visible state.

Contextual claims and prior interpretations are evidence inputs or possible explanations, not established conclusions. Where warranted, the agent maintains plausible competing explanations and favors actions that discriminate among them. UI language must make this clear:

> Working explanations — none is currently established as a finding.

V0.5 does not introduce persistent Hypothesis, Finding, Evidence, confidence-score, or evidence-graph models.

## InvestigationDirection

`InvestigationDirection` is a lightweight, persisted, versioned snapshot for investigation continuity, Resume, and minimal provenance. It contains:

- a direction ID and investigation association;
- ordered textual competing explanations;
- ordered textual provisional plan steps;
- creation/version metadata; and
- minimal provenance/trigger, such as `INITIAL`, `MODIFY`, or `DECLINE_REDIRECT`, with a relevant proposal or decision trigger where appropriate.

Direction versions append rather than overwrite. Normal UI shows the current version while prior versions remain available for provenance. For V0.5, ordered textual lists stored as structured JSON text in SQLite are acceptable and preferred over relational hypothesis/plan entities.

Direction is not a formal hypothesis, finding, evidence record, confidence score, executable task, institutional-memory record, or general provenance graph. Formal knowledge modeling remains deferred.

`InvestigationDirection` and a proposed next action are distinct. Direction is a provisional multi-step plan and is never authorization. The agent proposes exactly one investigator-readable analytical action for review using the unchanged five fields: Action, Purpose, Why now, Data to be used, and Expected output.

## Human decisions

### Approve

Approve authorizes exactly the displayed action. The Approved state prominently displays **ACTION APPROVED**, the exact five fields, and:

> This analytical action is authorized. Analytical execution is not implemented in this version.

Approve is terminal for the V0.5 cycle and creates no analytical result.

### Modify

Modify keeps the basic action but changes it according to the investigator instruction. The original proposal becomes `MODIFIED`; its instruction persists; the agent receives safe current direction, original proposal, and instruction; and a new five-field `PROPOSED` revision retains explicit revision lineage. It returns to Needs review and requires a fresh decision.

Modify may append a new `InvestigationDirection` version only when direction materially changes; otherwise the current direction remains authoritative. Modify never implies approval.

### Decline and redirect

Decline permanently makes the original proposal `DECLINED`; it must not later become `MODIFIED`. Guidance may explain why it should not proceed or what should be investigated instead. With guidance, the primary UI action is **Adjust investigation plan**, with clear text that the proposal will be declined and the agent will return a new proposal for approval. Without guidance, **Decline without guidance** is appropriate. Do not add a redundant generic second decline confirmation after actionable guidance.

The V0.5 decline boundary intentionally differs from V0:

```text
Proposal A → DECLINED + persisted human instruction
→ agent reconsideration/direction update
→ independent Proposal B → Needs review
```

The decline is authoritative before replacement generation. If generation fails, Proposal A and the human instruction remain persisted, no Proposal B exists, and no action is authorized. Modify uses proposal revision lineage; the replacement after Decline is never a revision child of the declined proposal. A successful reconsideration persists a dedicated decline-decision-to-independent-replacement association solely for restart-safe provenance and retry idempotency. It is not a general provenance graph, lifecycle state, authorization, or execution state. The same authoritative-decline rule applies with or without guidance.

## Local model operation and recovery

Model configuration is application/deployment-level operational configuration, not normal investigator workflow. It includes explicit Ollama base URL, model, generous hard processing limit, investigation database location, and case/package location as needed. Before agent reasoning, validate that local Ollama is reachable and the explicitly configured model is available. Do not silently substitute a model.

Investigator-visible failures distinguish at least service unavailable, model unavailable, request timeout, and generation error. While legitimate synchronous local inference runs, show **Agent working** with an accurate description such as *Preparing investigation approach* or *Adjusting investigation plan*, and state that no action is yet authorized. Do not invent percentages, fake stages, or completion estimates.

Slow inference is not itself an error. Use a sufficiently generous configurable hard bound only for stuck requests. There is no invisible/background retry. After a failure, the prior request has terminated and persisted state is authoritative. A visible **Try again** action, when appropriate, begins a new explicit request using persisted authoritative context/instruction. Attention presents the actual failure category and an available recovery action.

Do not introduce background-job infrastructure, task queues, or a generic workflow engine. V0.5 model operation remains synchronous: user initiates work → Agent working → local model success or controlled failure.

## Persistence and history

V0.5 adds persisted `investigation_directions`, a narrow successful decline-reconsideration decision-to-replacement association, and minimally extends investigation metadata with effective objective and safe package association. Exact SQL schema, migrations, Python API names, and Streamlit component structure remain implementation decisions.

History is investigator-readable and tells the investigation story rather than foregrounding database IDs. Internal IDs and lineage remain available for provenance.

## Scope boundaries

V0.5 must not add:

- analytical action, SQL, Python, or raw-data query execution;
- analytical results or persisted findings;
- formal persistent hypotheses, evidence graphs, institutional memory, or cross-investigation knowledge;
- multi-agent or autonomous workflows;
- automatic approval;
- evaluator data in investigator runtime;
- generic background-job/workflow infrastructure;
- model auto-selection; or
- full LLM conversation persistence as investigation state.

## Acceptance boundary

V0.5 is complete only when all of these are demonstrated:

1. Investigations can be started and resumed without UUIDs or package paths.
2. Safe package loading preserves evaluator/private isolation and governed initial context.
3. The investigator can keep, edit, replace, or remove the suggested objective.
4. Initial and revised output presents working competing explanations and exactly one five-field proposal.
5. Approve persists and presents the exact approved action without execution.
6. Modify persists its instruction, produces a revision-lineage proposal, and requires fresh review.
7. Decline commits permanently; guidance can redirect direction and create an independent fresh proposal.
8. Resume reconstructs lifecycle state, current direction, outstanding/approved action, and history.
9. Ollama preflight reports unavailable service/model as Attention without substitution.
10. Legitimately slow inference remains visibly Agent working.
11. Failed/timed-out generation leaves no partial proposal/authorization and preserves already committed decisions/instructions.
12. Retry is explicit and starts a new request only after the prior request terminates.
13. Normal investigator operation requires no operational configuration knowledge.
14. No analytical action is executed anywhere in V0.5.
