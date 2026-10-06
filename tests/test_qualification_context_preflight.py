"""The 64K context gate, exercised without a server.

The gate's real evidence is the live demonstration against the two Ollama instances --
a gate never shown to fail is not evidence. These tests cover the decision logic around
that readback so the failure paths stay closed under change: no test here reaches the
network, and none dispatches a model request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from validation.qualification.context_preflight import (
    PREFLIGHT_ARTIFACT_NAME,
    REQUIRED_CONTEXT_LENGTH,
    PreflightFailure,
    read_sweep_arguments,
    resolve_base_url,
    run_preflight,
)
from validation.qualification.storage import DEFAULT_RUN_ROOT


MODEL = "gpt-oss:20b"
BASE_URL = "http://127.0.0.1:11435"
SWEEP_ARGUMENTS = [
    "--model", MODEL,
    "--label", "gpt-oss-20b-64k",
    "--experiment-id", "gpt-oss-20b-64k-4a17d59",
    "--confirm-run",
]


def _stub_server(context_length: Any, *, loaded: bool = True) -> tuple[Any, Any]:
    """A `/api/ps` that reports `context_length` for the loaded model."""
    entry: dict[str, Any] = {"model": MODEL, "digest": "sha256-stub"}
    if context_length is not None:
        entry["context_length"] = context_length

    def get(url: str, timeout: float) -> Any:
        if url.endswith("/api/ps"):
            return {"models": [entry] if loaded else []}
        if url.endswith("/api/version"):
            return {"version": "0.34.4"}
        raise AssertionError(f"unexpected GET {url}")

    def post(url: str, body: Any, timeout: float) -> Any:
        assert url.endswith("/api/generate")
        assert body == {"model": MODEL, "prompt": ""}, "the load must send no num_ctx"
        return {"done": True, "done_reason": "load"}

    return get, post


def test_the_required_context_length_is_a_constant_not_an_option() -> None:
    """A threshold the gated run specification could supply is not a gate."""
    assert REQUIRED_CONTEXT_LENGTH == 65536


def test_an_unset_base_url_fails_instead_of_using_the_cli_default() -> None:
    with pytest.raises(PreflightFailure, match="OLLAMA_BASE_URL is unset or empty"):
        resolve_base_url({})


def test_an_empty_base_url_fails_instead_of_using_the_cli_default() -> None:
    with pytest.raises(PreflightFailure, match="OLLAMA_BASE_URL is unset or empty"):
        resolve_base_url({"OLLAMA_BASE_URL": "   "})


def test_the_resolved_base_url_is_normalized_the_way_the_harness_normalizes_it() -> None:
    assert resolve_base_url({"OLLAMA_BASE_URL": " http://127.0.0.1:11435/ "}) == BASE_URL


def test_the_model_and_run_directory_come_from_the_sweeps_own_arguments() -> None:
    models, experiment_id, run_root = read_sweep_arguments(SWEEP_ARGUMENTS)
    assert models == (MODEL,)
    assert experiment_id == "gpt-oss-20b-64k-4a17d59"
    assert run_root == DEFAULT_RUN_ROOT


def test_a_sweep_without_a_model_cannot_be_gated() -> None:
    with pytest.raises(PreflightFailure, match="no --model"):
        read_sweep_arguments(["--experiment-id", "x", "--confirm-run"])


def test_a_sweep_without_an_experiment_id_cannot_be_gated() -> None:
    with pytest.raises(PreflightFailure, match="no --experiment-id"):
        read_sweep_arguments(["--model", MODEL, "--confirm-run"])


def test_the_proven_context_is_the_value_read_back_and_is_recorded(tmp_path: Path) -> None:
    get, post = _stub_server(REQUIRED_CONTEXT_LENGTH)
    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]

    proof = run_preflight(
        arguments,
        {"OLLAMA_BASE_URL": BASE_URL},
        http_get=get,
        http_post=post,
    )

    assert proof["base_url"] == BASE_URL
    assert proof["models"] == [
        {
            "model": MODEL,
            "context_length": REQUIRED_CONTEXT_LENGTH,
            "model_digest": "sha256-stub",
            "source": "GET /api/ps",
        }
    ]
    artifact = tmp_path / "gpt-oss-20b-64k-4a17d59" / PREFLIGHT_ARTIFACT_NAME
    assert artifact.exists()
    assert proof["artifact_path"] == str(artifact)
    assert proof["verified_at_utc"].endswith("+00:00")


def test_a_context_below_the_requirement_fails_and_writes_nothing(tmp_path: Path) -> None:
    get, post = _stub_server(4096)
    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]

    with pytest.raises(PreflightFailure, match="context_length=4096"):
        run_preflight(arguments, {"OLLAMA_BASE_URL": BASE_URL}, http_get=get, http_post=post)

    assert not (tmp_path / "gpt-oss-20b-64k-4a17d59").exists()


def test_a_context_above_the_requirement_also_fails(tmp_path: Path) -> None:
    """Exactly 65536, not at least: the configuration record must be the truth."""
    get, post = _stub_server(131072)
    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]

    with pytest.raises(PreflightFailure, match="context_length=131072"):
        run_preflight(arguments, {"OLLAMA_BASE_URL": BASE_URL}, http_get=get, http_post=post)


def test_an_unreadable_context_length_is_a_failure_not_an_assumption(tmp_path: Path) -> None:
    get, post = _stub_server(None)
    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]

    with pytest.raises(PreflightFailure, match="no usable context_length"):
        run_preflight(arguments, {"OLLAMA_BASE_URL": BASE_URL}, http_get=get, http_post=post)


def test_a_model_that_is_not_resident_is_a_failure(tmp_path: Path) -> None:
    get, post = _stub_server(REQUIRED_CONTEXT_LENGTH, loaded=False)
    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]

    with pytest.raises(PreflightFailure, match="is not resident"):
        run_preflight(arguments, {"OLLAMA_BASE_URL": BASE_URL}, http_get=get, http_post=post)


def test_an_unreachable_server_is_a_failure(tmp_path: Path) -> None:
    def get(url: str, timeout: float) -> Any:
        raise OSError("connection refused")

    def post(url: str, body: Any, timeout: float) -> Any:
        raise OSError("connection refused")

    arguments = [*SWEEP_ARGUMENTS, "--run-root", str(tmp_path)]
    with pytest.raises(PreflightFailure, match="could not load"):
        run_preflight(arguments, {"OLLAMA_BASE_URL": BASE_URL}, http_get=get, http_post=post)
