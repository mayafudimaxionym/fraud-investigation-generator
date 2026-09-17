# AI Development Instructions

## Required reading

Before proposing or implementing framework changes, read:

1. `PROJECT_STATUS.md`
2. `ROADMAP.md`
3. `docs/ARCHITECTURE.md`
4. Current milestone specifications in `docs/specs/`
5. Relevant documents in `docs/decisions/`

## Authority

`docs/ARCHITECTURE.md` defines the architecture. The current milestone specification defines what is in scope now. `ROADMAP.md` defines sequencing; future roadmap items are not permission to implement work early.

## Scope discipline

Implement only the approved task. Do not expand scope, implement future work early, introduce speculative capabilities, modify frozen synthetic infrastructure without approval, place external or cloud services in the core path, leak evaluator-only truth, or silently change an architectural invariant. Prefer the smallest change that satisfies the approved requirement.

## Decision boundary

Proceed without escalation only when a change does not alter product behavior or architecture. For a product or architectural decision, stop and report the decision, why it is needed now, options, implementation consequences, and affected invariant or specification. Do not choose a direction merely because it is easier to implement.

## Completion

Run relevant tests and `git diff --check`. Report changed files, results, deviations, and untracked files. Do not commit unless explicitly asked.
