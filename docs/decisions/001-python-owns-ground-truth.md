# ADR 001: Python Owns Canonical Ground Truth

## Decision

Canonical IDs, timestamps, relationships, fraud status, event truth, and causal truth are owned only by Python.

## Reason

LLM output must not silently alter causal truth or reproducibility.

## Consequence

Ollama may generate narrative or language but cannot invent canonical facts.
