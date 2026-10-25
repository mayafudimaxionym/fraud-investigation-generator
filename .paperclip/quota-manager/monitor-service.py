#!/usr/bin/env python3
"""Windowless, logged entry point for the supervised quota monitor.

This is host-supervision plumbing only. It contributes no policy value: the
canonical company policy remains the single source of thresholds, intervals,
timeouts, and behaviors. The scheduled task runs this module under
``pythonw.exe`` so the monitor has no console window; because that host has no
usable standard streams, this module points them at an append-only log so a
crash or a configuration-incomplete exit stays diagnosable.

Supervision (start at logon, restart after an unexpected exit) belongs to the
Windows Scheduled Task, not to this module. It therefore does not retry or
loop on its own.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_LOG_BYTES = 1_048_576


def _stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def rotate_log(log_path: Path, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Keep one previous log so a restart loop cannot fill the disk."""
    try:
        if log_path.is_file() and log_path.stat().st_size > max_bytes:
            previous = log_path.with_suffix(log_path.suffix + ".1")
            previous.unlink(missing_ok=True)
            log_path.replace(previous)
    except OSError:
        # Logging must never prevent the monitor from starting.
        pass


def monitor_argv(company_dir: Path) -> list[str]:
    return [
        "monitor",
        "--policy",
        str(company_dir / "policy.json"),
        "--state",
        str(company_dir / "state.json"),
        "--events",
        str(company_dir / "control-events.jsonl"),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    args = parser.parse_args(argv)

    company_dir = ROOT / "companies" / args.company
    if not (company_dir / "policy.json").is_file():
        print(f"missing policy for company {args.company}", file=sys.stderr)
        return 78

    log_path = company_dir / "monitor.log"
    rotate_log(log_path)
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    print(f"{_stamp()} monitor-service start pid={os.getpid()}")

    sys.path.insert(0, str(ROOT))
    from quota_manager import command_main

    try:
        code = command_main(monitor_argv(company_dir))
    except KeyboardInterrupt:
        print(f"{_stamp()} monitor-service interrupted")
        return 130
    except BaseException:  # noqa: BLE001 - the supervisor restarts; the log must say why.
        print(f"{_stamp()} monitor-service crashed")
        traceback.print_exc(file=log)
        return 70
    print(f"{_stamp()} monitor-service exit code={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
