from generator.world.entities import CanonicalEntity


def test_entity_rejects_blank_entity_type() -> None:
    try:
        CanonicalEntity(entity_id="account-001", entity_type=" ")
    except ValueError as error:
        assert "entity_type" in str(error)
    else:
        raise AssertionError("blank entity types must be rejected")
