import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from generator.dev.package_case import export_development_investigation_package
from investigation.models import AnalyticalActionProposal, InvestigationDirection
from investigation.package_access import (
    DatasetInventory,
    InvestigatorPackageContext,
    load_investigator_package,
)
from investigation.proposal_agent import (
    CandidateDirectionContent,
    LocalProposalAgent,
    OllamaProposalClient,
    ProposalAgentResult,
    ProposalGenerationRequest,
    ProposalModelError,
    ProposalModelFailureCategory,
    ProposalOllamaConfig,
    build_proposal_prompt,
    parse_proposal_model_response,
)


BASE_TIME = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


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
                "visible_relationships.csv", 151,
                ("relationship_id", "source_entity_id", "target_entity_id", "relationship_type"),
            ),
            DatasetInventory(
                "visible_events.csv", 200,
                ("event_id", "event_type", "subject_entity_id", "target_entity_id", "occurred_at"),
            ),
        ),
    )


def _proposal(proposal_id: str = "proposal-001") -> AnalyticalActionProposal:
    return AnalyticalActionProposal(
        proposal_id, "Review visible events.", "Assess the activity.",
        "The available evidence requires review.", "visible_events.csv",
        "A bounded investigator-readable summary.", "PROPOSED", BASE_TIME,
    )


def _direction() -> InvestigationDirection:
    return InvestigationDirection(
        "direction-001", "investigation-001", 1,
        ("The activity may be coordinated.", "The activity may be legitimate shared use."),
        ("Review visible events.", "Compare relationship evidence."),
        BASE_TIME, "INITIAL",
    )


def _request(
    *,
    mode: str = "INITIAL",
    objective: str = "Assess the reported activity.",
    guidance: str | None = None,
) -> ProposalGenerationRequest:
    kwargs: dict[str, object] = {
        "context": _context(), "objective": objective, "proposal_id": "proposal-002",
        "created_at": BASE_TIME, "mode": mode,
    }
    if mode == "INITIAL":
        kwargs["investigator_instruction"] = "Investigate the reported concern."
    elif mode == "MODIFY":
        kwargs.update(
            current_direction=_direction(), source_proposal=_proposal(),
            investigator_instruction="Focus on events before relationships.",
        )
    else:
        kwargs.update(
            current_direction=_direction(), source_proposal=_proposal(),
            decline_guidance=guidance,
        )
    return ProposalGenerationRequest(**kwargs)  # type: ignore[arg-type]


def _payload(**overrides: object) -> str:
    response: dict[str, object] = {
        "competing_explanations": [
            "The activity may be coordinated misuse.",
            "The activity may be legitimate shared access.",
        ],
        "plan_steps": [
            "Review available event timing.",
            "Compare visible relationship evidence.",
        ],
        "proposal": {
            "action": "Review visible_events.csv for relevant login and transfer sequences.",
            "purpose": "Distinguish the plausible explanations using available records.",
            "why_now": "The investigation request and visible inventory identify event timing as the next step.",
            "data_to_be_used": "visible_events.csv and the investigation request.",
            "expected_output": "A bounded summary of candidate event sequences for investigator review.",
        },
    }
    response.update(overrides)
    return json.dumps(response)


def _payload_with_proposal_field(field_name: str, value: str) -> str:
    payload = json.loads(_payload())
    payload["proposal"][field_name] = value
    return json.dumps(payload)


def _agent(response: str) -> tuple[LocalProposalAgent, FakeProposalClient]:
    client = FakeProposalClient(response)
    return LocalProposalAgent(client), client


def _config() -> ProposalOllamaConfig:
    return ProposalOllamaConfig(base_url="http://localhost:11434", model="llama3:8b", timeout_seconds=123)


def test_valid_initial_response_preserves_order_and_returns_one_unchanged_proposal() -> None:
    agent, client = _agent(_payload())
    result = agent.generate(_request())

    assert result.direction == CandidateDirectionContent(
        ("The activity may be coordinated misuse.", "The activity may be legitimate shared access."),
        ("Review available event timing.", "Compare visible relationship evidence."),
    )
    assert result.provisional_plan == "Review available event timing.\nCompare visible relationship evidence."
    assert result.proposal.proposal_id == "proposal-002"
    assert result.proposal.created_at == BASE_TIME
    assert result.proposal.status == "PROPOSED"
    assert tuple(getattr(result.proposal, field) for field in (
        "action", "purpose", "why_now", "data_to_be_used", "expected_output"
    )) == tuple(json.loads(_payload())["proposal"].values())
    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    "payload",
    (
        _payload(competing_explanations=["  "]),
        _payload(competing_explanations="not a list"),
        _payload(plan_steps=["  "]),
        _payload(proposal={"action": ["not", "a", "string"], "purpose": "p", "why_now": "w", "data_to_be_used": "d", "expected_output": "e"}),
        _payload(proposal={"action": "", "purpose": "p", "why_now": "w", "data_to_be_used": "d", "expected_output": "e"}),
        "not JSON",
        "[]",
        json.dumps({"competing_explanations": [], "plan_steps": []}),
        json.dumps({"competing_explanations": [], "plan_steps": [], "proposal": {}}),
        _payload(proposal_id="model-must-not-own-identifiers"),
        _payload(proposal={"action": "a", "purpose": "p", "why_now": "w", "data_to_be_used": "d", "expected_output": "e", "status": "PROPOSED"}),
    ),
)
def test_invalid_or_model_owned_response_content_is_rejected(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_proposal_model_response(payload)


def test_invalid_model_response_becomes_a_generation_error_before_proposal_return() -> None:
    agent, _ = _agent("not JSON")
    with pytest.raises(ProposalModelError) as error:
        agent.generate(_request())
    assert error.value.category is ProposalModelFailureCategory.GENERATION_ERROR


@pytest.mark.parametrize(
    "model_owned_field",
    (
        "proposal_id",
        "investigation_id",
        "direction_id",
        "version",
        "created_at",
        "status",
        "revision_of_proposal_id",
        "provenance",
        "authorization_state",
        "execution_state",
    ),
)
def test_model_owned_persistence_or_lifecycle_fields_are_rejected(
    model_owned_field: str,
) -> None:
    with pytest.raises(ValueError, match="exactly the required fields"):
        parse_proposal_model_response(_payload(**{model_owned_field: "not allowed"}))


def test_legacy_propose_wrapper_remains_a_thin_initial_generation_adapter() -> None:
    agent, _ = _agent(_payload())
    result = agent.propose(
        _context(), "Investigate the reported concern.", "proposal-legacy", BASE_TIME
    )

    assert result.proposal.proposal_id == "proposal-legacy"
    assert result.direction.plan_steps == (
        "Review available event timing.", "Compare visible relationship evidence."
    )


def test_legacy_propose_wrapper_delegates_to_the_structured_generation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, _ = _agent(_payload())
    expected = ProposalAgentResult("derived plan", _proposal("proposal-legacy"))
    requests: list[ProposalGenerationRequest] = []

    def generate(request: ProposalGenerationRequest) -> ProposalAgentResult:
        requests.append(request)
        return expected

    monkeypatch.setattr(agent, "generate", generate)
    assert agent.propose(_context(), "Investigate.", "proposal-legacy", BASE_TIME) == expected
    assert len(requests) == 1
    assert requests[0].mode == "INITIAL"
    assert requests[0].objective == ""


def test_initial_prompt_includes_effective_objective_and_keeps_intentional_blank() -> None:
    nonblank = build_proposal_prompt(_request(objective="Focus on the transfer concern."))
    blank = build_proposal_prompt(_request(objective=""))

    assert "Focus on the transfer concern." in nonblank
    assert "Effective investigation objective (may be intentionally blank):\n\n\nInvestigation request" in blank
    assert "Investigate the reported suspicious activity" not in blank


def test_prompt_requires_analytical_discipline_and_uses_governed_context_only() -> None:
    context = _context()
    prompt = build_proposal_prompt(_request())

    for text in (
        context.investigation_request,
        context.customer_support_statement,
        context.prior_analyst_note,
        "plausible competing explanations",
        "discriminate among plausible explanations",
        "not established facts or findings",
        "neither authorized nor executed",
    ):
        assert text in prompt
    for dataset in context.datasets:
        assert dataset.dataset_name in prompt
        assert str(dataset.row_count) in prompt
        assert ", ".join(dataset.field_names) in prompt


def test_structured_rows_and_evaluator_content_cannot_enter_prompt(tmp_path: Path) -> None:
    package = export_development_investigation_package(tmp_path)
    marker = "UNIQUE-PROPOSAL-PROMPT-ROW-MARKER"
    entity_file = package / "investigator" / "data" / "visible_entities.csv"
    with entity_file.open("a", encoding="utf-8", newline="") as csv_file:
        csv.writer(csv_file).writerow((marker, "account"))
    evaluator_marker = "UNIQUE-EVALUATOR-ONLY-MARKER"
    (package / "evaluator_only" / "private.txt").write_text(evaluator_marker, encoding="utf-8")

    prompt = build_proposal_prompt(
        ProposalGenerationRequest(
            load_investigator_package(package), "", "proposal-002", BASE_TIME,
            "INITIAL", investigator_instruction="Investigate the reported concern.",
        )
    )

    assert marker not in prompt
    assert evaluator_marker not in prompt
    assert "ground_truth.csv" not in prompt


def test_modify_prompt_receives_current_direction_prior_proposal_and_instruction() -> None:
    prompt = build_proposal_prompt(_request(mode="MODIFY"))
    assert "The activity may be coordinated." in prompt
    assert "Review visible events." in prompt
    assert "Focus on events before relationships." in prompt


def test_decline_redirect_prompt_uses_guidance_only_when_present() -> None:
    with_guidance = build_proposal_prompt(_request(mode="DECLINE_REDIRECT", guidance="Review relationship evidence instead."))
    without_guidance = build_proposal_prompt(_request(mode="DECLINE_REDIRECT"))

    assert "Persisted decline guidance:\nReview relationship evidence instead." in with_guidance
    assert "declined without additional guidance" in without_guidance
    assert "Persisted decline guidance" not in without_guidance


def test_direction_aware_request_rejects_invalid_mode_specific_inputs() -> None:
    with pytest.raises(ValueError, match="MODIFY requires"):
        ProposalGenerationRequest(_context(), "", "proposal-002", BASE_TIME, "MODIFY")
    with pytest.raises(ValueError, match="DECLINE_REDIRECT must"):
        ProposalGenerationRequest(
            _context(), "", "proposal-002", BASE_TIME, "DECLINE_REDIRECT",
            investigator_instruction="not valid", current_direction=_direction(), source_proposal=_proposal(),
        )
    with pytest.raises(ValueError, match="MODIFY must not"):
        ProposalGenerationRequest(
            _context(), "", "proposal-002", BASE_TIME, "MODIFY",
            current_direction=_direction(), source_proposal=_proposal(),
            investigator_instruction="Modify it.", decline_guidance="Not applicable.",
        )


def test_initial_request_accepts_context_and_objective_without_instruction() -> None:
    request = ProposalGenerationRequest(
        _context(), "", "proposal-002", BASE_TIME, "INITIAL"
    )

    prompt = build_proposal_prompt(request)
    assert "Investigator instruction:" not in prompt


@pytest.mark.parametrize(
    "payload",
    (
        _payload(competing_explanations=["ground truth"]),
        _payload(plan_steps=["evaluator_only/signals.csv"]),
        _payload_with_proposal_field("action", "canonical world"),
        _payload_with_proposal_field("purpose", "ground truth"),
        _payload_with_proposal_field("why_now", "evaluator_only"),
        _payload_with_proposal_field("data_to_be_used", "signals.csv"),
        _payload_with_proposal_field("expected_output", "private data"),
    ),
)
def test_private_references_in_every_model_output_field_are_rejected(payload: str) -> None:
    agent, _ = _agent(payload)
    with pytest.raises(ProposalModelError) as error:
        agent.generate(_request())
    assert error.value.category is ProposalModelFailureCategory.GENERATION_ERROR


def test_agent_has_no_persistence_or_execution_side_effects() -> None:
    agent, client = _agent(_payload())
    result = agent.generate(_request())
    assert result.proposal.status == "PROPOSED"
    assert len(client.prompts) == 1
    assert not hasattr(agent, "store")
    assert not hasattr(agent, "execute")


def test_explicit_local_model_configuration_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(ValueError, match="model"):
        ProposalOllamaConfig.from_environment()


def test_preflight_passes_only_when_exact_configured_model_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "investigation.proposal_agent.urlopen",
        lambda request, **_kwargs: (calls.append(request) or FakeOllamaReply(b'{"models": [{"name": "llama3:8b"}]}')),
    )
    client = OllamaProposalClient(_config())
    client.preflight()
    assert len(calls) == 1
    assert calls[0].full_url == "http://localhost:11434/api/tags"


def test_preflight_distinguishes_service_and_configured_model_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("investigation.proposal_agent.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("refused")))
    with pytest.raises(ProposalModelError) as service_error:
        OllamaProposalClient(_config()).preflight()
    assert service_error.value.category is ProposalModelFailureCategory.SERVICE_UNAVAILABLE

    monkeypatch.setattr("investigation.proposal_agent.urlopen", lambda *_args, **_kwargs: FakeOllamaReply(b'{"models": [{"name": "another-model"}]}'))
    with pytest.raises(ProposalModelError) as model_error:
        OllamaProposalClient(_config()).preflight()
    assert model_error.value.category is ProposalModelFailureCategory.MODEL_UNAVAILABLE


@pytest.mark.parametrize(
    "failure, expected_category",
    (
        (TimeoutError("slow"), ProposalModelFailureCategory.SERVICE_UNAVAILABLE),
        (HTTPError("http://localhost:11434/api/tags", 500, "failure", None, None), ProposalModelFailureCategory.GENERATION_ERROR),
        (b"not JSON", ProposalModelFailureCategory.GENERATION_ERROR),
        (b"[]", ProposalModelFailureCategory.GENERATION_ERROR),
    ),
)
def test_preflight_failure_categories_make_one_request_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure: object,
    expected_category: ProposalModelFailureCategory,
) -> None:
    calls: list[object] = []

    def fail_once(request: object, **_kwargs: object) -> FakeOllamaReply:
        calls.append(request)
        if isinstance(failure, BaseException):
            raise failure
        return FakeOllamaReply(failure)  # type: ignore[arg-type]

    monkeypatch.setattr("investigation.proposal_agent.urlopen", fail_once)
    with pytest.raises(ProposalModelError) as error:
        OllamaProposalClient(_config()).preflight()
    assert error.value.category is expected_category
    assert len(calls) == 1


def test_generation_uses_exact_configured_model_and_never_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[object] = []
    monkeypatch.setattr(
        "investigation.proposal_agent.urlopen",
        lambda request, **_kwargs: (requests.append(request) or FakeOllamaReply(b'{"response": "{}"}')),
    )
    client = OllamaProposalClient(_config())
    assert client.generate("prompt") == "{}"
    assert len(requests) == 1
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body["model"] == "llama3:8b"
    assert requests[0].full_url == "http://localhost:11434/api/generate"


def test_task_five_can_explicitly_preflight_then_make_one_generation_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []
    replies = iter((
        FakeOllamaReply(b'{"models": [{"name": "llama3:8b"}]}'),
        FakeOllamaReply(b'{"response": "{}"}'),
    ))

    def reply(request: object, **_kwargs: object) -> FakeOllamaReply:
        requests.append(request)
        return next(replies)

    monkeypatch.setattr("investigation.proposal_agent.urlopen", reply)
    client = OllamaProposalClient(_config())
    client.preflight()
    assert client.generate("prompt") == "{}"
    assert [request.full_url for request in requests] == [
        "http://localhost:11434/api/tags",
        "http://localhost:11434/api/generate",
    ]


@pytest.mark.parametrize(
    "failure, expected_category",
    (
        (TimeoutError("slow"), ProposalModelFailureCategory.REQUEST_TIMEOUT),
        (URLError("refused"), ProposalModelFailureCategory.SERVICE_UNAVAILABLE),
        (b"not JSON", ProposalModelFailureCategory.GENERATION_ERROR),
        (b"[]", ProposalModelFailureCategory.GENERATION_ERROR),
    ),
)
def test_generation_failure_categories_make_one_request_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure: object,
    expected_category: ProposalModelFailureCategory,
) -> None:
    calls: list[object] = []

    def fail_once(request: object, **_kwargs: object) -> FakeOllamaReply:
        calls.append(request)
        if isinstance(failure, BaseException):
            raise failure
        return FakeOllamaReply(failure)  # type: ignore[arg-type]

    monkeypatch.setattr("investigation.proposal_agent.urlopen", fail_once)
    with pytest.raises(ProposalModelError) as error:
        OllamaProposalClient(_config()).generate("prompt")
    assert error.value.category is expected_category
    assert len(calls) == 1


def test_http_404_is_model_unavailable_without_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    def missing(request: object, **_kwargs: object) -> object:
        calls.append(request)
        raise HTTPError("http://localhost:11434/api/generate", 404, "missing", None, None)

    monkeypatch.setattr("investigation.proposal_agent.urlopen", missing)
    with pytest.raises(ProposalModelError) as error:
        OllamaProposalClient(_config()).generate("prompt")
    assert error.value.category is ProposalModelFailureCategory.MODEL_UNAVAILABLE
    assert len(calls) == 1


def test_http_generation_error_is_not_misclassified_as_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*_args: object, **_kwargs: object) -> object:
        raise HTTPError("http://localhost:11434/api/generate", 500, "failure", None, None)

    monkeypatch.setattr("investigation.proposal_agent.urlopen", failed)
    with pytest.raises(ProposalModelError) as error:
        OllamaProposalClient(_config()).generate("prompt")
    assert error.value.category is ProposalModelFailureCategory.GENERATION_ERROR
