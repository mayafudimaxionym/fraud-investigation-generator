import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

from generator.artifacts.ollama import OllamaConfig
from generator.dev.package_case import export_development_investigation_package
from investigation.package_access import (
    DatasetInventory,
    InvestigatorPackageContext,
    load_investigator_package,
)
from investigation.proposal_agent import (
    LocalProposalAgent,
    OllamaProposalClient,
    build_proposal_prompt,
    parse_proposal_model_response,
)


class FakeProposalClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeOllamaReply:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "FakeOllamaReply":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _context() -> InvestigatorPackageContext:
    return InvestigatorPackageContext(
        investigation_request="Review the reported unusual account activity.",
        customer_support_statement="The customer reported unexpected transfer activity.",
        prior_analyst_note="No prior structured analysis has been performed.",
        datasets=(
            DatasetInventory("visible_entities.csv", 119, ("entity_id", "entity_type")),
            DatasetInventory(
                "visible_relationships.csv",
                151,
                (
                    "relationship_id",
                    "source_entity_id",
                    "target_entity_id",
                    "relationship_type",
                ),
            ),
            DatasetInventory(
                "visible_events.csv",
                200,
                (
                    "event_id",
                    "event_type",
                    "subject_entity_id",
                    "target_entity_id",
                    "occurred_at",
                ),
            ),
        ),
    )


def _payload(**overrides: object) -> str:
    response: dict[str, object] = {
        "provisional_plan": "First inspect the available event sequence data.",
        "action": "Review visible_events.csv for relevant login and transfer sequences.",
        "purpose": "Assess whether reported activity warrants further analysis.",
        "why_now": "The investigation request and available event inventory make this the next step.",
        "data_to_be_used": "visible_events.csv and the investigation request.",
        "expected_output": "A bounded summary of candidate event sequences for review.",
    }
    response.update(overrides)
    return json.dumps(response)


def _agent(response: str) -> tuple[LocalProposalAgent, FakeProposalClient]:
    client = FakeProposalClient(response)
    return LocalProposalAgent(client), client


def test_valid_response_returns_one_plan_and_proposed_proposal() -> None:
    agent, client = _agent(_payload())
    created_at = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

    result = agent.propose(_context(), "Investigate the reported concern.", "proposal-001", created_at)

    assert result.provisional_plan == "First inspect the available event sequence data."
    assert result.proposal.proposal_id == "proposal-001"
    assert result.proposal.created_at == created_at
    assert result.proposal.status == "PROPOSED"
    assert (
        result.proposal.action,
        result.proposal.purpose,
        result.proposal.why_now,
        result.proposal.data_to_be_used,
        result.proposal.expected_output,
    ) == (
        "Review visible_events.csv for relevant login and transfer sequences.",
        "Assess whether reported activity warrants further analysis.",
        "The investigation request and available event inventory make this the next step.",
        "visible_events.csv and the investigation request.",
        "A bounded summary of candidate event sequences for review.",
    )
    assert len(client.prompts) == 1


def test_visible_data_to_be_used_value_is_accepted() -> None:
    agent, _ = _agent(_payload(data_to_be_used="visible_events.csv and the investigation request"))

    result = agent.propose(
        _context(),
        "Investigate the reported concern.",
        "proposal-001",
        datetime(2026, 9, 23, tzinfo=timezone.utc),
    )

    assert result.proposal.data_to_be_used == "visible_events.csv and the investigation request"


def test_prompt_contains_only_authorized_context_and_safe_inventory() -> None:
    context = _context()
    prompt = build_proposal_prompt(context, "Investigate the reported concern.")

    assert "Investigate the reported concern." in prompt
    assert context.investigation_request in prompt
    assert context.customer_support_statement in prompt
    assert context.prior_analyst_note in prompt
    for dataset in context.datasets:
        assert dataset.dataset_name in prompt
        assert str(dataset.row_count) in prompt
        assert ", ".join(dataset.field_names) in prompt


def test_structured_row_marker_cannot_enter_model_prompt(tmp_path: Path) -> None:
    package = export_development_investigation_package(tmp_path)
    marker = "UNIQUE-PROPOSAL-PROMPT-ROW-MARKER"
    entity_file = package / "investigator" / "data" / "visible_entities.csv"
    with entity_file.open("a", encoding="utf-8", newline="") as csv_file:
        csv.writer(csv_file).writerow((marker, "account"))
    context = load_investigator_package(package)

    prompt = build_proposal_prompt(context, "Investigate the reported concern.")

    assert marker not in context.investigation_request
    assert marker not in context.customer_support_statement
    assert marker not in context.prior_analyst_note
    assert marker not in prompt
    assert "120 rows" in prompt


def test_evaluator_content_and_filenames_cannot_enter_model_prompt(tmp_path: Path) -> None:
    package = export_development_investigation_package(tmp_path)
    marker = "UNIQUE-EVALUATOR-ONLY-MARKER"
    (package / "evaluator_only" / "never-agent-marker.txt").write_text(marker, encoding="utf-8")

    prompt = build_proposal_prompt(
        load_investigator_package(package), "Investigate the reported concern."
    )

    assert marker not in prompt
    assert "evaluator_only" not in prompt
    assert "ground_truth.csv" not in prompt


def test_missing_or_extra_response_keys_fail_safely() -> None:
    missing = json.dumps({"action": "Review events."})
    extra = _payload(extra="not allowed")

    with pytest.raises(ValueError, match="exactly the required fields"):
        parse_proposal_model_response(missing)
    with pytest.raises(ValueError, match="exactly the required fields"):
        parse_proposal_model_response(extra)


@pytest.mark.parametrize(
    "data_to_be_used",
    ("ground_truth.csv", "evaluator_only/signals.csv"),
)
def test_private_data_references_are_rejected_before_returning_proposal(
    data_to_be_used: str,
) -> None:
    agent, client = _agent(_payload(data_to_be_used=data_to_be_used))

    with pytest.raises(ValueError, match="outside governed context"):
        agent.propose(
            _context(),
            "Investigate the reported concern.",
            "proposal-001",
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )

    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    "response",
    (
        _payload(action=["not", "a", "string"]),
        _payload(action="   "),
        "not JSON",
        "[]",
    ),
)
def test_invalid_response_values_or_shapes_fail_safely(response: str) -> None:
    agent, _ = _agent(response)

    with pytest.raises(ValueError):
        agent.propose(
            _context(),
            "Investigate the reported concern.",
            "proposal-001",
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )


def test_local_ollama_transport_failure_returns_no_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise URLError("connection refused")

    monkeypatch.setattr("investigation.proposal_agent.urlopen", unavailable)
    agent = LocalProposalAgent(
        OllamaProposalClient(OllamaConfig(base_url="http://localhost:11434"))
    )

    with pytest.raises(RuntimeError, match="Ollama proposal generation failed"):
        agent.propose(
            _context(),
            "Investigate the reported concern.",
            "proposal-001",
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "outer_body",
    (
        b"[]",
        b"{}",
        b'{"response": 3}',
        b"not JSON",
    ),
)
def test_invalid_outer_ollama_responses_fail_through_transport_boundary(
    monkeypatch: pytest.MonkeyPatch, outer_body: bytes
) -> None:
    monkeypatch.setattr(
        "investigation.proposal_agent.urlopen",
        lambda *_args, **_kwargs: FakeOllamaReply(outer_body),
    )
    client = OllamaProposalClient(OllamaConfig(base_url="http://localhost:11434"))

    with pytest.raises(RuntimeError):
        client.generate("Return JSON.")


@pytest.mark.parametrize("instruction", ("", "   ", None, 7))
def test_invalid_instruction_is_rejected_before_model_invocation(instruction: object) -> None:
    agent, client = _agent(_payload())

    with pytest.raises(ValueError, match="investigator_instruction"):
        agent.propose(
            _context(),
            instruction,  # type: ignore[arg-type]
            "proposal-001",
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )

    assert client.prompts == []


def test_agent_has_no_execution_or_persistence_collaborator() -> None:
    agent, client = _agent(_payload())

    result = agent.propose(
        _context(),
        "Investigate the reported concern.",
        "proposal-001",
        datetime(2026, 9, 23, tzinfo=timezone.utc),
    )

    assert result.proposal.status == "PROPOSED"
    assert len(client.prompts) == 1
    assert not hasattr(agent, "execute")
    assert not hasattr(agent, "store")
