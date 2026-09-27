# ADR 006: Human Semantic Review Boundary for V0.5

**Status:** Accepted.

## Decision

V0.5 retains unrestricted investigator-authored objective, Modify instruction, and Decline guidance text and uses one local-model generation call per durable `AgentOperation`. Python enforces only objectively machine-checkable response and persistence invariants. It does not use keyword overlap, edit distance, text-similarity thresholds, embeddings, fixed stage labels, or other lexical proxies to certify natural-language meaning.

Python validates at least:

- the exact approved JSON response shape;
- exactly one proposal with the five required non-blank textual fields;
- at least two non-blank competing-explanation entries;
- at least two non-blank ordered provisional-plan steps;
- absence of exactly duplicated explanations or plan steps after trivial whitespace/case normalization;
- absence of model-assigned canonical IDs, status, timestamps, authorization, or execution state;
- explicit known evaluator-only/private-source references;
- operation, decision, proposal-lineage, atomic-completion, and no-partial-result invariants; and
- the continued absence of analytical execution in V0.5.

Semantic properties remain model-quality expectations reviewed by a human. These include whether explanations are genuinely distinct and plausible, the plan is a meaningful and sufficient investigation direction, the proposed action is narrower than the direction, a Modify result materially follows the instruction, a Decline replacement materially addresses redirection guidance, and the response is grounded and non-contradictory.

The Needs Review presentation must show the effective objective and, when applicable, the persisted Modify instruction or Decline guidance together with the generated direction and proposal. Previous and newly generated direction content must be available when needed to judge a requested redirection. The UI must not claim that the model followed an instruction; it must tell the investigator to verify responsiveness and scope before approval. Direction remains provisional and never authorizes analysis.

Direction versioning uses a deterministic content boundary rather than a semantic claim: retain the current version when returned direction content is unchanged after trivial normalization, and append a new version when the returned content differs. A new version records changed text; it does not certify that the change is material or adequate.

One durable operation permits one generation call. Availability/model preflight is not a generation call. V0.5 does not add a second semantic-adjudication call, an automatic repair call, or a hidden retry. A structurally invalid response fails safely as `GENERATION_ERROR`; explicit Try again creates a new operation identity from persisted authoritative request state.

A structurally valid but substantively weak response becomes authoritative generated state and is presented as Needs Review. It is not automatically rejected or regenerated. The investigator may Approve, Modify, or Decline it; no action is authorized without explicit approval. A weak direction is redirected through the existing Decline/Adjust investigation plan flow.

`llama3:8b` is not a required qualified V0.5 deployment baseline. It may remain configurable, but V0.5 acceptance must record and use a local model, version, settings, and prompt configuration that pass the approved manual semantic scenarios. A configuration that repeatedly produces inadequate directions or unresponsive Modify/Decline results cannot pass V0.5 acceptance. Model qualification improves expected quality but is not deterministic semantic proof.

## Reason

Arbitrary natural-language responsiveness, contradiction, negation, incidental keyword reuse, semantic equivalence, and action narrowness cannot be established reliably through deterministic lexical rules. Such rules both accept contradictory responses and reject valid changes. Treating those heuristics as semantic proof creates false assurance and prevents normal investigator workflows from succeeding.

Human review is already the V0.5 authorization boundary. Showing the authoritative investigator input and generated output together lets the domain expert make the semantic judgment without expanding V0.5 into structured investigator controls, a second-model evaluator, or a multi-call workflow.

## Consequences

Automated tests cover the deterministic contract and all durable-operation safety guarantees. Manual acceptance covers semantic adequacy using representative INITIAL, MODIFY, and DECLINE/redirect scenarios. Structurally valid weak prose may reach review, but remains provisional and unauthorized.

The prompt should describe a useful plan through a semantic rubric rather than a fixed taxonomy. Where relevant, a useful direction decomposes the objective into investigable questions, identifies governed evidence, considers behavioral and relational patterns, maintains competing explanations, includes corroboration/contradiction and limitation checks, follows a sensible sequence, and leads toward synthesis. These are model-quality and human-review criteria; they are not prescribed stage names or one-to-one required fields.

If a future milestone requires automatic semantic rejection before human review, it must separately approve a structured semantic contract or a semantic-adjudication model boundary, including persistence, provenance, failure, retry, latency, and model-configuration consequences.

This decision preserves human authority, persistent structured state, evaluator isolation, local-only processing, model independence, atomic operation completion, and the prohibition on V0.5 analytical execution.
