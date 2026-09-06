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
                "provenance": [{"source": "cod", "source_id": "1000001", "evidence": "crystallographic_identity"}],
                "process_evidence": {"status": "identity-only", "recipe_ids": [], "recipe_paths": []},
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
                "provenance": [{"source": "cod", "source_id": "1000002", "evidence": "crystallographic_identity"}],
                "process_evidence": {"status": "identity-only", "recipe_ids": [], "recipe_paths": []},
            },
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_bytes(materials.canonical_json_bytes(payload))
    entries = materials.load_material_catalog(path)
    assert materials.resolve_material(entries, "HfO2")["name"] == "hafnium dioxide"
    assert materials.resolve_material(entries, "hafnia")["formula"] == "HfO2"
    assert [row["formula"] for row in materials.search_materials(entries, "oxide")] == ["Al2O3", "HfO2"]
    assert [row["formula"] for row in materials.filter_materials(entries, material_class="oxide", element="Hf")] == ["HfO2"]
    report = materials.material_report(entries)
    assert report["counted_non_elemental_reduced_formula_count"] == 2
    assert report["material_classes"]["oxide"] == 2


def _builder_fixture_records():
    return [
        {
            "source": "cod",
            "source_id": "9000001",
            "formula": "HfO2",
            "name": "hafnium dioxide",
            "space_group": "P21/c",
        },
        {
            "source": "cod",
            "source_id": "9000002",
            "formula": "HfO2",
            "name": "hafnium oxide",
            "space_group": "P42/nmc",
        },
        {
            "source": "cod",
            "source_id": "9000003",
            "formula": "Al2O3",
            "name": "aluminum oxide",
            "space_group": "R-3c",
        },
        {
            "source": "cod",
            "source_id": "9000004",
            "formula": "ZnS",
            "name": "zinc sulfide",
            "space_group": "F-43m",
        },
        {
            "source": "cod",
            "source_id": "9000005",
            "formula": "TiN",
            "name": "titanium nitride",
            "space_group": "Fm-3m",
        },
        {
            "source": "cod",
            "source_id": "9000006",
            "formula": "Fe",
            "name": "iron",
            "space_group": "Im-3m",
        },
        {
            "source": "cod",
            "source_id": "9000007",
            "formula": "CoSx",
            "name": "cobalt sulfide",
        },
        {
            "source": "",
            "source_id": "",
            "formula": "SiO2",
            "name": "silicon dioxide",
        },
    ]


def test_builder_merges_duplicate_formulas_excludes_invalids_and_selects_exact_target():
    from tools import build_material_catalog as builder

    catalog, manifest, audit = builder.build_material_artifacts(
        _builder_fixture_records(),
        [],
        [],
        target_count=4,
        manifest_template={"retrieved_at": "2026-09-05T00:00:00Z"},
    )

    counted = [entry for entry in catalog["entries"] if entry["counted"]]
    assert catalog["catalog_schema"] == "ald-material-catalog/1"
    assert catalog["counted_non_elemental_reduced_formula_count"] == 4
    assert len(counted) == 4
    assert {entry["reduced_formula"] for entry in counted} == {"Al2O3", "HfO2", "SZn", "NTi"}
    hfo2 = next(entry for entry in counted if entry["reduced_formula"] == "HfO2")
    assert hfo2["identifiers"]["cod_ids"] == ["9000001", "9000002"]
    assert len(hfo2["phases"]) == 2
    assert audit["duplicate_reduced_formula_collapses"] == 1
    assert audit["elemental_exclusions"] == 1
    assert audit["variable_or_ambiguous_formula_exclusions"] == 1
    assert audit["provenance_failures"] == 1
    assert audit["counted_catalog_size"] == 4
    assert manifest["target_count"] == 4


def test_builder_is_byte_deterministic_for_same_inputs():
    from tools import build_material_catalog as builder

    args = (
        _builder_fixture_records(),
        [],
        [],
    )
    first = builder.build_material_artifacts(
        *args,
        target_count=4,
        manifest_template={"retrieved_at": "2026-09-05T00:00:00Z"},
    )
    second = builder.build_material_artifacts(
        *args,
        target_count=4,
        manifest_template={"retrieved_at": "2026-09-05T00:00:00Z"},
    )
    assert [materials.canonical_json_bytes(value) for value in first] == [
        materials.canonical_json_bytes(value) for value in second
    ]


def test_builder_rejects_target_larger_than_eligible_pool():
    from tools import build_material_catalog as builder

    with pytest.raises(ValueError, match="eligible"):
        builder.build_material_artifacts(
            _builder_fixture_records(),
            [],
            [],
            target_count=5,
            manifest_template={"retrieved_at": "2026-09-05T00:00:00Z"},
        )


def test_pyproject_packages_material_module():
    assert '"ald_materials"' in Path("pyproject.toml").read_text(encoding="utf-8")
