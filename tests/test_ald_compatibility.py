from __future__ import annotations

import json
from pathlib import Path

import pytest

import ald_compatibility as compat


MODEL = {
    "schema": "ald-compatibility-model/1",
    "precursor_weights": {
        "exact_process": 0.25,
        "direct_literature": 0.20,
        "external_thermochemistry": 0.15,
        "role_complementarity": 0.10,
        "surface_sequence": 0.10,
        "physical_property": 0.10,
        "chemistry_analogue": 0.10,
    },
    "material_weights": {
        "direct_stack": 0.30,
        "direct_literature": 0.20,
        "external_thermodynamics": 0.20,
        "shared_precursors": 0.10,
        "family_analogue": 0.10,
        "surface_interface": 0.10,
    },
    "coverage_unknown_below": 0.15,
    "verdict_thresholds": {"low_support": 45.0, "plausible": 60.0, "supported": 75.0},
    "candidate_weights": {"harmonic": 0.40, "minimum": 0.20, "coverage": 0.15, "roles": 0.15, "known": 0.10},
    "beam_width": 50,
    "default_top": 20,
    "status_reliability": {
        "established": 1.0,
        "literature-grounded": 0.95,
        "literature-grounded-surrogate": 0.90,
        "conceptual-multicomponent-surrogate": 0.60,
        "default": 0.50,
    },
    "role_keywords": {
        "OXIDANT": ["oxygen co-reactant", "oxidant", "ozone", "water"],
        "REDUCTANT": ["reducing co-reactant", "reductant", "hydrogen"],
        "CHALCOGEN_REACTANT": ["sulfur co-reactant", "selenium co-reactant", "tellurium co-reactant"],
        "NITROGEN_REACTANT": ["nitrogen co-reactant", "ammonia", "nitrogen reactant"],
        "HALOGEN_REACTANT": ["fluorine co-reactant", "halogen co-reactant"],
        "CARBON_REACTANT": ["carbon co-reactant"],
        "OTHER_REACTANT": ["co-reactant", "reactant"],
        "SOURCE": ["source"],
    },
}


def entry(
    recipe_id: str,
    precursors: list[dict[str, str]],
    *,
    target_formula: str = "Al2O3",
    target_material: str = "aluminum oxide",
    category: str = "oxides",
    chemistry_family: str = "binary-oxide",
    chemistry_status: str = "established",
    source_references: list[dict[str, str]] | None = None,
    exposure_signature: list[str] | None = None,
) -> dict[str, object]:
    return {
        "recipe_id": recipe_id,
        "path": f"recipes/{recipe_id}.json",
        "precursor_count": len(precursors),
        "precursors": precursors,
        "target_formula": target_formula,
        "target_material": target_material,
        "category": category,
        "chemistry_family": chemistry_family,
        "chemistry_status": chemistry_status,
        "product_family": "test material",
        "source_references": source_references or [],
        "exposure_signature": exposure_signature or [p["id"] for p in precursors],
    }


def test_formula_and_name_normalization_are_deterministic():
    assert compat.normalize_formula("  Hf Cl4 \n") == "HfCl4"
    assert compat.normalize_name("  Hafnium   Tetrachloride ") == "hafnium tetrachloride"
    assert compat.normalize_name("Ｗａｔｅｒ") == "water"


def test_duplicate_precursor_appearances_collapse_to_one_entity():
    entries = [
        entry(
            "r1",
            [{"id": "A", "name": "water", "formula": "H2O", "role": "oxygen co-reactant"},
             {"id": "B", "name": "trimethylaluminum", "formula": "Al(CH3)3", "role": "aluminum source"}],
        ),
        entry(
            "r2",
            [{"id": "A", "name": "Water", "formula": " H2O ", "role": "oxidant"},
             {"id": "B", "name": "hafnium tetrachloride", "formula": "HfCl4", "role": "hafnium source"}],
            target_formula="HfO2",
            target_material="hafnium oxide",
        ),
    ]

    entities = compat.build_precursor_entities(entries, MODEL)
    water = [item for item in entities if item["formula"] == "H2O"]

    assert len(water) == 1
    assert water[0]["roles"] == ["OXIDANT"]
    assert water[0]["recipe_ids"] == ["r1", "r2"]
    assert entities == compat.build_precursor_entities(entries, MODEL)


def test_precursor_entity_ids_are_stable_and_formula_first():
    entries = [
        entry(
            "r1",
            [{"id": "A", "name": "water", "formula": "H2O", "role": "oxygen co-reactant"},
             {"id": "B", "name": "trimethylaluminum", "formula": "Al(CH3)3", "role": "aluminum source"}],
        )
    ]
    first = compat.build_precursor_entities(entries, MODEL)
    second = compat.build_precursor_entities(list(reversed(entries)), MODEL)
    assert first == second
    assert all(item["id"].startswith("p-") for item in first)


def test_role_classifier_is_coarse_and_deterministic():
    assert compat.classify_role("hafnium source", MODEL) == "SOURCE"
    assert compat.classify_role("oxygen co-reactant", MODEL) == "OXIDANT"
    assert compat.classify_role("reducing co-reactant", MODEL) == "REDUCTANT"
    assert compat.classify_role("mystery ligand", MODEL) == "OTHER"


def test_material_builder_separates_base_and_composite_targets():
    entries = [
        entry("al", [], target_formula="Al2O3", target_material="aluminum oxide"),
        entry("hf", [], target_formula="HfO2", target_material="hafnium oxide"),
        entry(
            "stack",
            [],
            target_formula="HfO2/Al2O3",
            target_material="hafnium oxide/aluminum oxide nanolaminate",
            chemistry_family="nanolaminate-supercycle-surrogate",
        ),
    ]

    result = compat.build_material_entities(entries)
    assert [item["formula"] for item in result["base"]] == ["Al2O3", "HfO2"]
    assert result["composites"][0]["components"] == ["HfO2", "Al2O3"]


def test_load_model_rejects_unknown_schema(tmp_path: Path):
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="model schema"):
        compat.load_model(path)


def test_load_evidence_rejects_out_of_range_values(tmp_path: Path):
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema": "ald-compatibility-evidence/1",
                "records": [
                    {
                        "graph": "precursor",
                        "a": "H2O",
                        "b": "HfCl4",
                        "family": "external_thermochemistry",
                        "value": 2.0,
                        "reliability": 0.8,
                        "source": {"type": "test", "identifier": "x"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="value"):
        compat.load_evidence_overrides(path)
