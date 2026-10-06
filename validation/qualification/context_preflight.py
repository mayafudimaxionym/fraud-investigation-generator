"""Fail-closed 64K context gate wrapped around a qualification sweep.

The harness has no notion of context length: `num_ctx` is never sent, and the context
a sweep actually runs at is purely a property of whichever Ollama instance
`OLLAMA_BASE_URL` happens to point at. `cli.py` defaults that variable to
`http://localhost:11434`, the default-context instance. So a sweep can run at the
wrong context, write a complete-looking roll-up, exit 0, and leave nothing in the
evidence that reveals it. The roll-up's `environment` block records neither the
context length nor the base URL, and it is an approved ADR 006 artifact, so it is not
changed here.

This module is that missing signal, and nothing more. It resolves one endpoint, proves
the loaded context length by reading it back off the live server, and only then runs
the approved sweep command unchanged:

    py -3 -m validation.qualification.context_preflight \
        --model gpt-oss:20b --label gpt-oss-20b-64k \
        --experiment-id gpt-oss-20b-64k-4a17d59 --confirm-run

The arguments are the sweep's own arguments, forwarded verbatim. The gate reads three
of them without consuming them -- `--model`, `--experiment-id`, `--run-root` -- so the
model it proves is the model swept and the artifact lands in the run's own directory.

What counts as proof. Only the `context_length` that `GET /api/ps` reports for the
loaded model. An environment variable, a flag or an operator assertion is not proof,
so none is accepted: the required value is the constant below and cannot be relaxed
from a run specification. Reading it requires the model to be resident, so the gate
first issues the standard empty-prompt load (`POST /api/generate` with `"prompt": ""`,
`done_reason: "load"`). That dispatches no generation and is not an observation; the
sweep's own requests are left entirely alone.

Failure is always non-zero and always before the sweep starts. An unset or empty
`OLLAMA_BASE_URL` fails rather than falling back to the `cli.py` default.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from validation.qualification.storage import DEFAULT_RUN_ROOT, experiment_directory


#: The context length a qualification sweep must run at, in tokens. Deliberately a
#: constant and not an option: a gate whose threshold can be supplied by the run
#: specification it is gating is not a gate.
REQUIRED_CONTEXT_LENGTH = 65536

#: Written into the run's own directory on success. Declared in the worker's
#: `expectedArtifacts`, so its absence is itself a failure signal.
PREFLIGHT_ARTIFACT_NAME = "context-preflight.json"

#: Distinct from any exit code the sweep itself can produce, so "the gate refused" is
#: never confused with "the sweep failed".
PREFLIGHT_FAILURE_EXIT_CODE = 78

#: Loading a 13 GB model is far slower than answering from it, so the sweep's own
#: timeout seam is reused only when it is set explicitly.
DEFAULT_LOAD_TIMEOUT_SECONDS = 900.0


class PreflightFailure(Exception):
    """The context could not be proven. Always fails the command before the sweep."""


HttpGet = Callable[[str, float], Any]
HttpPost = Callable[[str, Mapping[str, Any], float], Any]


def main(argv: Sequence[str] | None = None) -> int:
    sweep_arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        proof = run_preflight(sweep_arguments, os.environ)
    except PreflightFailure as failure:
        print(f"PREFLIGHT FAILED: {failure}", file=sys.stderr)
        print("The sweep was not started.", file=sys.stderr)
        return PREFLIGHT_FAILURE_EXIT_CODE

    for model in proof["models"]:
        print(
            f"PREFLIGHT: {model['model']} loaded at context_length="
            f"{model['context_length']} (read back from {model['source']} "
            f"at {proof['base_url']})"
        )
    print(f"PREFLIGHT: required context_length={REQUIRED_CONTEXT_LENGTH} proven")
    print(f"PREFLIGHT: artifact {proof['artifact_path']}")
    print(f"PREFLIGHT: handing off to the sweep at {proof['base_url']}", flush=True)

    return run_sweep_command(sweep_arguments, proof["base_url"], os.environ)


def run_preflight(
    sweep_arguments: Sequence[str],
    environment: Mapping[str, str],
    *,
    http_get: HttpGet | None = None,
    http_post: HttpPost | None = None,
    write_artifact: bool = True,
) -> dict[str, Any]:
    """Prove the context length from the live server, or raise `PreflightFailure`."""
    get = http_get or _http_get_json
    post = http_post or _http_post_json

    base_url = resolve_base_url(environment)
    models, experiment_id, run_root = read_sweep_arguments(sweep_arguments)
    timeout = _load_timeout_seconds(environment)

    verified = []
    for model in models:
        _load_model(post, base_url, model, timeout)
        context_length, digest = _loaded_context_length(get, base_url, model, timeout)
        if context_length != REQUIRED_CONTEXT_LENGTH:
            raise PreflightFailure(
                f"{base_url} loaded {model} at context_length={context_length}, "
                f"but {REQUIRED_CONTEXT_LENGTH} is required"
            )
        verified.append(
            {
                "model": model,
                "context_length": context_length,
                "model_digest": digest,
                "source": "GET /api/ps",
            }
        )

    proof = {
        "artifact": "qualification-context-preflight",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_context_length": REQUIRED_CONTEXT_LENGTH,
        "base_url": base_url,
        "ollama_version": _ollama_version(get, base_url, timeout),
        "experiment_id": experiment_id,
        "models": verified,
        "proof": (
            "context_length as reported by GET /api/ps for the loaded model, after an "
            "empty-prompt load. Not supplied to the server by this gate."
        ),
    }

    artifact_path = experiment_directory(experiment_id, run_root) / PREFLIGHT_ARTIFACT_NAME
    if write_artifact:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    proof["artifact_path"] = str(artifact_path)
    return proof


def resolve_base_url(environment: Mapping[str, str]) -> str:
    """Resolve the one endpoint value. Never falls back to the `cli.py` default.

    Normalized exactly as `cli.py` normalizes it, so the endpoint proven here and the
    endpoint the sweep is handed are byte-identical.
    """
    raw = environment.get("OLLAMA_BASE_URL")
    if raw is None or not raw.strip():
        raise PreflightFailure(
            "OLLAMA_BASE_URL is unset or empty. The run specification must set it "
            "explicitly; falling back to the cli.py default would run the sweep at an "
            "unverified context."
        )
    return raw.strip().rstrip("/")


def read_sweep_arguments(
    sweep_arguments: Sequence[str],
) -> tuple[tuple[str, ...], str, Path]:
    """Read the model(s), experiment id and run root out of the sweep's own arguments.

    Reading them from the forwarded arguments rather than from separate options is what
    makes the proof binding: the model proven cannot differ from the model swept, and
    the artifact cannot land anywhere but the run's own directory.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    try:
        known, _ = parser.parse_known_args(list(sweep_arguments))
    except SystemExit as error:  # argparse exits on a malformed value
        raise PreflightFailure(f"could not read the sweep arguments: {error}") from error

    if not known.model:
        raise PreflightFailure(
            "no --model in the sweep arguments; there is nothing to prove the context for"
        )
    if not known.experiment_id:
        raise PreflightFailure(
            "no --experiment-id in the sweep arguments, so the run directory the "
            "preflight artifact belongs in cannot be resolved"
        )
    return tuple(known.model), known.experiment_id, known.run_root


def run_sweep_command(
    sweep_arguments: Sequence[str],
    base_url: str,
    environment: Mapping[str, str],
) -> int:
    """Run the approved sweep unchanged, at the proven endpoint, and pass its code on."""
    child_environment = dict(environment)
    child_environment["OLLAMA_BASE_URL"] = base_url
    completed = subprocess.run(
        [sys.executable, "-m", "validation.qualification", *sweep_arguments],
        env=child_environment,
    )
    return completed.returncode


def _load_model(post: HttpPost, base_url: str, model: str, timeout: float) -> None:
    """Make the model resident so its loaded context length can be read back.

    An empty prompt is Ollama's own load-only request: it generates nothing and returns
    `done_reason: "load"`. No `num_ctx` is sent, so the context observed afterwards is
    the one the server itself applies -- the same one the sweep will get.
    """
    try:
        payload = post(f"{base_url}/api/generate", {"model": model, "prompt": ""}, timeout)
    except PreflightFailure:
        raise
    except Exception as error:
        raise PreflightFailure(f"could not load {model} at {base_url}: {error}") from error
    if isinstance(payload, Mapping) and payload.get("done") is not True:
        raise PreflightFailure(f"{base_url} did not report {model} as loaded: {payload}")


def _loaded_context_length(
    get: HttpGet, base_url: str, model: str, timeout: float
) -> tuple[int, str | None]:
    try:
        payload = get(f"{base_url}/api/ps", timeout)
    except Exception as error:
        raise PreflightFailure(f"could not read {base_url}/api/ps: {error}") from error

    entries = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        raise PreflightFailure(f"{base_url}/api/ps returned no model list: {payload}")

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if model not in (entry.get("model"), entry.get("name")):
            continue
        context_length = entry.get("context_length")
        if not isinstance(context_length, int) or isinstance(context_length, bool):
            raise PreflightFailure(
                f"{base_url}/api/ps reported no usable context_length for {model}: "
                f"{entry.get('context_length')!r}. The context cannot be proven."
            )
        return context_length, entry.get("digest")

    loaded = [entry.get("model") for entry in entries if isinstance(entry, Mapping)]
    raise PreflightFailure(
        f"{model} is not resident at {base_url} after a load request; loaded: {loaded}"
    )


def _ollama_version(get: HttpGet, base_url: str, timeout: float) -> str | None:
    try:
        payload = get(f"{base_url}/api/version", timeout)
    except Exception:
        return None
    return payload.get("version") if isinstance(payload, Mapping) else None


def _load_timeout_seconds(environment: Mapping[str, str]) -> float:
    raw = environment.get("OLLAMA_TIMEOUT_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_LOAD_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError as error:
        raise PreflightFailure(f"OLLAMA_TIMEOUT_SECONDS is not a number: {raw!r}") from error


def _http_get_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - localhost
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(url: str, body: Mapping[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    sys.exit(main())
