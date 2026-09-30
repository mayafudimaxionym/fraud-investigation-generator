"""Isolated Streamlit process and structured evidence utilities."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import urlopen


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Evidence:
    scenario_id: str
    directory: Path
    commit: str
    config: dict[str, object]
    steps: list[dict[str, object]] = field(default_factory=list)

    def step(self, name: str, expected: object, actual: object) -> None:
        self.steps.append({"step": name, "expected": expected, "actual": actual})
        self.flush()

    def snapshot(self, page: object, name: str) -> None:
        (self.directory / f"{name}.html").write_text(page.content(), encoding="utf-8")

    def persisted_rows(self, database: Path) -> None:
        rows: dict[str, object] = {}
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            for (table,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ):
                rows[table] = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
        (self.directory / "persisted_rows.json").write_text(
            json.dumps(rows, indent=2, default=str), encoding="utf-8"
        )

    def flush(self) -> None:
        (self.directory / "evidence.json").write_text(json.dumps({
            "scenario_id": self.scenario_id,
            "commit": self.commit,
            "config": self.config,
            "steps": self.steps,
        }, indent=2), encoding="utf-8")


@dataclass
class LiveApplication:
    url: str
    database: Path
    process: subprocess.Popen[str]
    log_handle: object
    evidence: Evidence

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.log_handle.close()
        if self.database.exists():
            self.evidence.persisted_rows(self.database)
        self.evidence.flush()


@contextmanager
def live_application(
    root: Path,
    scenario_id: str,
    fake_url: str,
    *,
    timeout_seconds: float = 3,
    inject_transport_oserror: bool = False,
):
    scenario = root / scenario_id
    scenario.mkdir(parents=True)
    database = (scenario / "scenario.sqlite").resolve()
    log_path = scenario / "streamlit.log"
    log_handle = log_path.open("w", encoding="utf-8")
    port = _free_port()
    commit = subprocess.run(
        ["git", "-c", f"safe.directory={Path.cwd().as_posix()}", "rev-parse", "HEAD"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True,
    ).stdout.strip()
    config = {
        "database": str(database), "ollama_base_url": fake_url,
        "ollama_model": "qa-model", "ollama_timeout_seconds": timeout_seconds,
        "streamlit_port": port,
    }
    evidence = Evidence(scenario_id, scenario, commit, config)
    evidence.flush()
    env = os.environ.copy()
    env.update({
        "INVESTIGATION_DATABASE_PATH": str(database),
        "OLLAMA_BASE_URL": fake_url,
        "OLLAMA_MODEL": "qa-model",
        "OLLAMA_TIMEOUT_SECONDS": str(timeout_seconds),
        "OLLAMA_TEMPERATURE": "0",
        "OLLAMA_SEED": "42",
    })
    streamlit_module = (
        "tests.browser.injected_streamlit"
        if inject_transport_oserror
        else "streamlit"
    )
    process = subprocess.Popen([
        sys.executable, "-m", streamlit_module, "run", "investigation/app.py",
        "--server.headless=true", f"--server.port={port}",
        "--browser.gatherUsageStats=false",
    ], cwd=Path.cwd(), env=env, stdin=subprocess.DEVNULL,
       stdout=log_handle, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Streamlit exited early; see {log_path}")
        try:
            with urlopen(f"{url}/_stcore/health", timeout=.5) as reply:
                if reply.status == 200:
                    break
        except OSError:
            continue
    else:
        raise RuntimeError(f"Streamlit did not become ready; see {log_path}")
    app = LiveApplication(url, database, process, log_handle, evidence)
    try:
        yield app
    finally:
        app.close()


def operation_rows(database: Path) -> list[dict[str, object]]:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT * FROM agent_operations ORDER BY created_at, operation_id"
        )]
