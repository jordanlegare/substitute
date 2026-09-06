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


def test_all_8000_materials_are_audited_against_pubchem_bulk_mirror():
    entries = materials.load_material_catalog(CATALOG)
    assert all(entry["provenance"]["pubchem_audit"]["status"] in {"matched", "no_exact_formula_match"} for entry in entries)
    assert all(entry["provenance"]["pubchem_audit"]["mirror"] == "PubChemRDF" for entry in entries)


def test_pubchem_identity_snapshot_is_bulk_audit_not_per_formula_api_cache():
    payload = json.loads(PUBCHEM.read_text(encoding="utf-8"))
    assert payload["audit_mode"] == "bulk-mirror"
    assert payload["mirror"] == "PubChemRDF"
    assert payload["target_formula_count"] == 8000
    assert payload["formula_records_scanned"] > 1_000_000


def test_manifest_and_build_audit_record_8000_pubchem_milestone():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert manifest["target_count"] == 8000
    assert manifest["source_metadata"]["pubchem"]["audit_mode"] == "bulk-mirror"
    assert audit["target_count"] == 8000
    assert audit["selected_count"] == 8000
    assert audit["pubchem_audited_count"] == 8000
