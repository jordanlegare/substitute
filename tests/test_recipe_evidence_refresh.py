import io
import json
from pathlib import Path

from tools.refresh_recipe_evidence import (
    cached_fetch_json,
    classify_process_family,
    normalize_crossref_work,
    normalize_openalex_work,
    parse_awases_rows,
)


FIXTURES = Path("tests/fixtures/recipe_evidence")


def test_classify_process_family_is_conservative_and_deterministic():
    assert classify_process_family("Plasma-enhanced atomic layer deposition", "", "") == "plasma-ald"
    assert classify_process_family("Molecular layer deposition of a hybrid film", "", "") == "mld"
    assert classify_process_family("Hybrid ALD/MLD supercycle", "", "") == "hybrid"
    assert classify_process_family("Atomic layer deposition of alumina", "", "") == "thermal-ald"
    assert classify_process_family("Chemical vapor deposition of silica", "", "") is None


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
