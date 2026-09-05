from pathlib import Path

import pytest

import ald_hardened_core as core
from ald_product_scene import (
    build_product_document,
    build_product_scene,
    canonical_product_json,
    parse_product_json,
)
from ald_product_svg import render_final_svg, render_stack_svg, render_top_svg


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


def test_svg_views_are_deterministic_and_structurally_distinct():
    scene = build_product_scene(majorana_recipe(), stage="final")

    top_a = render_top_svg(scene)
    top_b = render_top_svg(scene)
    stack = render_stack_svg(scene)
    final = render_final_svg(scene)

    assert top_a == top_b
    assert top_a.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b"H-shaped superconducting island" in top_a
    assert b"QD1" in top_a and b"QD5" in top_a
    assert b"InAs0.8Sb0.2" in stack
    assert b"Pb" in stack
    assert b"UNSPECIFIED" in stack
    assert b"physical_fabrication_mapping=false" in final
    assert top_a != stack
    assert final != stack


def test_product_json_round_trips_canonically():
    scene = build_product_scene(majorana_recipe(), stage="final")
    document = build_product_document(
        scene,
        recipe_sha256=b"\x11" * 32,
        root_hash=b"\x22" * 32,
        view_sha256={
            "top": "33" * 32,
            "stack": "44" * 32,
            "final": "55" * 32,
        },
    )

    raw = canonical_product_json(document)
    parsed = parse_product_json(raw)

    assert raw.endswith(b"\n")
    assert b'"physical_fabrication_mapping":false' in raw
    assert b'"packet_root_hash":"' + (b"22" * 32) + b'"' in raw
    assert parsed.scene == scene
    assert parsed.recipe_sha256 == b"\x11" * 32
    assert parsed.root_hash == b"\x22" * 32
    assert dict(parsed.view_sha256) == {
        "final": "55" * 32,
        "stack": "44" * 32,
        "top": "33" * 32,
    }
    assert canonical_product_json(parsed) == raw


def test_product_json_rejects_true_fabrication_mapping():
    scene = build_product_scene(majorana_recipe(), stage="final")
    document = build_product_document(
        scene,
        recipe_sha256=b"\x11" * 32,
        root_hash=b"\x22" * 32,
        view_sha256={"top": "33" * 32, "stack": "44" * 32, "final": "55" * 32},
    )
    raw = canonical_product_json(document)
    tampered = raw.replace(
        b'"physical_fabrication_mapping":false',
        b'"physical_fabrication_mapping":true',
    )

    with pytest.raises(core.RecipeError, match="physical_fabrication_mapping"):
        parse_product_json(tampered)
