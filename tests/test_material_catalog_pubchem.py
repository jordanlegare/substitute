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

    assert [entry["reduced_formula"] for entry in catalog["entries"]] == ["HfO2", "O2Ti"]
    assert all(entry["pubchem_audit"]["status"] == "matched" for entry in catalog["entries"])
    assert catalog["entries"][1]["pubchem_audit"]["cids"] == ["26042", "66217"]
    assert manifest["source_metadata"]["pubchem"]["audit_mode"] == "bulk-mirror"
    assert audit["target_count"] == 2
    assert audit["selected_count"] == 2
    assert audit["pubchem_matched_count"] == 2
    assert audit["pubchem_candidate_match_count"] == 2


def test_builder_can_fill_shortfall_with_explicit_pubchem_primary_identity():
    source_records = [
        {"source": "cod", "source_id": "1", "formula": "HfO2", "name": "hafnia"},
    ]
    pubchem_records = [
        {
            "reduced_formula": "HfO2",
            "cid": "23976",
            "cids": ["23976"],
            "identity_origin": "cod+pubchem",
        },
        {
            "reduced_formula": "GaSb",
            "cid": "160954",
            "cids": ["160954"],
            "identity_origin": "pubchem-primary",
        },
    ]
    metadata = {
        "audit_mode": "bulk-mirror",
        "mirror": "PubChemRDF",
        "mirror_release_date": "2026-07-25",
        "selection_mode": "cod-plus-pubchem-primary",
    }

    catalog, _manifest, audit = builder.build_material_artifacts(
        source_records,
        pubchem_records,
        [],
        target_count=2,
        require_pubchem_match=True,
        include_pubchem_primary=True,
        pubchem_audit_metadata=metadata,
    )

    entries = {entry["reduced_formula"]: entry for entry in catalog["entries"]}
    assert set(entries) == {"GaSb", "HfO2"}
    assert entries["GaSb"]["provenance"] == [
        {"source": "pubchem", "source_id": "160954", "evidence": "materials_identity"}
    ]
    assert entries["GaSb"]["identifiers"]["pubchem_cid"] == "160954"
    assert entries["GaSb"]["pubchem_audit"]["status"] == "matched"
    assert audit["cod_backed_selected_count"] == 1
    assert audit["pubchem_primary_selected_count"] == 1


def test_cod_backed_identity_ranks_before_pubchem_primary_supplement():
    source_records = [
        {"source": "cod", "source_id": "1", "formula": "GaSb", "name": "gallium antimonide"},
    ]
    pubchem_records = [
        {
            "reduced_formula": "GaSb",
            "cid": "160954",
            "cids": ["160954"],
            "identity_origin": "cod+pubchem",
        },
        {
            "reduced_formula": "InSb",
            "cid": "5355353",
            "cids": ["5355353"],
            "identity_origin": "pubchem-primary",
        },
    ]

    catalog, _manifest, _audit = builder.build_material_artifacts(
        source_records,
        pubchem_records,
        [],
        target_count=1,
        require_pubchem_match=True,
        include_pubchem_primary=True,
        pubchem_audit_metadata={"mirror": "PubChemRDF", "mirror_release_date": "2026-07-25"},
    )

    assert [entry["reduced_formula"] for entry in catalog["entries"]] == ["GaSb"]
