import io
import json
from pathlib import Path

import ald_recipe_evidence as evidence_core
from tools.refresh_recipe_evidence import (
    build_frozen_evidence,
    cached_fetch_json,
    classify_process_family,
    normalize_crossref_work,
    normalize_openalex_work,
    parse_atomiclimits_api_payload,
    parse_awases_rows,
)


FIXTURES = Path("tests/fixtures/recipe_evidence")


def _candidate(target_formula, doi, *, grade="R2", family="thermal-ald", reactants=None):
    return evidence_core.validate_evidence_record(
        {
            "target_material": target_formula,
            "target_formula": target_formula,
            "process_family": family,
            "reactants": reactants
            or [
                {"label": "A-source", "role": "reactant-a"},
                {"label": "B-source", "role": "reactant-b"},
            ],
            "publications": [{"type": "doi", "identifier": doi, "direct": True}],
            "discovery_sources": ["atomiclimits"],
            "evidence_grade": grade,
            "selection_status": "candidate",
        }
    )


def _material_entry(formula):
    reduced, elements = evidence_core.materials.reduce_formula(formula)
    return {
        "material_id": evidence_core.materials.material_id(reduced),
        "name": formula,
        "formula": formula,
        "reduced_formula": reduced,
        "elements": list(elements),
    }


def test_classify_process_family_is_conservative_and_deterministic():
    assert classify_process_family("Plasma-enhanced atomic layer deposition", "", "") == "plasma-ald"
    assert classify_process_family("Molecular layer deposition of a hybrid film", "", "") == "mld"
    assert classify_process_family("Hybrid ALD/MLD supercycle", "", "") == "hybrid"
    assert classify_process_family("Atomic layer deposition of alumina", "", "") == "thermal-ald"
    assert classify_process_family("Chemical vapor deposition of silica", "", "") is None


def test_atomiclimits_live_api_joins_references_and_preserves_source_labels_only():
    payload = {
        "success": True,
        "processes": [
            {
                "process_id": "429",
                "process_material": "ZrO2",
                "process_reactantA": "Zr(OtBu)4",
                "process_reactantB": "H2O",
                "process_reactantC": "",
                "process_reactantD": "",
                "process_note": "reported at 250 C",
                "process_reviewed": "1",
            },
            {
                "process_id": "9001",
                "process_material": "TiN",
                "process_reactantA": "TiCl4",
                "process_reactantB": "N2/H2 plasma",
                "process_reactantC": "",
                "process_reactantD": "",
                "process_note": "300 W plasma",
                "process_reviewed": "1",
            },
        ],
        "references": [
            {
                "reference_id": "2205",
                "process_id": "429",
                "reference_doi": "10.3938/jkps.45.1249",
                "reference_reviewed": "1",
            },
            {
                "reference_id": "2207",
                "process_id": "429",
                "reference_doi": "10.1002/example",
                "reference_reviewed": "1",
            },
            {
                "reference_id": "9900",
                "process_id": "9001",
                "reference_doi": "10.1234/tin-plasma",
                "reference_reviewed": "1",
            },
        ],
    }

    records = parse_atomiclimits_api_payload(payload)

    assert [record["target_reduced_formula"] for record in records] == ["NTi", "O2Zr"]
    tin, zirconia = records
    assert tin["process_family"] == "plasma-ald"
    assert tin["reactants"] == [
        {"label": "TiCl4", "role": "reactant-a"},
        {"label": "N2/H2 plasma", "role": "reactant-b"},
    ]
    assert tin["evidence_grade"] == "R3"
    assert zirconia["process_family"] == "thermal-ald"
    assert [item["identifier"] for item in zirconia["publications"]] == [
        "10.1002/example",
        "10.3938/jkps.45.1249",
    ]
    assert zirconia["evidence_grade"] == "R3"

    serialized = json.dumps(records).casefold()
    assert "250 c" not in serialized
    assert "300 w" not in serialized
    assert "process_note" not in serialized


def test_awases_parser_keeps_only_fixed_ald_targets_and_exact_source_labels():
    with (FIXTURES / "awases_sample.csv").open(encoding="utf-8", newline="") as stream:
        records = parse_awases_rows(stream)

    assert [record["target_reduced_formula"] for record in records] == ["Al2O3", "NTi"]
    alumina, tin = records
    assert alumina["process_family"] == "thermal-ald"
    assert alumina["reactants"] == [
        {"label": "Al(NiPr2)3", "role": "reactant-a"},
        {"label": "H2O", "role": "reactant-b"},
    ]
    assert alumina["publications"][0]["identifier"] == "10.1016/j.matlet.2007.04.009"
    assert alumina["evidence_grade"] == "R3"
    assert tin["process_family"] == "plasma-ald"
    assert tin["reactants"][1]["label"] == "N2/H2 plasma"

    serialized = json.dumps(records).casefold()
    assert "250 c" not in serialized
    assert "300 w" not in serialized
    assert "full_text" not in serialized
    assert "abstract" not in serialized
    assert "process_note" not in serialized
    assert "chemical vapor deposition" not in serialized
    assert "alxoy" not in serialized


def test_crossref_normalization_is_non_operational_and_canonical():
    payload = json.loads((FIXTURES / "crossref_work.json").read_text(encoding="utf-8"))
    result = normalize_crossref_work(payload)
    assert result == {
        "type": "doi",
        "identifier": "10.1016/j.matlet.2007.04.009",
        "title": "Tris(dialkylamino)aluminums and atomic layer deposition of alumina thin films",
        "journal": "Materials Letters",
        "year": 2007,
    }


def test_openalex_normalization_is_non_operational_and_canonical():
    payload = json.loads((FIXTURES / "openalex_work.json").read_text(encoding="utf-8"))
    result = normalize_openalex_work(payload)
    assert result == {
        "type": "doi",
        "identifier": "10.1016/j.matlet.2007.04.009",
        "title": "Tris(dialkylamino)aluminums and atomic layer deposition of alumina thin films",
        "journal": "Materials Letters",
        "year": 2007,
        "openalex_id": "W1234567890",
    }


def test_cached_fetch_json_replays_without_network(tmp_path):
    calls = []

    def first_fetch(url):
        calls.append(url)
        return b'{"answer":42}'

    assert cached_fetch_json("https://example.test/work", tmp_path, first_fetch) == {"answer": 42}
    assert calls == ["https://example.test/work"]

    def fail_fetch(url):
        raise AssertionError(f"network should not be used for cached URL: {url}")

    assert cached_fetch_json("https://example.test/work", tmp_path, fail_fetch) == {"answer": 42}


def test_build_frozen_evidence_preserves_existing_and_selects_one_best_new_target():
    records = [
        _candidate("HfO2", "10.1234/hfo2", grade="R3"),
        _candidate("ZnO", "10.1234/zno-r2", grade="R2"),
        _candidate("ZnO", "10.1234/zno-r3", grade="R3"),
    ]
    material_catalog = {
        "entries": [_material_entry("HfO2"), _material_entry("ZnO")]
    }
    recipe_catalog = {
        "entries": [
            {
                "recipe_id": "historical-hfo2",
                "target_formula": "HfO2",
                "path": "recipes/compounds/oxides/historical_hfo2.json",
            }
        ]
    }

    evidence_doc, manifest, audit = build_frozen_evidence(
        records,
        material_catalog,
        recipe_catalog,
        source_metadata={
            "awases_repository": "jd-coderepos/awases-ald",
            "awases_ref": "abc123",
            "awases_path": "step 1/data/2-filtered-data.csv",
        },
    )

    statuses = {
        (record["target_reduced_formula"], record["selection_status"], record["evidence_grade"])
        for record in evidence_doc["records"]
    }
    assert ("HfO2", "covered-existing", "R3") in statuses
    assert ("OZn", "selected", "R3") in statuses
    assert ("OZn", "rejected", "R2") in statuses
    selected = [record for record in evidence_doc["records"] if record["selection_status"] == "selected"]
    assert selected[0]["material_id"] == _material_entry("ZnO")["material_id"]
    assert manifest["schema"] == "ald-recipe-evidence-manifest/1"
    assert manifest["sources"]["atomiclimits"]["awases_ref"] == "abc123"
    assert len(manifest["digests"]["process_evidence_sha256"]) == 64
    assert audit["counts"]["material_identities_examined"] == 2
    assert audit["counts"]["existing_recipe_backed_materials"] == 1
    assert audit["counts"]["new_distinct_materials_selected"] == 1
    assert audit["counts"]["r3_selected"] == 1
    assert audit["counts"]["r2_selected"] == 0
    assert audit["counts"]["final_executable_recipe_count"] == 2
    assert audit["counts"]["remaining_identity_only_materials"] == 0
    assert audit["rejections"]["already-recipe-backed"] == 1
    assert audit["rejections"]["not-best-chemistry"] == 1


def test_build_frozen_evidence_excludes_candidates_outside_material_universe():
    records = [
        _candidate("ZnO", "10.1234/zno", grade="R3"),
        _candidate("CdO", "10.1234/cdo", grade="R3"),
    ]
    evidence_doc, _manifest, audit = build_frozen_evidence(
        records,
        {"entries": [_material_entry("ZnO")]},
        {"entries": []},
        source_metadata={"awases_ref": "abc123"},
    )
    assert {record["target_reduced_formula"] for record in evidence_doc["records"]} == {"OZn"}
    assert audit["counts"]["source_candidates_outside_material_catalog"] == 1


def test_build_frozen_evidence_collapses_duplicate_canonical_evidence_ids():
    duplicate = _candidate("HfO2", "10.1234/hfo2", grade="R3")
    evidence_doc, _manifest, audit = build_frozen_evidence(
        [duplicate, dict(duplicate)],
        {"entries": [_material_entry("HfO2")]},
        {"entries": []},
        source_metadata={"awases_ref": "abc123"},
    )

    assert len(evidence_doc["records"]) == 1
    assert evidence_doc["records"][0]["selection_status"] == "selected"
    assert audit["counts"]["duplicate_evidence_collapses"] == 1


def test_build_frozen_evidence_does_not_treat_previous_expansion_as_historical_baseline():
    records = [
        _candidate("HfO2", "10.1234/hfo2", grade="R3"),
        _candidate("ZnO", "10.1234/zno", grade="R3"),
    ]
    recipe_catalog = {
        "entries": [
            {
                "recipe_id": "historical-hfo2",
                "target_formula": "HfO2",
                "path": "recipes/compounds/oxides/historical_hfo2.json",
            },
            {
                "recipe_id": "exp-zno-old-snapshot",
                "target_formula": "ZnO",
                "path": "recipes/compounds/oxides/exp_zno_old_snapshot.json",
                "recipe_origin": "evidence-expansion",
                "evidence_record_id": "ev-old",
                "process_family": "thermal-ald",
            },
        ]
    }

    evidence_doc, _manifest, audit = build_frozen_evidence(
        records,
        {"entries": [_material_entry("HfO2"), _material_entry("ZnO")]},
        recipe_catalog,
        source_metadata={"transport": "atomiclimits-live-api"},
    )

    statuses = {
        (record["target_reduced_formula"], record["selection_status"])
        for record in evidence_doc["records"]
    }
    assert ("HfO2", "covered-existing") in statuses
    assert ("OZn", "selected") in statuses
    assert audit["counts"]["existing_recipe_backed_materials"] == 1
    assert audit["counts"]["new_distinct_materials_selected"] == 1
    assert audit["counts"]["final_executable_recipe_count"] == 2
