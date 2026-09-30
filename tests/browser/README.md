# V0.5 real-browser gate

This directory contains the minimal PO-1 browser journeys. The in-process
Streamlit lifecycle suite remains the primary deterministic gate.

Install the test extra and Chromium once:

```powershell
python -m pip install -e ".[test]"
python -m playwright install chromium
```

Run the complete browser gate or one scenario:

```powershell
python -m pytest tests/browser/test_v05_gating_journeys.py --browser chromium
python -m pytest tests/browser/test_v05_gating_journeys.py::test_transport_disconnect_is_not_persistence_failure --browser chromium
```

`QA_OBJECTIVE` and `QA_DECLINE_GUIDANCE` parameterize investigator text.
Set `QA_EVIDENCE_DIR` to an absolute directory outside version control to retain
the structured JSON evidence, Streamlit logs, database-row capture, and HTML
page snapshots. Without it, pytest's temporary directory is used and cleaned
normally. Every scenario gets its own Streamlit process and SQLite database.
