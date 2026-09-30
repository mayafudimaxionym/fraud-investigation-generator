# Experiment summary records

Version-controlled roll-up summaries, one JSON file per experiment id (PO-4, approved).

A summary carries per-scenario run counts, failure categories and the structural
validity rate. It carries **no quality score and no acceptance verdict**: structural
results are counts, and semantic adequacy is decided only by the Product Owner, reading
every presented run in full.

The raw prompts, the verbatim responses and the per-run records for an experiment stay
out of version control under `validation/runs/<experiment-id>/`, referenced by run id.

This directory is empty until an experiment is run. Running the qualification campaign
is the AI Model Qualification Researcher's work, not the harness build's.
