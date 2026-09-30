from __future__ import annotations

import json
from http.client import RemoteDisconnected
from urllib.request import Request, urlopen

import pytest

from tests.browser.fake_ollama import FakeOllama


@pytest.mark.parametrize("mode", ["valid", "invalid", "slow", "timeout", "disconnect", "model_404"])
def test_fake_ollama_modes_are_scriptable_and_generation_is_countable(mode: str) -> None:
    fake = FakeOllama(mode=mode).start()
    if mode in ("slow", "timeout"):
        fake.release_response.set()
    try:
        if mode == "model_404":
            assert json.load(urlopen(f"{fake.base_url}/api/tags")) == {"models": []}
            return
        request = Request(f"{fake.base_url}/api/generate", data=b"{}", method="POST")
        if mode == "disconnect":
            with pytest.raises((RemoteDisconnected, ConnectionError, OSError)):
                urlopen(request).read()
        else:
            payload = json.load(urlopen(request))
            assert (payload["response"] == "not-json") is (mode == "invalid")
        assert len(fake.generation_calls) == 1
    finally:
        fake.close()


def test_unreachable_transport_is_represented_by_closed_endpoint() -> None:
    fake = FakeOllama().start()
    endpoint = fake.base_url
    fake.close()
    with pytest.raises(OSError):
        urlopen(f"{endpoint}/api/tags", timeout=.2)
