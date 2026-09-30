# Validation directory

Offline validation and research tooling. **Nothing here is a product component**, and
nothing here may be wired into the application.

PO-4 (approved, `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` §8) puts scenario
definitions, harness code and summary records under one version-controlled validation
directory, and keeps raw model responses, run databases and logs out of version
control, referenced by run id.

| Path | Version-controlled? | Contents |
|---|---|---|
| `validation/qualification/` | yes | Harness code |
| `validation/qualification/scenarios/` | yes | Named scenario definitions |
| `validation/qualification/summaries/` | yes | Roll-up summary records, one per experiment |
| `validation/runs/` | **no** (git-ignored) | Verbatim prompts, verbatim responses, per-run records, semantic acceptance packages |

---

## Model Qualification Harness

Specified by `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` §4, at the observation
counts in §2.1. It answers "how good is this model at this job?" with **no Streamlit,
no browser and no investigation database**.

### What it is not

- Not a second generation call, not a semantic-adjudication boundary, not a repair or
  retry path. Each observation issues exactly one model request and accepts the result.
- Not a scorer. There is **no automated score, rubric-scoring model or LLM-as-judge**
  anywhere in it. ADR 006 rejected that class of false assurance. Semantic adequacy is
  judged by the Product Owner; the harness records, labels and presents.
- Not the campaign. Building the harness and running experiments are separate work
  (§9, steps 6 and 7). Running a sweep requires an explicit `--confirm-run`.

### Observation counts (§2.1, PO-2 and PO-8, approved)

Counts are **per semantic scenario, per candidate configuration**. V0.5 uses three
semantic scenarios — INITIAL, MODIFY, DECLINE/redirect — and each carries the full
count in its own right.

| Evidence class | Runs | Total per candidate configuration |
|---|---|---|
| Structural validity | 10 of each scenario | 30 runs |
| Semantic adequacy | 3 of each scenario | 9 plans, each read in full by the Product Owner |

One chained execution (INITIAL → MODIFY → DECLINE_REDIRECT) yields one observation of
each scenario, so ten chained repetitions satisfy all three scenarios.

**N=3 per scenario is a screening gate against gross instability, not a statistical
reliability guarantee.** The gate is three-of-three *within* each scenario. The nine
runs are never pooled into a single stronger-sounding claim, and no output describes
N=3 as establishing a reliability rate.

### Usage

```
py -3 -m validation.qualification --list-scenarios
py -3 -m validation.qualification --model qwen3:30b --label qwen3-30b-64k --dry-run
py -3 -m validation.qualification --model qwen3:30b --label qwen3-30b-64k --confirm-run
```

`--model` may be repeated to sweep several candidate configurations against the same
version-controlled scenario text; scenario text is never edited to run a sweep.
`OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_TEMPERATURE` and `OLLAMA_SEED` are
read from the environment, using the product's own deployment-configuration seam.

A run writes:

- `validation/runs/<experiment>/raw/<run-id>.prompt.txt` — the exact prompt;
- `validation/runs/<experiment>/raw/<run-id>.response.txt` — the exact raw response,
  captured **before** parsing, so an unparseable response is data rather than a lost run;
- `validation/runs/<experiment>/records/<run-id>.json` — the comparable per-run record;
- `validation/runs/<experiment>/semantic-acceptance/<configuration>.md` — the nine plans
  grouped by scenario and labelled with scenario and run index, for reading in full;
- `validation/qualification/summaries/<experiment>.json` — the roll-up summary record.

### Single contract definition

§7 records one genuine architecture constraint: the machine-checkable contract must
have a single definition, because a drifted harness reports model fitness against a
contract the product does not enforce. `validation/qualification/contract.py` therefore
**consumes** `parse_proposal_model_response` and the product's private-reference check
rather than restating any threshold, field list or token list.
`tests/test_qualification_contract.py` fails if the product rewords a check, and an
unrecognised message is reported as `UNATTRIBUTED_CONTRACT_FAILURE` rather than guessed
into a category.

### Evaluator isolation

Absolute. Context is only ever loaded through the product's governed
`load_investigator_package`, which reads solely the package's `investigator/` subtree.
Every prompt is scanned before dispatch and every record before it is written; a hit
aborts rather than redacting.

### Tests

```
py -3 -m pytest tests/test_qualification_*.py
```

No test contacts Ollama.
