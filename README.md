# Fraud Investigation Generator

A local, seed-reproducible generator for synthetic fintech and payments fraud-investigation cases. The aim is to create a synthetic investigation environment—not merely a transaction-classification dataset.

## Current architecture

Python owns the canonical case world: entities, relationships, events, signals, ground truth, deterministic generation, and validation. Canonical ground truth is kept separate from the investigator-visible case view.

Ollama is reserved for constrained narrative, ambiguity, and human-facing artifacts around facts supplied by Python. It must not establish or alter canonical IDs, timestamps, relationships, events, amounts, or fraud truth.

## Status

The repository currently contains dependency-free domain contracts and deterministic validation foundations. It does not yet generate synthetic cases or invoke Ollama.

Development is intentionally incremental: each small, approved change is validated before the next step. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for current progress and [docs/architecture.md](docs/architecture.md) for the architecture.
