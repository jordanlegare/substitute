from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import ald_materials as materials


CATALOG = Path("materials/catalog.json")
AUDIT = Path("materials/build-audit.json")
MANIFEST = Path("materials/source-manifest.json")
COD_SOURCE = Path("materials/sources/cod-materials.json")
PUBCHEM_SOURCE = Path("materials/sources/pubchem-identities.json")

FORBIDDEN_KEYS = {
    "temperature",
    "process_temperature",
    "pulse_time",
    "dose_time",
    "flow",
    "flow_rate",
    "pressure",
    "equipment",
    "equipment_settings",
    "precursor_handling",
    "fabrication_mapping",
    "physical_fabrication_mapping",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_checked_in_material_catalog_has_exactly_1000_real_counted_formulas():
    entries = materials.load_material_catalog(CATALOG)
    counted = [entry for entry in entries if entry.get("counted") is True]

    assert len(counted) == 1000
    assert len({entry["reduced_formula"] for entry in counted}) == 1000
    assert len({entry["material_id"] for entry in counted}) == 1000
    assert all(len(entry["elements"]) >= 2 for entry in counted)
    assert all(entry["provenance"] for entry in counted)
    assert all(entry.get("identifiers", {}).get("cod_ids") for entry in counted)
    assert all(materials.reduce_formula(entry["formula"])[0] == entry["reduced_formula"] for entry in counted)


def test_checked_in_catalog_contains_common_thin_film_reference_materials():
    entries = materials.load_material_catalog(CATALOG)
    formulas = {entry["reduced_formula"] for entry in entries if entry.get("counted") is True}
    expected = {
        "HfO2",
        "Al2O3",
        "O2Ti",
        "O2Si",
        "OZn",
        "GaN",
        "AlN",
        "NTi",
        "MoS2",
        "S2W",
    }
    assert expected <= formulas


def test_material_catalog_contains_no_operational_process_metadata():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    keys = {key.casefold() for key in _walk_keys(payload)}
    assert FORBIDDEN_KEYS.isdisjoint(keys)


def test_material_catalog_artifacts_rebuild_byte_identically():
    result = subprocess.run(
        [sys.executable, "tools/build_material_catalog.py", "--check", "--target-count", "1000"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_material_catalog_audit_and_manifest_match_milestone():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert audit["counted_catalog_size"] == 1000
    assert len(audit["final_material_ids"]) == 1000
    assert audit["accepted_candidate_count_before_selection"] >= 1000
    assert audit["recipe_linked_materials"] > 0
    assert audit["pubchem_enrichment_successes"] + audit["pubchem_enrichment_unresolved"] == 1000
    assert manifest["target_count"] == 1000
    assert manifest["selection_policy_version"] == "materials-1000-v2"
    assert COD_SOURCE.exists()
    assert PUBCHEM_SOURCE.exists()
