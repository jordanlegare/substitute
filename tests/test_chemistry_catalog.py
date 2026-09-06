from __future__ import annotations

import ald_recipe_evidence as evidence_core
import ald_materials as materials
import ald_chemistry as chemistry


def _historical_recipe(
    recipe_id="hist-hfo2-water",
    *,
    target_formula="HfO2",
    target_material="hafnium dioxide",
    precursor="HfCl4",
    precursor_name="hafnium tetrachloride",
    chemistry_family="binary-oxide",
):
    return {
        "category": "oxides",
        "chemistry_family": chemistry_family,
        "chemistry_status": "established",
        "path": f"recipes/compounds/oxides/{recipe_id}.json",
        "precursor_count": 2,
        "precursors": [
            {"formula": precursor, "id": "A", "name": precursor_name, "role": "metal source"},
            {"formula": "H2O", "id": "B", "name": "water", "role": "oxygen co-reactant"},
        ],
        "product_family": "dielectric oxide",
        "recipe_id": recipe_id,
        "source_references": [{"type": "doi", "identifier": "10.1234/historical"}],
        "target_formula": target_formula,
        "target_material": target_material,
        "exposure_signature": ["A", "B"],
    }


def _selected_expansion_evidence():
    return evidence_core.validate_evidence_record(
        {
            "target_material": "titanium dioxide",
            "target_formula": "TiO2",
            "material_id": materials.material_id("O2Ti"),
            "process_family": "plasma-ald",
            "reactants": [
                {"label": "TiCl4", "name": "titanium tetrachloride", "formula": "TiCl4", "role": "reactant-a"},
                {"label": "O2 plasma", "role": "reactant-b"},
            ],
            "publications": [
                {
                    "type": "doi",
                    "identifier": "10.1234/tio2-direct",
                    "direct": True,
                    "title": "Plasma ALD of titanium dioxide",
                    "year": 2024,
                    "journal": "Example Journal",
                }
            ],
            "discovery_sources": ["atomiclimits", "crossref"],
            "evidence_grade": "R3",
            "selection_status": "selected",
        }
    )


def _expansion_recipe(record):
    return {
        "category": "oxides",
        "chemistry_family": "plasma-ald",
        "chemistry_status": "literature-backed-simulation-surrogate",
        "path": "recipes/compounds/oxides/tio2_expansion.json",
        "precursor_count": 2,
        "precursors": [
            {"formula": "TiCl4", "id": "A", "name": "titanium tetrachloride", "role": "reactant-a"},
            {"formula": "O2 plasma", "id": "B", "name": "O2 plasma", "role": "reactant-b"},
        ],
        "product_family": "evidence-backed material chemistry",
        "recipe_id": "cat-exp-tio2-abc123",
        "source_references": [{"type": "doi", "identifier": "10.1234/tio2-direct"}],
        "target_formula": "TiO2",
        "target_material": "titanium dioxide",
        "exposure_signature": ["A", "B"],
        "recipe_origin": "evidence-expansion",
        "evidence_record_id": record["evidence_id"],
        "process_family": "plasma-ald",
    }


def _material(formula, name):
    reduced = materials.reduce_formula(formula)[0]
    return {
        "material_id": materials.material_id(reduced),
        "name": name,
        "formula": formula,
        "reduced_formula": reduced,
        "elements": list(materials.reduce_formula(formula)[1]),
        "counted": True,
        "material_classes": [],
        "aliases": [],
        "identifiers": {},
        "phases": [],
        "provenance": [],
        "process_evidence": {"status": "identity-only", "recipe_ids": [], "recipe_paths": []},
    }


def _index():
    evidence_record = _selected_expansion_evidence()
    return chemistry.build_chemistry_index(
        [
            _historical_recipe(),
            _historical_recipe(
                "hist-hfo2-ozone",
                precursor="Hf(NMe2)4",
                precursor_name="tetrakis(dimethylamido)hafnium",
            ),
            _expansion_recipe(evidence_record),
        ],
        {"schema": evidence_core.EVIDENCE_SCHEMA, "records": [evidence_record]},
        [_material("HfO2", "hafnium dioxide"), _material("TiO2", "titanium dioxide")],
    )


def test_build_index_joins_expansion_recipe_to_selected_evidence():
    entries = _index()
    expansion = next(item for item in entries if item["origin"] == "expansion")
    assert expansion["evidence_grade"] == "R3"
    assert expansion["process_family"] == "plasma-ald"
    assert expansion["recipe_id"] == "cat-exp-tio2-abc123"
    assert expansion["reactants"][1]["label"] == "O2 plasma"
    assert expansion["sources"][0]["identifier"] == "10.1234/tio2-direct"
    assert expansion["material_id"] == materials.material_id("O2Ti")


def test_historical_recipes_are_explorable_without_retroactive_evidence_grade():
    entries = _index()
    historical = [item for item in entries if item["origin"] == "historical"]
    assert len(historical) == 2
    assert {item["evidence_grade"] for item in historical} == {"historical"}
    assert all(item["evidence_record_id"] is None for item in historical)
    assert all(item["process_family"] is None for item in historical)


def test_chemistry_projection_excludes_simulator_operating_fields():
    forbidden = {
        "dose",
        "purge_ms",
        "temperature_c",
        "pressure_pa",
        "plasma_power",
        "flow_sccm",
        "instructions",
        "limits",
    }
    for entry in _index():
        assert forbidden.isdisjoint(entry)
        for reactant in entry["reactants"]:
            assert forbidden.isdisjoint(reactant)


def test_formula_resolution_returns_all_preserved_historical_variants():
    resolved = chemistry.resolve_chemistries(_index(), "HfO2")
    assert [item["recipe_id"] for item in resolved] == ["hist-hfo2-ozone", "hist-hfo2-water"]


def test_search_ranks_exact_target_formula_before_reactant_match():
    result = chemistry.search_chemistries(_index(), "TiO2", limit=10)
    assert [item["recipe_id"] for item in result] == ["cat-exp-tio2-abc123"]
    reactant_result = chemistry.search_chemistries(_index(), "TiCl4", limit=10)
    assert {item["recipe_id"] for item in reactant_result} == {"cat-exp-tio2-abc123"}


def test_filters_compose_with_and_semantics():
    result = chemistry.filter_chemistries(
        _index(),
        process_family="plasma-ald",
        element="Ti",
        precursor="O2 plasma",
        evidence="R3",
        origin="expansion",
        limit=50,
    )
    assert [item["recipe_id"] for item in result] == ["cat-exp-tio2-abc123"]
    assert chemistry.filter_chemistries(
        _index(), process_family="thermal-ald", origin="historical", limit=50
    ) == []


def test_sources_and_report_are_provenance_focused():
    entries = _index()
    sources = chemistry.chemistry_sources(entries, "cat-exp-tio2-abc123")
    assert sources == [
        {
            "type": "doi",
            "identifier": "10.1234/tio2-direct",
            "direct": True,
            "title": "Plasma ALD of titanium dioxide",
            "year": 2024,
            "journal": "Example Journal",
        }
    ]
    report = chemistry.chemistry_report(entries, material_count=8000)
    assert report["total_executable_recipes"] == 3
    assert report["unique_recipe_backed_materials"] == 2
    assert report["historical_recipe_count"] == 2
    assert report["expansion_recipe_count"] == 1
    assert report["evidence_grades"] == {"R3": 1, "historical": 2}
    assert report["process_families"] == {"plasma-ald": 1, "unspecified": 2}
    assert report["remaining_identity_only_materials"] == 7998
