# ADR 003: Structured Ollama Artifact Boundary

## Decision

Communication between Python and Ollama must use explicit structured contracts.

## Reason

Generated language must remain separate from canonical truth.

## Consequence

Python supplies authoritative facts and validates the machine-checkable structure, prohibited-reference boundary, and Python-owned identity/state constraints of model responses. Ollama is restricted to generated language, ambiguity, and human-readable artifacts.

For unrestricted natural-language investigation directions and proposals, this validation does not claim to prove semantic adequacy, responsiveness to an investigator instruction, absence of contradiction, or action narrowness. Those semantic judgments remain subject to the human-review boundary defined in ADR 006. This clarification does not weaken evaluator isolation, governed context, or Python ownership of canonical state.
