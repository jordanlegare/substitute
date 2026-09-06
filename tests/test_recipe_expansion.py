import copy
import json
from pathlib import Path

import ald_core as core
import ald_recipe_evidence as evidence_core
from tools.build_recipe_expansion import (
    build_recipe,
    expected_expansion_files,
    recipe_category,
    recipe_filename,
)


SIMULATION_NOTICE = (
    "Literature-recognition chemistry only. Executable ordering and numbers are synthetic "
    "simulator values; not a physical fabrication recipe or machine-control instruction."
)


def selected_record(
    *,
    target_material="titanium dioxide",
    target_formula="TiO2",
    process_family="thermal-ald",
    reactants=None,
    doi="10.1234/example",
):
    if reactants is None:
        reactants = [
            {"label": "TiCl4", "name": "titanium tetrachloride", "formula": "TiCl4", "role": "reactant-a"},
            {"label": "H2O", "name": "water", "formula": "H2O", "role": "reactant-b"},
        ]
    return evidence_core.validate_evidence_record(
        {
            "target_material": target_material,
            "target_formula": target_formula,
            "process_family": process_family,
            "reactants": reactants,
            "publications": [{"type": "doi", "identifier": doi, "direct": True}],
            "discovery_sources": ["atomiclimits"],
            "evidence_grade": "R2",
            "selection_status": "selected",
        }
    )


def test_build_recipe_carries_only_evidence_chemistry_and_fixed_simulator_template():
    record = selected_record()
    raw = build_recipe(record)

    assert raw["metadata"]["target_formula"] == "TiO2"
    assert raw["metadata"]["target_material"] == "titanium dioxide"
    assert raw["metadata"]["process_family"] == "thermal-ald"
    assert raw["metadata"]["recipe_origin"] == "evidence-expansion"
    assert raw["metadata"]["evidence_record_id"] == record["evidence_id"]
    assert raw["metadata"]["physical_fabrication_mapping"] is False
    assert raw["metadata"]["simulation_notice"] == SIMULATION_NOTICE
    assert raw["metadata"]["source_references"] == [
        {"type": "doi", "identifier": "10.1234/example"}
    ]
    assert raw["precursors"] == {
        "A": {"name": "titanium tetrachloride", "formula": "TiCl4", "role": "reactant-a"},
        "B": {"name": "water", "formula": "H2O", "role": "reactant-b"},
    }

    validated = core.validate_recipe(raw)
    core.compile_recipe(validated)


def test_unresolved_canonical_identity_uses_exact_source_label_without_inference():
    record = selected_record(
        reactants=[
            {"label": "Al(NiPr2)3", "role": "reactant-a"},
            {"label": "H2O", "name": "water", "formula": "H2O", "role": "reactant-b"},
        ]
    )
    raw = build_recipe(record)
    assert raw["precursors"]["A"] == {
        "name": "Al(NiPr2)3",
        "formula": "Al(NiPr2)3",
        "role": "reactant-a",
    }
    core.compile_recipe(core.validate_recipe(raw))


def test_literature_operating_data_cannot_change_synthetic_template():
    baseline = selected_record()
    comparison = copy.deepcopy(baseline)
    comparison["provenance"] = {"safe_note": "different bibliographic transport metadata"}

    one = build_recipe(baseline)
    two = build_recipe(comparison)

    for raw in (one, two):
        assert raw["initial_conditions"] == {"temperature_c": 25.0, "pressure_pa": 101325.0}
        cycle = next(item for item in raw["instructions"] if item["opcode"] == "DEPOSITION_CYCLE")
        assert cycle["arguments"]["exposures"] == [
            {"precursor": "A", "dose": 0.2, "purge_ms": 4000},
            {"precursor": "B", "dose": 0.23, "purge_ms": 4000},
        ]


def test_recipe_category_uses_process_family_and_fixed_target_composition():
    assert recipe_category(selected_record(target_formula="TiO2")) == "oxides"
    assert recipe_category(selected_record(target_formula="TiN", target_material="titanium nitride")) == "nitrides"
    assert recipe_category(selected_record(target_formula="ZnS", target_material="zinc sulfide")) == "chalcogenides"
    assert recipe_category(selected_record(target_formula="TiC", target_material="titanium carbide")) == "carbides_and_other_inorganics"
    assert recipe_category(selected_record(target_formula="LiCoO2", target_material="lithium cobalt oxide")) == "ternary_and_multicomponent"
    assert recipe_category(selected_record(target_formula="AlC2H5O3", target_material="hybrid alucone", process_family="mld")) == "molecular_layer_deposition"


def test_recipe_filename_and_recipe_id_are_deterministic_from_target_and_chemistry():
    record = selected_record()
    assert recipe_filename(record) == recipe_filename(copy.deepcopy(record))
    assert build_recipe(record)["recipe_id"] == build_recipe(copy.deepcopy(record))["recipe_id"]
    assert recipe_filename(record).endswith(".json")


def test_expected_expansion_files_emits_only_selected_r2_r3_records():
    selected = selected_record()
    rejected = copy.deepcopy(selected_record(target_formula="ZnO", target_material="zinc oxide", doi="10.1234/zno"))
    rejected["selection_status"] = "rejected"
    rejected["rejection_reason"] = "not-best-chemistry"

    files = expected_expansion_files({"schema": "ald-recipe-evidence/1", "records": [selected, rejected]})
    assert len(files) == 1
    path, payload = next(iter(files.items()))
    assert path.name == recipe_filename(selected)
    assert path.parent.name == "oxides"
    decoded = json.loads(payload)
    assert decoded["metadata"]["evidence_record_id"] == selected["evidence_id"]


def test_expected_expansion_files_rejects_duplicate_selected_target():
    one = selected_record(doi="10.1234/one")
    two = selected_record(doi="10.1234/two")
    try:
        expected_expansion_files({"schema": "ald-recipe-evidence/1", "records": [one, two]})
    except ValueError as error:
        assert "duplicate selected target" in str(error)
    else:
        raise AssertionError("duplicate selected target was accepted")
