# Fraud Investigation Generator

A local, seed-reproducible generator for synthetic fintech and payments fraud-investigation cases. The aim is to create a synthetic investigation environment—not merely a transaction-classification dataset.

## Current architecture

Python owns the canonical case world: entities, relationships, events, signals, ground truth, deterministic generation, and validation. Canonical ground truth is kept separate from the investigator-visible case view.

Ollama is reserved for constrained narrative, ambiguity, and human-facing artifacts around facts supplied by Python. It must not establish or alter canonical IDs, timestamps, relationships, events, amounts, or fraud truth.

## Status

The repository generates deterministic in-memory cases and includes a constrained, local Ollama adapter for development-only investigator-visible artifact generation. No production persistence format or external dependency is used.

To generate the fixed local review case with artifacts, start Ollama locally and run `python -m generator.dev.generate_artifacts`. Configure `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_TEMPERATURE`, or `OLLAMA_SEED` only when defaults are unsuitable.

Development is intentionally incremental: each small, approved change is validated before the next step. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for current progress and [docs/architecture.md](docs/architecture.md) for the architecture.
