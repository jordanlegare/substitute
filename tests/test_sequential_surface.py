import pytest

from ald_sequential_surface import (
    SequentialSurfaceConfig,
    SequentialSurfaceError,
    SequentialSurfaceModel,
)


def config(signature=("A", "B", "C")):
    return SequentialSurfaceConfig(
        model_version="site-sequential/1",
        regions=2,
        sites_per_region=1000,
        transport_factors=(1.0, 0.8),
        blocked_fraction=0.01,
        defect_fraction=0.005,
        reaction_factors=tuple(1.0 for _ in signature),
        growth_nm_per_completion_fraction=0.1,
        purge_half_life_ms=800,
        precursor_ids=tuple(dict.fromkeys(signature)),
        exposure_signature=signature,
    )


def test_three_step_sequence_is_deterministic_and_conserves_sites():
    root = bytes.fromhex("11" * 32)
    first = SequentialSurfaceModel(config(), root, 42)
    second = SequentialSurfaceModel(config(), root, 42)
    for model in (first, second):
        model.expose_step(1, 0, "A", 0.5)
        model.purge(2000)
        model.expose_step(1, 1, "B", 0.4)
        model.purge(2000)
        model.expose_step(1, 2, "C", 0.3)
        model.purge(2000)
    assert first.snapshot() == second.snapshot()
    assert first.snapshot().completed_depositions > 0
    assert all(
        sum(region.state_counts) + region.blocked + region.defects == 1000
        for region in first.snapshot().regions
    )


def test_only_current_position_can_advance():
    model = SequentialSurfaceModel(config(), bytes.fromhex("12" * 32), 42)
    with pytest.raises(SequentialSurfaceError, match="step order"):
        model.expose_step(1, 1, "B", 0.5)


def test_repeated_precursor_positions_use_distinct_rng_domains():
    model = SequentialSurfaceModel(config(("A", "B", "A")), bytes.fromhex("22" * 32), 42)
    first = model._reaction_rng_material(1, 0, "A", 0, "reaction")
    third = model._reaction_rng_material(1, 2, "A", 0, "reaction")
    assert first != third


def test_residual_purge_decays_every_precursor_and_excludes_next_precursor():
    model = SequentialSurfaceModel(config(), bytes.fromhex("33" * 32), 42)
    model.expose_step(1, 0, "A", 0.5)
    before = model.snapshot().residuals["A"]
    model.purge(800)
    after = model.snapshot().residuals["A"]
    assert after == pytest.approx(before / 2.0)
    assert model.max_incompatible_residual("A") == 0.0
    assert model.max_incompatible_residual("B") > 0.0


def test_config_rejects_reaction_factor_length_mismatch():
    with pytest.raises(SequentialSurfaceError, match="reaction_factors"):
        SequentialSurfaceConfig(
            model_version="site-sequential/1",
            regions=1,
            sites_per_region=1000,
            transport_factors=(1.0,),
            blocked_fraction=0.0,
            defect_fraction=0.0,
            reaction_factors=(1.0, 1.0),
            growth_nm_per_completion_fraction=0.1,
            purge_half_life_ms=800,
            precursor_ids=("A", "B", "C"),
            exposure_signature=("A", "B", "C"),
        )
