# ADR 004: Versioned Investigation Direction

## Decision

V0.5 introduces `InvestigationDirection` as a lightweight, persisted, versioned snapshot of an investigation's textual competing explanations and textual provisional plan steps.

Each version has minimal creation/version metadata and provenance that identifies why it exists, such as `INITIAL`, `MODIFY`, or `DECLINE_REDIRECT`, with a relevant proposal or decision trigger where appropriate. Versions append rather than overwrite.

For V0.5, the ordered textual lists may be stored as structured JSON text in SQLite and are preferred over relational hypothesis or plan entities.

## Reason

An investigator must be able to resume an investigation, understand its current direction, and understand why its direction changed without relying on transient UI state, chat history, or LLM memory.

## Consequence

The current direction supports investigation continuity and minimal provenance while leaving the existing single proposed next action as the only authorization candidate. It is not a formal Hypothesis, Finding, Evidence, confidence score, executable task, institutional-memory record, or general provenance graph. Formal knowledge modeling remains deferred.
