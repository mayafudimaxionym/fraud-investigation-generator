from generator.seed import derive_seed


def test_derived_seed_is_reproducible() -> None:
    assert derive_seed(427, "world") == derive_seed(427, "world")


def test_derived_seed_is_namespaced() -> None:
    assert derive_seed(427, "world") != derive_seed(427, "artifacts")
