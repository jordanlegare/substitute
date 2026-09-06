import json

from tools.refresh_recipe_evidence import fetch_atomiclimits_records


def test_fetch_atomiclimits_records_normalizes_and_replays_cache(tmp_path):
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
            }
        ],
        "references": [
            {
                "reference_id": "2205",
                "process_id": "429",
                "reference_doi": "10.3938/jkps.45.1249",
                "reference_reviewed": "1",
            }
        ],
    }
    calls = []

    def first_fetch(url):
        calls.append(url)
        return json.dumps(payload).encode("utf-8")

    records = fetch_atomiclimits_records(tmp_path, first_fetch)

    assert calls == ["https://www.atomiclimits.com/alddatabase/api/processes.php"]
    assert len(records) == 1
    assert records[0]["target_reduced_formula"] == "O2Zr"
    assert records[0]["reactants"] == [
        {"label": "Zr(OtBu)4", "role": "reactant-a"},
        {"label": "H2O", "role": "reactant-b"},
    ]
    assert records[0]["evidence_grade"] == "R3"
    assert "250 C" not in json.dumps(records)

    def fail_fetch(url):
        raise AssertionError(f"network should not be used for cached URL: {url}")

    assert fetch_atomiclimits_records(tmp_path, fail_fetch) == records
