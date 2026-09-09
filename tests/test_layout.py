from pathlib import Path

from generator.layout import case_output_paths


def test_case_output_separates_truth_from_investigator_view() -> None:
    paths = case_output_paths(Path("output"), "case-001")

    assert paths.ground_truth_directory == Path("output/case-001/ground_truth")
    assert paths.investigator_view_directory == Path(
        "output/case-001/investigator_view"
    )


def test_case_output_rejects_path_like_case_ids() -> None:
    try:
        case_output_paths(Path("output"), "../case-001")
    except ValueError:
        pass
    else:
        raise AssertionError("path-like case IDs must be rejected")
