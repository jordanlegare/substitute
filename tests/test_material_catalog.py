from pathlib import Path

import pytest

import ald_materials as materials


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("HfO2", "HfO2"),
        ("Al2O3", "Al2O3"),
        ("Fe2O4", "FeO2"),
        ("Ca3(PO4)2", "Ca3O8P2"),
        ("Li2FeSiO4", "FeLi2O4Si"),
    ],
)
def test_reduce_formula_is_fixed_and_deterministic(formula, expected):
    reduced, elements = materials.reduce_formula(formula)
    assert reduced == expected
    assert tuple(sorted(elements)) == elements


@pytest.mark.parametrize(
    "formula",
    ["CoSx", "TiO2-x", "A/B", "Ti0.5O", "", "Xx2O", "Ca3(PO4", "H0O"],
)
def test_reduce_formula_rejects_symbolic_ambiguous_or_invalid_formulas(formula):
    with pytest.raises(ValueError):
        materials.reduce_formula(formula)


def test_material_id_is_deterministic_and_collision_resistant_shape():
    first = materials.material_id("HfO2")
    second = materials.material_id("HfO2")
    assert first == second
    assert first.startswith("mat-hfo2-")
    assert len(first.rsplit("-", 1)[1]) == 8


def test_catalog_search_and_resolution_are_deterministic(tmp_path: Path):
    payload = {
        "catalog_schema": "ald-material-catalog/1",
        "counted_non_elemental_reduced_formula_count": 2,
        "entries": [
            {
                "material_id": materials.material_id("Al2O3"),
                "name": "aluminum oxide",
                "formula": "Al2O3",
                "reduced_formula": "Al2O3",
                "elements": ["Al", "O"],
                "counted": True,
                "material_classes": ["oxide", "dielectric"],
                "aliases": ["alumina"],
                "identifiers": {"cod_ids": ["1000001"]},
                "phases": [],
                "provenance": [
                    {
                        "source": "cod",
                        "source_id": "1000001",
                        "evidence": "crystallographic_identity",
                    }
                ],
                "process_evidence": {
                    "status": "identity-only",
                    "recipe_ids": [],
                    "recipe_paths": [],
                },
            },
            {
                "material_id": materials.material_id("HfO2"),
                "name": "hafnium dioxide",
                "formula": "HfO2",
                "reduced_formula": "HfO2",
                "elements": ["Hf", "O"],
                "counted": True,
                "material_classes": ["oxide", "dielectric"],
                "aliases": ["hafnia"],
                "identifiers": {"cod_ids": ["1000002"]},
                "phases": [],
                "provenance": [
                    {
                        "source": "cod",
                        "source_id": "1000002",
                        "evidence": "crystallographic_identity",
                    }
                ],
                "process_evidence": {
                    "status": "identity-only",
                    "recipe_ids": [],
                    "recipe_paths": [],
                },
            },
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_bytes(materials.canonical_json_bytes(payload))
    entries = materials.load_material_catalog(path)
    assert materials.resolve_material(entries, "HfO2")["name"] == "hafnium dioxide"
    assert materials.resolve_material(entries, "hafnia")["formula"] == "HfO2"
    assert [row["formula"] for row in materials.search_materials(entries, "oxide")] == [
        "Al2O3",
        "HfO2",
    ]
    assert [
        row["formula"]
        for row in materials.filter_materials(
            entries, material_class="oxide", element="Hf"
        )
    ] == ["HfO2"]
    report = materials.material_report(entries)
    assert report["counted_non_elemental_reduced_formula_count"] == 2
    assert report["material_classes"]["oxide"] == 2


def test_pyproject_packages_material_module():
    assert '"ald_materials"' in Path("pyproject.toml").read_text(encoding="utf-8")
