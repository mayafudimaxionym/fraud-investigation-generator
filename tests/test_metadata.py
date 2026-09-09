from generator.metadata import GenerationMetadata


def test_metadata_serializes_reproducibility_fields() -> None:
    metadata = GenerationMetadata(
        master_seed=427,
        generator_version="0.1.0",
        scenario_version="1",
        schema_version="1",
    )

    assert metadata.to_dict() == {
        "master_seed": 427,
        "generator_version": "0.1.0",
        "scenario_version": "1",
        "schema_version": "1",
        "artifact_model": None,
        "prompt_version": None,
    }
