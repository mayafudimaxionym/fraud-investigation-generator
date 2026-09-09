from generator.world.relationships import CanonicalRelationship


def test_relationship_rejects_blank_source_entity_id() -> None:
    try:
        CanonicalRelationship(
            relationship_id="relationship-001",
            source_entity_id=" ",
            target_entity_id="account-001",
            relationship_type="uses_device",
        )
    except ValueError as error:
        assert "source_entity_id" in str(error)
    else:
        raise AssertionError("blank source entity IDs must be rejected")
