"""Launch Streamlit with a deterministic unclassified transport failure."""

from __future__ import annotations

from urllib.request import Request

from investigation import proposal_agent
from streamlit.web import cli as streamlit_cli


_urlopen = proposal_agent.urlopen


def _disconnect_during_generation(
    request: Request, *args: object, **kwargs: object
) -> object:
    if request.full_url.endswith("/api/generate"):
        raise OSError("harness-controlled transport disconnect")
    return _urlopen(request, *args, **kwargs)


proposal_agent.urlopen = _disconnect_during_generation

if __name__ == "__main__":
    streamlit_cli.main()
