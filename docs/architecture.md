# Architecture

## Purpose

This project is building a synthetic fraud-investigation environment for testing an AI-powered Fraud Intelligence Framework. It is not designed as a simple synthetic transaction generator or fraud-classification dataset. A useful case should support an investigation: competing explanations, incomplete evidence, plausible red herrings, and fraud signals that can be discovered through relationships and behavior.

## Case graph as the conceptual core

The primary abstraction is a case graph. Its evolving canonical world models entities and their connections, including actors, accounts, devices, networks, beneficiaries, events, and relationships. Tables and other datasets are derived representations of that world rather than the starting point for assigning labels.

This orientation prioritizes relational and behavioral realism. For example, useful signals can arise from shared devices, unusual temporal clustering, event ordering, or interaction patterns rather than from an isolated transaction field.

## Information boundaries

The current model separates four concerns:

- **Canonical world:** Python-owned entities, relationships, events, and signals.
- **Ground truth:** private campaign, fraud, causal-signal, red-herring, and hypothesis adjudication references.
- **Investigator-visible evidence:** the entities, events, and artifacts available to an investigator or evaluation framework.
- **Generated artifacts:** investigator-visible human language such as client communications, produced around Python-supplied facts.

Ground truth is intentionally distinct from the investigator view. An investigation framework should not receive the truth-side manifest during normal testing.

## Responsibilities

Python owns canonical facts: identifiers, timestamps, relationships, events, fraud status, causal truth, reproducibility, and validation. It builds and validates the world deterministically.

Ollama is reserved for language generation around constrained, Python-provided facts. Its role is narrative, controlled ambiguity, and messy human artifacts. It must not silently invent canonical IDs, timestamps, relationships, amounts, events, or fraud truth.

The artifact interface is structured: Python sends an explicit request containing the allowed canonical facts, and Python validates the returned language before associating it with a known artifact.

## Determinism and validation

Cases are intended to be reproducible from a master seed with derived component seeds and recorded generation metadata. Validation is deterministic and currently checks identifier uniqueness, reference integrity, event ordering, world consistency, and alignment between declared competing hypotheses and private ground truth.

Future case construction must preserve legitimate lookalikes, competing hypotheses, and discoverable fraud signals. Legitimate lookalikes should resemble suspicious behavior on selected dimensions while remaining distinguishable through deeper evidence. A valid case should make the intended fraud mechanism discoverable from the investigator-visible evidence without exposing the ground truth directly.
