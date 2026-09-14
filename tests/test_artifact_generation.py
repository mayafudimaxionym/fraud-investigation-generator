import json

from generator.artifacts.context import (
    ArtifactTask,
    build_artifact_generation_request,
    build_investigator_artifact_context,
)
from generator.artifacts.contracts import ArtifactGenerationResponse
from generator.artifacts.contracts import parse_artifact_generation_response
from generator.artifacts.ollama import build_artifact_prompt
from generator.artifacts.orchestration import (
    attach_investigator_artifacts,
    generate_artifacts,
)
from generator.artifacts.validation import validate_artifact_response
from generator.dev.generate_artifacts import build_development_artifact_tasks
from generator.dev.inspect_case import build_development_case
from generator.validation.case import validate_case


class FakeArtifactClient:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        interpretation = (
            "This may reflect a routine explanation."
            if request.mode == "interpretive"
            else None
        )
        return ArtifactGenerationResponse(
            tuple(assertion.assertion_id for assertion in request.assertions),
            interpretation,
        )


def _context_and_tasks():
    case = build_development_case()
    context = build_investigator_artifact_context(
        case.scenario,
        case.world,
        case.investigator_view,
        operational_framing="Review supplied observations only.",
    )
    return case, context, build_development_artifact_tasks()


def test_assertions_are_deterministic_and_derived_only_from_visible_evidence() -> None:
    case, context, _ = _context_and_tasks()
    repeat = build_investigator_artifact_context(
        case.scenario, case.world, case.investigator_view
    )
    visible_ids = (
        set(case.investigator_view.visible_entity_ids)
        | set(case.investigator_view.visible_relationship_ids)
        | set(case.investigator_view.visible_event_ids)
    )
    serialized = json.dumps([assertion.to_dict() for assertion in context.assertions])

    assert context.assertions == repeat.assertions
    assert all(set(assertion.evidence_ids) <= visible_ids for assertion in context.assertions)
    assert "campaign-" not in serialized
    assert "signal-" not in serialized
    assert case.ground_truth.correct_hypothesis not in serialized


def test_request_uses_only_task_assertions_and_their_explicit_evidence_closure() -> None:
    case, context, tasks = _context_and_tasks()
    task = tasks[3]
    request = build_artifact_generation_request(context, task)
    assertions = {assertion.assertion_id: assertion for assertion in context.assertions}
    expected_assertions = tuple(assertions[identifier] for identifier in task.assertion_ids)
    expected_evidence = tuple(
        dict.fromkeys(
            identifier
            for assertion in expected_assertions
            for identifier in assertion.evidence_ids
        )
    )

    assert request.assertions == expected_assertions
    assert request.allowed_canonical_ids == expected_evidence
    arbitrary_visible_id = next(
        identifier
        for identifier in case.investigator_view.visible_entity_ids
        if identifier not in request.allowed_canonical_ids
    )
    assert arbitrary_visible_id not in request.allowed_canonical_ids


def test_unknown_assertions_and_factual_interpretation_are_rejected() -> None:
    _, context, tasks = _context_and_tasks()
    request = build_artifact_generation_request(context, tasks[0])
    unknown_response = parse_artifact_generation_response(
        {"selected_assertion_ids": ["assertion-unknown", "assertion-unknown"]}
    )

    assert validate_artifact_response(
        request, unknown_response
    ) == ("artifact response selects unavailable assertion ID assertion-unknown",)
    assert validate_artifact_response(
        request,
        ArtifactGenerationResponse((), "This should not be permitted in factual mode."),
    ) == ("factual artifact response must not contain interpretation",)


def test_deduplicated_model_selection_renders_each_assertion_once() -> None:
    _, context, tasks = _context_and_tasks()
    request = build_artifact_generation_request(context, tasks[0])
    selected_assertion_id = request.assertions[0].assertion_id
    response = parse_artifact_generation_response(
        {"selected_assertion_ids": [selected_assertion_id, selected_assertion_id]}
    )
    class DuplicateSelectionClient:
        def generate(self, _request):  # type: ignore[no-untyped-def]
            return response

    artifact = generate_artifacts(
        context, (tasks[0],), DuplicateSelectionClient()
    )[0]

    assert response.selected_assertion_ids == (selected_assertion_id,)
    assert artifact.content.count(request.assertions[0].rendered_fact) == 1


def test_interpretive_response_preserves_python_factual_spine_and_private_id_protection() -> None:
    case, context, tasks = _context_and_tasks()
    request = build_artifact_generation_request(context, tasks[-1])
    response = ArtifactGenerationResponse(
        tuple(assertion.assertion_id for assertion in request.assertions),
        "This could be routine activity.",
    )
    artifacts = generate_artifacts(context, (tasks[-1],), FakeArtifactClient())

    assert validate_artifact_response(request, response) == ()
    assert all(assertion.rendered_fact in artifacts[0].content for assertion in request.assertions)
    assert "Analyst interpretation (non-authoritative):" in artifacts[0].content
    private_response = ArtifactGenerationResponse(
        (), f"See {case.ground_truth.campaign_ids[0]}."
    )
    assert "unavailable canonical ID" in validate_artifact_response(
        request, private_response
    )[0]


def test_purposes_create_distinct_request_structures_without_truth_leakage() -> None:
    case, context, tasks = _context_and_tasks()
    requests = tuple(build_artifact_generation_request(context, task) for task in tasks)
    prompt = build_artifact_prompt(requests[-1])

    assert tuple(request.purpose for request in requests) == (
        "customer_reported_concern",
        "customer_facing_notification",
        "analyst_observation_note",
        "operational_observation_summary",
        "alternative_analyst_interpretation",
    )
    assert len({request.assertions for request in requests}) == len(requests)
    assert "selected_assertion_ids" in prompt
    assert "Each selected_assertion_id may appear at most once." in prompt
    assert "Python will render all factual prose" in prompt
    assert case.ground_truth.correct_hypothesis not in prompt
    assert "campaign-" not in prompt
    assert "signal-" not in prompt


def test_fake_orchestration_and_attachment_keep_case_valid() -> None:
    case, context, tasks = _context_and_tasks()
    client = FakeArtifactClient()
    artifacts = generate_artifacts(context, tasks, client)
    attached = attach_investigator_artifacts(case, artifacts)

    assert tuple(artifact.artifact_id for artifact in artifacts) == tuple(
        task.artifact_id for task in tasks
    )
    assert tuple(request.mode for request in client.requests) == (
        "factual", "factual", "factual", "factual", "interpretive"
    )
    assert attached.world is case.world
    assert attached.ground_truth is case.ground_truth
    assert case.artifacts == ()
    assert attached.investigator_view.artifact_ids == tuple(
        task.artifact_id for task in tasks
    )
    assert validate_case(attached) == ()


def test_task_rejects_private_or_ineligible_assertion_selection() -> None:
    case, context, tasks = _context_and_tasks()
    try:
        build_artifact_generation_request(
            context,
            ArtifactTask(
                "artifact-006", "operational_note", "operational_observation_summary",
                "factual", (case.ground_truth.campaign_ids[0],),
            ),
        )
    except ValueError as error:
        assert "unavailable assertion IDs" in str(error)
    else:
        raise AssertionError("private identifiers must not be selectable as assertions")

    entity_assertion = next(
        assertion.assertion_id
        for assertion in context.assertions
        if assertion.assertion_type == "entity"
    )
    try:
        build_artifact_generation_request(
            context,
            ArtifactTask(
                "artifact-007", "operational_note", "operational_observation_summary",
                "factual", (entity_assertion,),
            ),
        )
    except ValueError as error:
        assert "not eligible" in str(error)
    else:
        raise AssertionError("purpose must constrain eligible assertions")
