# ADR 003: Structured Ollama Artifact Boundary

## Decision

Communication between Python and Ollama must use explicit structured contracts.

## Reason

Generated language must remain separate from canonical truth.

## Consequence

Python supplies authoritative facts and validates model responses. Ollama is restricted to generated language, ambiguity, and human-readable artifacts.
