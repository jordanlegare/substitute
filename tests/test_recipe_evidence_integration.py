import json
from pathlib import Path

import ald_core as core
import ald_materials as materials
import ald_recipe_evidence as evidence_core


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def reduced_formula(value: str) -> str:
    reduced, _elements = materials.reduce_formula(value)
    return reduced


def test_selected_evidence_and_expansion_recipes_are_one_to_one_and_compile():
    evidence_document = load_json("recipes/evidence/process-evidence.json")
    catalog = load_json("recipes/compounds/catalog.json")
    audit = load_json("recipes/evidence/acquisition-audit.json")

    records = [
        evidence_core.validate_evidence_record(record)
        for record in evidence_document["records"]
    ]
    selected = [record for record in records if record["selection_status"] == "selected"]
    expansion = [
        entry
        for entry in catalog["entries"]
        if entry.get("recipe_origin") == "evidence-expansion"
    ]
    historical = [
        entry
        for entry in catalog["entries"]
        if entry.get("recipe_origin") != "evidence-expansion"
    ]

    expected_count = audit["counts"]["new_distinct_materials_selected"]
    assert len(selected) == expected_count
    assert len(expansion) == expected_count
    assert all(record["evidence_grade"] in {"R2", "R3"} for record in selected)
    assert not any(
        record["selection_status"] == "selected" and record["evidence_grade"] == "R1"
        for record in records
    )

    selected_ids = [record["evidence_id"] for record in selected]
    expansion_ids = [entry["evidence_record_id"] for entry in expansion]
    assert len(selected_ids) == len(set(selected_ids))
    assert len(expansion_ids) == len(set(expansion_ids))
    assert set(expansion_ids) == set(selected_ids)

    selected_targets = [record["target_reduced_formula"] for record in selected]
    assert len(selected_targets) == len(set(selected_targets))

    historical_targets = set()
    for entry in historical:
        try:
            historical_targets.add(reduced_formula(entry["target_formula"]))
        except ValueError:
            pass
    assert set(selected_targets).isdisjoint(historical_targets)

    evidence_by_id = {record["evidence_id"]: record for record in selected}
    for entry in expansion:
        record = evidence_by_id[entry["evidence_record_id"]]
        assert reduced_formula(entry["target_formula"]) == record["target_reduced_formula"]
        assert entry["process_family"] == record["process_family"]
        expected_sources = sorted(
            (publication["type"], publication["identifier"])
            for publication in record["publications"]
        )
        actual_sources = sorted(
            (source["type"], source["identifier"])
            for source in entry["source_references"]
        )
        assert actual_sources == expected_sources

        recipe_path = ROOT / entry["path"]
        raw_recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        assert raw_recipe["metadata"]["evidence_record_id"] == record["evidence_id"]
        assert raw_recipe["metadata"]["physical_fabrication_mapping"] is False
        assert "synthetic simulator values" in raw_recipe["metadata"]["simulation_notice"]
        core.compile_recipe(core.validate_recipe(raw_recipe))


def test_frozen_audit_counts_match_catalog_and_material_coverage():
    catalog = load_json("recipes/compounds/catalog.json")
    material_catalog = load_json("materials/catalog.json")
    audit = load_json("recipes/evidence/acquisition-audit.json")

    expansion = [
        entry
        for entry in catalog["entries"]
        if entry.get("recipe_origin") == "evidence-expansion"
    ]
    assert len(catalog["entries"]) == audit["counts"]["final_executable_recipe_count"]
    assert len(expansion) == audit["counts"]["new_distinct_materials_selected"]
    assert len(material_catalog["entries"]) == audit["counts"]["material_identities_examined"]
    assert (
        audit["counts"]["existing_recipe_backed_materials"]
        + audit["counts"]["new_distinct_materials_selected"]
        + audit["counts"]["remaining_identity_only_materials"]
        == audit["counts"]["material_identities_examined"]
    )
