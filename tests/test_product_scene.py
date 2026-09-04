from pathlib import Path

import pytest

import ald_hardened_core as core
from ald_product_scene import build_product_scene


MAJORANA_RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def majorana_recipe() -> core.Recipe:
    return core.validate_recipe(core.load_recipe(MAJORANA_RECIPE))


def test_majorana_scene_preserves_reference_geometry_without_fabrication_mapping():
    scene = build_product_scene(majorana_recipe(), stage="final")

    assert scene.protocol == "ALD-PRODUCT-SCENE/1"
    assert scene.physical_fabrication_mapping is False
    assert scene.tetron.shape == "H-shaped superconducting island"
    assert scene.tetron.horizontal_nanowires == 2
    assert scene.tetron.horizontal_nanowire_length_um == 3.5
    assert scene.tetron.horizontal_nanowire_width_nm == 35.0
    assert scene.tetron.backbone_length_um == 1.0
    assert scene.tetron.backbone_width_nm == 20.0
    assert len(scene.gate_layers) == 3
    assert len(scene.quantum_dots) == 5
    assert sum(dot.shared_with_vertical_neighbor for dot in scene.quantum_dots) == 3


def test_unknown_stack_fields_remain_unspecified():
    scene = build_product_scene(majorana_recipe(), stage="reference-stack")
    layers = {layer.role: layer for layer in scene.layers}

    assert layers["substrate"].material == "GaSb"
    assert layers["substrate"].thickness_nm is None
    assert layers["bottom_barrier"].material is None
    assert layers["bottom_barrier"].thickness_nm is None
    assert layers["quantum_well_inas"].material == "InAs"
    assert layers["quantum_well_inas"].thickness_nm == 6.0
    assert layers["quantum_well_inassb"].material == "InAs0.8Sb0.2"
    assert layers["quantum_well_inassb"].thickness_nm == 2.0
    assert layers["superconductor"].material == "Pb"
    assert layers["superconductor"].thickness_nm == 10.0


def test_generic_recipe_cannot_be_rendered_as_majorana_product():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))

    with pytest.raises(core.RecipeError, match="public_device_reference"):
        build_product_scene(recipe, stage="final")
