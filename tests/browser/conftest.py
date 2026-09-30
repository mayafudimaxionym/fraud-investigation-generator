from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    configured = os.environ.get("QA_EVIDENCE_DIR")
    root = Path(configured).resolve() if configured else tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def bounded_browser_waits(request: pytest.FixtureRequest) -> None:
    """Keep a missing stable locator from consuming an entire scenario run."""
    if request.node.get_closest_marker("real_browser") is not None:
        request.getfixturevalue("page").set_default_timeout(7_000)
