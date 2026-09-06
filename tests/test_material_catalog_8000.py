from __future__ import annotations

import json
from pathlib import Path

import ald_materials as materials


CATALOG = Path("materials/catalog.json")
AUDIT = Path("materials/build-audit.json")
MANIFEST = Path("materials/source-manifest.json")
PUBCHEM = Path("materials/sources/pubchem-identities.json")


def test_checked_in_catalog_has_exactly_8000_materials():
    entries = materials.load_material_catalog(CATALOG)
    assert len(entries) == 8000
    assert len({entry["material_id"] for entry in entries}) == 8000
    assert len({entry["reduced_formula"] for entry in entries}) == 8000


def test_all_8000_materials_have_exact_pubchem_bulk_formula_matches():
    entries = materials.load_material_catalog(CATALOG)
    assert all(entry["pubchem_audit"]["status"] == "matched" for entry in entries)
    assert all(entry["pubchem_audit"]["mirror"] == "PubChemRDF" for entry in entries)
    assert all(entry["pubchem_audit"]["release_date"] for entry in entries)
    assert all(entry["pubchem_audit"]["cids"] for entry in entries)
    provenance_sources = {
        item["source"]
        for entry in entries
        for item in entry["provenance"]
    }
    assert "cod" in provenance_sources
    assert "pubchem" in provenance_sources


def test_pubchem_identity_snapshot_is_full_bulk_audit_not_per_formula_api_cache():
    payload = json.loads(PUBCHEM.read_text(encoding="utf-8"))
    assert payload["schema"] == "ald-material-pubchem-rdf-audit/1"
    assert payload["audit_mode"] == "bulk-mirror"
    assert payload["mirror"] == "PubChemRDF"
    assert payload["selection_mode"] == "cod-plus-pubchem-primary"
    assert payload["requested_material_count"] == 8000
    assert payload["audited_candidate_formula_count"] >= 8000
    assert payload["matched_candidate_formula_count"] > 0
    assert payload["supplemental_formula_count"] > 0
    assert payload["eligible_formula_count"] >= 8000
    assert payload["formula_records_scanned"] > 1_000_000
    assert payload["mirror_release_date"]
    assert payload["shard_count"] == 9
    assert payload["compressed_bytes"] == 803_480_392


def test_manifest_and_build_audit_record_8000_pubchem_milestone():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert manifest["target_count"] == 8000
    assert manifest["source_metadata"]["pubchem"]["audit_mode"] == "bulk-mirror"
    assert manifest["source_metadata"]["pubchem"]["mirror"] == "PubChemRDF"
    assert manifest["source_metadata"]["pubchem"]["selection_mode"] == "cod-plus-pubchem-primary"
    assert audit["target_count"] == 8000
    assert audit["selected_count"] == 8000
    assert audit["pubchem_matched_count"] == 8000
    assert audit["pubchem_candidate_match_count"] >= 8000
    assert audit["cod_backed_selected_count"] > 0
    assert audit["pubchem_primary_selected_count"] > 0
    assert audit["cod_backed_selected_count"] + audit["pubchem_primary_selected_count"] == 8000
