"""Scriptable, dependency-free fake for the two Ollama HTTP endpoints we use."""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

Mode = Literal["valid", "invalid", "slow", "timeout", "disconnect", "model_404"]


def valid_response(suffix: str = "browser") -> str:
    return json.dumps({
        "competing_explanations": [
            f"Coordinated activity is plausible ({suffix}).",
            f"Legitimate shared access is plausible ({suffix}).",
        ],
        "plan_steps": [
            f"Review visible event timing ({suffix}).",
            "Compare governed relationship evidence.",
        ],
        "proposal": {
            "action": f"Compare the selected visible events ({suffix}).",
            "purpose": "Distinguish the competing explanations.",
            "why_now": "The governed context supports this bounded step.",
            "data_to_be_used": "visible_events.csv",
            "expected_output": "An investigator-readable comparison.",
        },
    })


@dataclass
class FakeOllama:
    mode: Mode = "valid"
    response_text: str = field(default_factory=valid_response)
    generation_calls: list[dict[str, object]] = field(default_factory=list)
    request_started: threading.Event = field(default_factory=threading.Event)
    release_response: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.release_response.set()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _json(self, status: int, payload: object) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/api/tags":
                    self._json(404, {})
                elif fake.mode == "model_404":
                    self._json(200, {"models": []})
                else:
                    self._json(200, {"models": [{"name": "qa-model"}]})

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/generate":
                    self._json(404, {})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    request = {"raw": raw.decode(errors="replace")}
                fake.generation_calls.append(request)
                fake.request_started.set()
                if fake.mode in ("slow", "timeout"):
                    fake.release_response.wait(timeout=30)
                if fake.mode == "disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                response = "not-json" if fake.mode == "invalid" else fake.response_text
                self._json(200, {"response": response})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def hold(self) -> None:
        self.mode = "slow"
        self.request_started.clear()
        self.release_response.clear()

    def release(self) -> None:
        self.release_response.set()

    def close(self) -> None:
        self.release_response.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
