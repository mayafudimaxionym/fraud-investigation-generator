from generator.artifacts.manifest import InvestigatorViewManifest


def test_investigator_view_rejects_duplicate_artifact_ids() -> None:
    try:
        InvestigatorViewManifest(
            visible_entity_ids=("account-001",),
            visible_event_ids=("event-001",),
            artifact_ids=("email-001", "email-001"),
        )
    except ValueError as error:
        assert "artifact_ids" in str(error)
    else:
        raise AssertionError("duplicate visible artifact identifiers must be rejected")


def test_investigator_view_rejects_duplicate_visible_relationship_ids() -> None:
    try:
        InvestigatorViewManifest(
            visible_entity_ids=(),
            visible_event_ids=(),
            artifact_ids=(),
            visible_relationship_ids=("relationship-001", "relationship-001"),
        )
    except ValueError as error:
        assert "visible_relationship_ids" in str(error)
    else:
        raise AssertionError("duplicate visible relationship IDs must be rejected")
