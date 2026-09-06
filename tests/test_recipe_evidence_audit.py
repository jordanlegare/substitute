import hashlib

import pytest

import ald_recipe_evidence as evidence_core
from tools.audit_recipe_evidence import audit_evidence


def selected_record(*, target_formula="TiN", doi="10.1234/tin", reactant_a="TiCl4", reactant_b="NH3", grade="R2"):
    return evidence_core.validate_evidence_record(
        {
            "target_material": target_formula,
            "target_formula": target_formula,
            "process_family": "thermal-ald",
            "reactants": [
                {"label": reactant_a, "role": "reactant-a"},
                {"label": reactant_b, "role": "reactant-b"},
            ],
            "publications": [{"type": "doi", "identifier": doi, "direct": True}],
            "discovery_sources": ["atomiclimits"],
            "evidence_grade": grade,
            "selection_status": "selected",
        }
    )


def ledger(*records):
    return {"schema": "ald-recipe-evidence/1", "records": list(records)}


def manifest_for(evidence):
    digest = hashlib.sha256(evidence_core.canonical_json_bytes(evidence)).hexdigest()
    return {
        "schema": "ald-recipe-evidence-manifest/1",
        "sources": {},
        "digests": {"process_evidence_sha256": digest},
    }


def acquisition_audit():
    return {"schema": "ald-recipe-evidence-audit/1", "counts": {}, "rejections": {}}


def material_catalog(*formulas):
    return {
        "catalog_schema": "ald-material-catalog/1",
        "entries": [
            {"reduced_formula": evidence_core.materials.reduce_formula(formula)[0]}
            for formula in formulas
        ],
    }


def historical_recipe(target_formula="HfO2"):
    return {
        "recipe_id": "historical-001",
        "target_formula": target_formula,
        "path": "recipes/compounds/oxides/historical.json",
    }


def expansion_recipe(record):
    return {
        "recipe_id": "expansion-001",
        "target_formula": record["target_formula"],
        "path": "recipes/compounds/nitrides/expansion.json",
        "recipe_origin": "evidence-expansion",
        "evidence_record_id": record["evidence_id"],
    }


def test_audit_accepts_one_selected_new_target_linked_to_one_generated_recipe():
    record = selected_record()
    evidence = ledger(record)
    result = audit_evidence(
        evidence,
        manifest_for(evidence),
        acquisition_audit(),
        {"catalog_schema": "ald-compound-catalog/1", "entries": [historical_recipe(), expansion_recipe(record)]},
        material_catalog("HfO2", "TiN"),
    )
    assert result["selected_record_count"] == 1
    assert result["generated_recipe_count"] == 1
    assert result["linked_generated_recipe_count"] == 1


def test_audit_rejects_r1_selected_record():
    record = selected_record(grade="R1")
    evidence = ledger(record)
    with pytest.raises(ValueError, match="R1.*selected"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": []},
            material_catalog("TiN"),
        )


def test_audit_rejects_two_selected_chemistries_for_same_target():
    one = selected_record(doi="10.1234/one")
    two = selected_record(doi="10.1234/two", reactant_b="N2/H2 plasma")
    evidence = ledger(one, two)
    with pytest.raises(ValueError, match="duplicate selected target"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": []},
            material_catalog("TiN"),
        )


def test_audit_rejects_selected_target_that_was_already_historical_recipe_backed():
    record = selected_record(target_formula="HfO2")
    evidence = ledger(record)
    with pytest.raises(ValueError, match="already recipe-backed"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": [historical_recipe("HfO2")]},
            material_catalog("HfO2"),
        )


def test_audit_rejects_r2_without_direct_publication():
    raw = selected_record()
    raw["publications"] = [{"type": "doi", "identifier": "10.1234/review", "direct": False}]
    evidence = ledger(raw)
    with pytest.raises(ValueError, match="direct publication"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": []},
            material_catalog("TiN"),
        )


def test_audit_rejects_generated_recipe_without_selected_evidence_record():
    record = selected_record()
    evidence = ledger(record)
    recipe = expansion_recipe(record)
    recipe["evidence_record_id"] = "ev-missing-deadbeef"
    with pytest.raises(ValueError, match="missing selected evidence"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": [recipe]},
            material_catalog("TiN"),
        )


def test_audit_rejects_manifest_digest_mismatch():
    record = selected_record()
    evidence = ledger(record)
    manifest = manifest_for(evidence)
    manifest["digests"]["process_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        audit_evidence(
            evidence,
            manifest,
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": []},
            material_catalog("TiN"),
        )


def test_audit_rejects_operational_fields_anywhere_in_record():
    record = selected_record()
    record["provenance"] = {"nested": {"plasma_power": 300}}
    evidence = ledger(record)
    with pytest.raises(ValueError, match="operational"):
        audit_evidence(
            evidence,
            manifest_for(evidence),
            acquisition_audit(),
            {"catalog_schema": "ald-compound-catalog/1", "entries": []},
            material_catalog("TiN"),
        )
