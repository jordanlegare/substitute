from pathlib import Path

import ald_hardened_core as core


RECIPE = Path("recipes/compounds/research/acceptance_three_precursor.json")


def test_hardened_preflight_accepts_exact_multi_precursor_compilation():
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    compiled = core.compile_recipe(recipe)
    controller = core.SimulatedALDController()

    controller._start_run(compiled, 42)
    trust_globals = controller._start_run.__globals__
    assert trust_globals["_recipe_shape_is_trusted"](recipe)
    assert all(controller._is_well_formed_hashed_packet(item) for item in compiled.packets)
    assert controller._verify_compiled_integrity(compiled) == compiled.packets
