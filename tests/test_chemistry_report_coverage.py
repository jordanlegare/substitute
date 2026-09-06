from __future__ import annotations

import json
from pathlib import Path

import ald_master
import ald_materials as materials


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_chemistry_report_does_not_count_formula_only_material_match_as_recipe_linked(
    tmp_path: Path, capsys
):
    formula = "HfO2"
    reduced = materials.reduce_formula(formula)[0]
    material_id = materials.material_id(reduced)

    recipe_catalog = {
        "catalog_schema": "ald-compound-catalog/1",
        "entry_count": 1,
        "entries": [
            {
                "category": "oxides",
                "chemistry_family": "binary-oxide",
                "chemistry_status": "established",
                "path": "recipes/compounds/oxides/hfo2_example.json",
                "precursor_count": 2,
                "precursors": [
                    {
                        "formula": "HfCl4",
                        "id": "A",
                        "name": "hafnium tetrachloride",
                        "role": "hafnium source",
                    },
                    {
                        "formula": "H2O",
                        "id": "B",
                        "name": "water",
                        "role": "oxygen co-reactant",
                    },
                ],
                "product_family": "dielectric oxide",
                "recipe_id": "hist-hfo2-example",
                "source_references": [
                    {"type": "doi", "identifier": "10.1234/historical"}
                ],
                "target_formula": formula,
                "target_material": "hafnium dioxide",
                "exposure_signature": ["A", "B"],
            }
        ],
    }
    material_catalog = {
        "catalog_schema": materials.CATALOG_SCHEMA,
        "counted_non_elemental_reduced_formula_count": 1,
        "entries": [
            {
                "material_id": material_id,
                "name": "hafnium dioxide",
                "formula": formula,
                "reduced_formula": reduced,
                "elements": ["Hf", "O"],
                "counted": True,
                "material_classes": ["oxide"],
                "aliases": [],
                "identifiers": {},
                "phases": [],
                "provenance": [],
                "process_evidence": {
                    "status": "identity-only",
                    "recipe_ids": [],
                    "recipe_paths": [],
                },
            }
        ],
    }
    evidence = {"schema": "ald-recipe-evidence/1", "records": []}

    recipes_path = _write_json(tmp_path / "recipes.json", recipe_catalog)
    materials_path = _write_json(tmp_path / "materials.json", material_catalog)
    evidence_path = _write_json(tmp_path / "evidence.json", evidence)

    result = ald_master.main(
        [
            "--catalog",
            str(recipes_path),
            "--recipe-evidence",
            str(evidence_path),
            "--materials-catalog",
            str(materials_path),
            "chemistry",
            "report",
            "--json",
        ]
    )
    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["recipe_backed_materials_in_identity_catalog"] == 0
    assert report["remaining_identity_only_materials"] == 1
