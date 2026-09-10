from generator.artifacts.manifest import InvestigatorViewManifest
from generator.validation.investigator_view import validate_investigator_view_references
from generator.world.model import CanonicalWorld


def test_investigator_view_validation_reports_missing_visible_event() -> None:
    errors = validate_investigator_view_references(
        CanonicalWorld(entities=(), relationships=(), events=()),
        InvestigatorViewManifest((), ("event-001",), ()),
    )

    assert errors == ("investigator_view: missing visible event event-001",)


def test_investigator_view_validation_reports_missing_artifact() -> None:
    errors = validate_investigator_view_references(
        CanonicalWorld(entities=(), relationships=(), events=()),
        InvestigatorViewManifest((), (), ("email-001",)),
    )

    assert errors == ("investigator_view: missing artifact email-001",)
