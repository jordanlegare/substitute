import json
from pathlib import Path

import pytest

from ald_media_controller import (
    ExitCode,
    compile_recipe,
    load_recipe,
    main,
    validate_recipe,
)


PRODUCT_RECIPES = (
    ("cmos_high_k_gate_sim.json", "CMOS high-k gate dielectric surrogate", 3),
    ("dram_mim_capacitor_sim.json", "DRAM MIM capacitor dielectric surrogate", 5),
    ("nand_3d_liner_sim.json", "3D NAND conformal liner surrogate", 7),
)


@pytest.mark.parametrize("filename,product_family,regions", PRODUCT_RECIPES)
def test_checked_in_product_surrogate_recipe_validates_compiles_and_simulates(
    tmp_path, filename, product_family, regions
):
    recipe_path = Path("recipes/products") / filename
    output = tmp_path / recipe_path.stem

    assert recipe_path.is_file()
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["product_family"] == product_family
    assert payload["metadata"]["physical_fabrication_mapping"] is False
    assert payload["precursors"] == {
        "A": {"label": "A-sim"},
        "B": {"label": "B-sim"},
    }
    assert payload["surface"]["regions"] == regions
    assert len(payload["surface"]["transport_factors"]) == regions

    recipe = validate_recipe(load_recipe(recipe_path))
    compiled = compile_recipe(recipe)
    assert compiled.packets
    assert len(compiled.root_hash) == 32

    assert main(["validate", str(recipe_path)]) == ExitCode.OK
    assert main(
        ["simulate", str(recipe_path), "--seed", "42", "--output", str(output)]
    ) == ExitCode.OK
    assert {path.name for path in output.iterdir()} == {
        "audit.jsonl",
        "cycles.csv",
        "surface-final.json",
    }
