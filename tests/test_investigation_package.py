from pathlib import Path

from generator.dev.inspect_case import build_development_case
from generator.dev.package_case import (
    build_investigator_text_fixtures,
    export_development_investigation_package,
)


def test_investigation_package_has_deterministic_separated_layout(tmp_path: Path) -> None:
    first = export_development_investigation_package(tmp_path / "first")
    second = export_development_investigation_package(tmp_path / "second")
    investigator_files = {
        Path("data/visible_entities.csv"),
        Path("data/visible_relationships.csv"),
        Path("data/visible_events.csv"),
        Path("context/investigation_request.txt"),
        Path("context/customer_support.txt"),
        Path("context/prior_analyst_note.txt"),
    }
    evaluator_files = {
        Path("entities.csv"),
        Path("relationships.csv"),
        Path("events.csv"),
        Path("signals.csv"),
        Path("campaigns.csv"),
        Path("ground_truth.csv"),
    }

    assert {
        path.relative_to(first / "investigator")
        for path in (first / "investigator").rglob("*")
        if path.is_file()
    } == investigator_files
    assert {
        path.relative_to(first / "evaluator_only")
        for path in (first / "evaluator_only").rglob("*.csv")
    } == evaluator_files
    assert not (first / "investigator" / "evaluator_only").exists()
    for relative_path in investigator_files:
        assert (first / "investigator" / relative_path).read_bytes() == (
            second / "investigator" / relative_path
        ).read_bytes()
    for relative_path in evaluator_files:
        assert (first / "evaluator_only" / relative_path).read_bytes() == (
            second / "evaluator_only" / relative_path
        ).read_bytes()


def test_investigation_package_removes_stale_legacy_export_content(
    tmp_path: Path,
) -> None:
    stale_case_directory = tmp_path / "development-case-42"
    stale_artifact = stale_case_directory / "investigator_view" / "artifacts.csv"
    stale_artifact.parent.mkdir(parents=True)
    stale_artifact.write_text("obsolete artifact", encoding="utf-8")
    (stale_case_directory / "internal").mkdir()
    (stale_case_directory / "obsolete.txt").write_text("obsolete", encoding="utf-8")

    case_directory = export_development_investigation_package(tmp_path)

    assert {path.name for path in case_directory.iterdir()} == {
        "investigator",
        "evaluator_only",
    }
    assert not (case_directory / "internal").exists()
    assert not (case_directory / "investigator_view").exists()
    assert not stale_artifact.exists()


def test_investigator_package_contains_no_private_truth_or_evaluator_files(
    tmp_path: Path,
) -> None:
    case = build_development_case()
    case_directory = export_development_investigation_package(tmp_path)
    investigator_directory = case_directory / "investigator"
    visible_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in investigator_directory.rglob("*")
        if path.is_file()
    )
    private_identifiers = (
        set(case.ground_truth.campaign_ids)
        | set(case.ground_truth.causal_signal_ids)
        | set(case.ground_truth.red_herring_ids)
    )

    for private_field in (
        "campaign_ids",
        "causal_signal_ids",
        "red_herring_ids",
        "correct_hypothesis",
        "ground_truth",
        "signal_id",
    ):
        assert private_field not in visible_content
    assert case.ground_truth.correct_hypothesis not in visible_content
    assert all(identifier not in visible_content for identifier in private_identifiers)
    assert not any(
        path.name in {"campaigns.csv", "signals.csv", "ground_truth.csv"}
        for path in investigator_directory.rglob("*")
        if path.is_file()
    )
    assert (case_directory / "evaluator_only" / "ground_truth.csv").is_file()


def test_text_fixtures_are_neutral_and_contain_only_a_plausible_wrong_path() -> None:
    case = build_development_case()
    fixtures = build_investigator_text_fixtures(case)
    all_text = "\n".join(fixtures.values()).lower()

    assert set(fixtures) == {
        "investigation_request.txt",
        "customer_support.txt",
        "prior_analyst_note.txt",
    }
    for forbidden_phrase in (
        "account takeover",
        "fraud",
        "fraudulent",
        "campaign",
        "causal signal",
        "red herring",
        "ground truth",
        "correct hypothesis",
    ):
        assert forbidden_phrase not in all_text
    assert "strongest supported explanation" in fixtures["investigation_request.txt"]
    assert "plausible alternatives" in fixtures["investigation_request.txt"]
    assert "cannot remember" in fixtures["customer_support.txt"]
    assert "may reflect ordinary shared access" in fixtures["prior_analyst_note.txt"]
    assert case.ground_truth.correct_hypothesis not in all_text
