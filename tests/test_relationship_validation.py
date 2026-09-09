from generator.validation.relationships import validate_relationship_references
from generator.world.entities import CanonicalEntity
from generator.world.relationships import CanonicalRelationship


def test_relationship_validation_reports_missing_source_entity() -> None:
    errors = validate_relationship_references(
        entities=(CanonicalEntity("account-001", "account"),),
        relationships=(
            CanonicalRelationship(
                "relationship-001",
                "device-001",
                "account-001",
                "uses_device",
            ),
        ),
    )

    assert errors == ("relationship-001: missing source device-001",)
