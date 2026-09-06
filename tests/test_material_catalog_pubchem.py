from __future__ import annotations

from tools import build_material_catalog as builder


def test_builder_can_require_pubchem_bulk_matches_for_selection():
    source_records = [
        {"source": "cod", "source_id": "1", "formula": "HfO2", "name": "hafnia"},
        {"source": "cod", "source_id": "2", "formula": "TiO2", "name": "titania"},
        {"source": "cod", "source_id": "3", "formula": "ZrO2", "name": "zirconia"},
    ]
    pubchem_records = [
        {"reduced_formula": "HfO2", "cid": "23976", "cids": ["23976"]},
        {"reduced_formula": "TiO2", "cid": "26042", "cids": ["26042", "66217"]},
    ]
    metadata = {
        "audit_mode": "bulk-mirror",
        "mirror": "PubChemRDF",
        "mirror_release_date": "2026-07-25",
        "formula_records_scanned": 123456789,
        "matched_candidate_formula_count": 2,
    }

    catalog, manifest, audit = builder.build_material_artifacts(
        source_records,
        pubchem_records,
        [],
        target_count=2,
        require_pubchem_match=True,
        pubchem_audit_metadata=metadata,
    )

    assert [entry["reduced_formula"] for entry in catalog["entries"]] == ["HfO2", "TiO2"]
    assert all(entry["pubchem_audit"]["status"] == "matched" for entry in catalog["entries"])
    assert catalog["entries"][1]["pubchem_audit"]["cids"] == ["26042", "66217"]
    assert manifest["source_metadata"]["pubchem"]["audit_mode"] == "bulk-mirror"
    assert audit["target_count"] == 2
    assert audit["selected_count"] == 2
    assert audit["pubchem_matched_count"] == 2
    assert audit["pubchem_candidate_match_count"] == 2
