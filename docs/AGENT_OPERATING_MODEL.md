# Agent Operating Model

**Status:** Approved where marked. This document is the repository's system of record for how the agent organization operates. It was split out of the V0.5 acceptance specification under approved decision PO-5 so that organizational truth is durable in the repository rather than only in the coordination tool.

**Scope:** role ownership, human authority, provider capacity handling, dispatch policy, and task sizing.

**Not in scope:** product behavior, V0.5 acceptance requirements, and validation architecture. Those live in `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` and `docs/specs/V0_5_INVESTIGATOR_READY_LOOP.md`. Where this document and a product specification appear to disagree about product behavior, the product specification wins.

---

## 1. Governing principle

**Capacity may influence *when* work is dispatched. It must never change *who owns* the work.**

This principle applies identically to every provider. A role's authority, its acceptance criteria, and its architectural decision rights are fixed by this document and by the product specifications. They are not a function of which provider has quota available at a given moment.

Concretely, capacity must never change:

- task ownership;
- architectural authority;
- acceptance criteria;
- what a role is permitted to decide.

---

## 2. Roles and ownership

| Role | Provider | Owns | Status |
|---|---|---|---|
| Product & Architecture Planner | Claude | Product behavior, architecture, specifications, acceptance requirements, ADRs | Exists |
| Implementation Engineer | Claude | Product implementation of approved decisions | Exists |
| Independent Reviewer | Claude | Independent review of implementation work | Exists |
| QA & Workflow Validation Engineer | Claude | *Running* validation; PASS/FAIL/BLOCKED verdicts with evidence | Exists |
| AI Model Qualification Researcher | Claude | Controlled experiments, structural evidence, analysis, recommendations | Exists |
| QA Automation Developer | Codex | Building bounded QA automation and validation/test infrastructure | **Exists and is in active use** |

**Maya (Product Owner)** is the human authority and is not a role in the table above. Maya retains final authority over material product behavior changes, architecture changes, milestone scope, human/agent governance, destructive or irreversible repository actions, major new dependencies affecting architecture, and final milestone acceptance. Approval is never inferred from silence.

**Current-state note (verified against the agent roster, 2026-09-30).** The Status column records whether an agent is actually provisioned, not whether the role is desirable. Six agents exist: Product & Architecture Planner, Implementation Engineer, Independent Reviewer, QA & Workflow Validation Engineer, AI Model Qualification Researcher, and QA Automation Developer.

**The Independent Reviewer is provisioned.** Maya authorized the role on 2026-09-30 and approved the escalation path in 2.2 below; the agent was created the same day and is on the roster. Independent review work routes to it. It must never be silently absorbed by the QA & Workflow Validation Engineer, whose authority is to *run* validation and report PASS/FAIL/BLOCKED verdicts, not to review implementation on quality terms. Provisioning any further agent remains a human/agent governance change requiring Maya's explicit authorization.

This column must be corrected whenever the roster changes. A role recorded as existing when it does not produces authorized handoffs with no owner, which is the failure this note exists to prevent.

### 2.1 QA Automation Developer — boundary (PO-7, approved with current-state correction)

The QA Automation Developer **already exists** and is currently being used successfully for bounded technical investigation and validation. It is not a planned or pending role, and must not be described as awaiting creation.

Its implementation boundary is deliberately narrow:

- **May** build bounded validation and test infrastructure — for example Playwright and pytest automation — in the approved validation/test area.
- **Does not** define expected product behavior.
- **Does not** issue product acceptance verdicts.
- **Does not** modify product code merely because Codex capacity is available.
- Its implementation output is reviewed on the same quality terms as any other implementation work. Provider diversification does not diversify the quality bar.

**Provider availability never changes role ownership.** The role that *builds* validation automation stays distinct from the role that *runs* it and reports verdicts.

---

### 2.2 Independent Reviewer — finding disposition and the narrow independence-escalation path (approved 2026-09-30)

The Independent Reviewer's deliverable is a review report: findings anchored to a file and line, each citing the committed clause it concerns, each with a concrete failure scenario, a severity, and a disposition route. **A review finding does not change approved design.** It is evidence and a recommendation, never an authorization to alter a specification, an ADR, an invariant, or an acceptance criterion. The Reviewer does not implement, does not fix what it finds, does not define expected product behavior, does not issue product acceptance verdicts, and does not create follow-up issues.

**Normal disposition routes through the Product & Architecture Planner.** Ordinary implementation defects and missing implementation tests route to the Implementation Engineer; genuine product or architecture ambiguity routes to the Planner; material changes reach Maya through the Planner. This is the default and covers nearly every case, and it is what keeps a finding from silently becoming an approved change.

**The Independent Reviewer may escalate directly to Maya only when one of the following holds:**

1. a **material** finding concerns the Planner's own specification or architecture decision and cannot be resolved through normal disposition;
2. the Planner **declines, suppresses, or fails to preserve** a material review finding; or
3. a **governance or independence conflict** makes routing solely through the Planner inappropriate.

The path exists because routing every finding through the author of the specification would make a finding *about* that specification unreviewable. It is narrow by design.

**Direct escalation reports the evidence and the unresolved disagreement only.** It does not authorize the Reviewer to change product behavior, specifications, ADRs, architecture, acceptance criteria, or milestone status, and it does not make the finding an approved decision. Maya decides. Escalation must be explicit — the Reviewer must state that it is escalating and which of the three conditions applies. Non-material findings and ordinary implementation defects never take this path.

---

## 3. Capacity-aware dispatch

Readiness is necessary but not sufficient. A task being ready is the first condition for dispatch; sufficient provider capacity to finish it and persist durable state is the second.

**No numeric thresholds are set in this document.** There is not yet evidence to calibrate percentages, and an arbitrary number would harden into a rule nobody could justify. Calibration is separate future work requiring observed task-cost data.

### 3.1 Capacity states — required for every provider

Every capacity mechanism must distinguish four states and must never collapse them:

1. **Authentication / configuration health** — is the credential and configuration usable at all?
2. **Short-term capacity** — the near-term rolling window.
3. **Longer-term capacity** — the longer rolling window.
4. **UNKNOWN / BLOCKED** — capacity could not be determined.

**UNKNOWN / BLOCKED must be an explicit state, never silently rendered as "available" or "0% used."** A mechanism that reports zero usage on a parse or transport failure would dispatch the largest work at exactly the moment it has the least information.

### 3.2 Claude

Retain the existing **non-inference `get_usage` design**. Claude Code exposes current subscription usage without consuming an inference call, via the stream-JSON `get_usage` control request — session (five-hour) utilization and reset time, and weekly utilization and reset time.

Constraints on any implementation:

- use the non-inference `get_usage` mechanism;
- `skip_behaviors: true`;
- isolate the subscription-profile lookup from the coordination tool's API-key environment;
- tolerate unknown response fields;
- treat any parsing or interface failure as **UNKNOWN**, never 0%;
- assume the interface is experimental and may change without notice.

### 3.3 Codex

A read-only, non-inference capacity mechanism has been identified in **codex-cli 0.156.1**:

- JSON-RPC method: **`account/rateLimits/read`**
- transport: **`codex app-server --stdio`**
- can expose `ordinaryUsageAllowed`, `accountId`, primary and secondary `usedPercent`, reset times, `planType`, credit state, and spend-control / reached-state signals;
- it does **not** create a prompt, thread, turn, or any other inference operation.

Constraints:

- `app-server` is **experimental and version-sensitive**; the mechanism must be treated as liable to change;
- authentication failure, network failure, JSON-RPC failure, or `ordinaryUsageAllowed = null` must result in **UNKNOWN / BLOCKED** — never an assumed available or 0%-usage state.

### 3.4 Deferral policy (PO-6, approved)

- **Capacity deferral must always be visible on the affected issue.** Silent deferral is not permitted.
- The **reason** must be recorded, and the **expected reset time** when it is known.
- **An explicit instruction from Maya overrides a capacity-deferral heuristic.** When overridden, the agent discloses the capacity risk and proceeds; it does not refuse human-directed work.
- Deferral is a scheduling decision only. It never changes what the work is, who owns it, what authority applies, or what the acceptance criteria are.

---

## 4. Task sizing

Tasks are sized for completion within one execution window. The Planner decomposes oversized work **before** assignment rather than relying on the executing agent to survive it.

Every assigned task carries one bounded objective, the minimal necessary context, explicit completion criteria, a durable output, and an early-stop condition where appropriate.

**Recovery is not a plan.** Normal operation must not depend on Resume or Recovery to finish planned work. A task that routinely needs it was mis-sized; the fix is decomposition at assignment time, not longer runtime.

### 4.1 Investigation discipline (adopted operating rule)

When an assigned task is investigative:

- start from the **most direct current-state, runtime, or source evidence**;
- work to an **explicit investigation budget and evidence order**;
- use **at most one narrowly targeted reproduction** when direct evidence is insufficient;
- **stop once sufficient evidence establishes the objective** — remaining runtime is not a reason to widen the investigation;
- do **not** broaden into unrelated infrastructure or schema exploration, or into workaround development, unless the direct path proves insufficient;
- **report the uncertainty and the additional evidence required** rather than expanding indefinitely.

---

## 5. Multi-provider execution

Independent work may run on Claude-backed and Codex-backed agents in parallel or in sequence where dependencies permit. QA automation construction is genuinely independent of product fixes, so those workstreams may overlap.

Work moves to another provider-backed role **only when that role legitimately owns it** — never because a provider has spare capacity. Restating §1: authority is unchanged by provider.

---

## 6. Explicitly outside this document

Implementing a capacity monitor · defining numeric capacity thresholds · redesigning the organization · creating additional roles · recurring autonomous routines or scheduled heartbeats · any product behavior or acceptance criteria.

Each of the above requires Maya's explicit authorization as a separate decision.
