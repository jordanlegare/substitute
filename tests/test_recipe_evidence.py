from copy import deepcopy

import pytest

from ald_recipe_evidence import (
    chemistry_key,
    normalize_doi,
    normalize_process_family,
    validate_evidence_record,
)


def direct_record(**overrides):
    record = {
        "target_material": "hafnium dioxide",
        "target_formula": "HfO2",
        "process_family": "thermal-ald",
        "reactants": [
            {
                "name": "hafnium tetrachloride",
                "formula": "HfCl4",
                "role": "metal-source",
            },
            {"name": "water", "formula": "H2O", "role": "co-reactant"},
        ],
        "publications": [
            {
                "type": "doi",
                "identifier": "https://doi.org/10.1234/Example",
                "direct": True,
            }
        ],
        "discovery_sources": ["atomiclimits"],
        "evidence_grade": "R2",
        "selection_status": "candidate",
    }
    record.update(overrides)
    return record


def test_normalize_doi_removes_url_prefix_and_normalizes_case():
    assert normalize_doi(" HTTPS://DOI.ORG/10.1234/ABC ") == "10.1234/abc"
    assert normalize_doi("http://dx.doi.org/10.5555/Mixed.Case") == "10.5555/mixed.case"


def test_normalize_process_family_accepts_known_aliases_and_rejects_unknown():
    assert normalize_process_family("PEALD") == "plasma-ald"
    assert normalize_process_family("thermal ALD") == "thermal-ald"
    assert normalize_process_family("molecular layer deposition") == "mld"
    with pytest.raises(ValueError, match="process family"):
        normalize_process_family("chemical vapor deposition")


def test_chemistry_key_is_reactant_order_independent():
    record = direct_record()
    reactants = record["reactants"]
    assert chemistry_key("HfO2", "thermal-ald", reactants) == chemistry_key(
        "HfO2", "thermal-ald", list(reversed(reactants))
    )


def test_validation_normalizes_direct_record_without_mutating_input():
    raw = direct_record()
    before = deepcopy(raw)
    normalized = validate_evidence_record(raw)

    assert raw == before
    assert normalized["target_formula"] == "HfO2"
    assert normalized["target_reduced_formula"] == "HfO2"
    assert normalized["process_family"] == "thermal-ald"
    assert normalized["publications"][0]["identifier"] == "10.1234/example"
    assert normalized["reactant_identities_complete"] is True
    assert normalized["independent_direct_publication_count"] == 1
    assert normalized["stable_publication_identifier_count"] == 1
    assert normalized["chemistry_key"]
    assert normalized["evidence_id"].startswith("ev-hfo2-")


def test_validation_rejects_operational_fields_recursively():
    record = direct_record(
        provenance={"source": "example", "nested": {"process_temperature": 250}}
    )
    with pytest.raises(ValueError, match="operational"):
        validate_evidence_record(record)


def test_validation_rejects_r2_without_direct_publication():
    record = direct_record(
        publications=[
            {"type": "doi", "identifier": "10.1234/review", "direct": False}
        ]
    )
    with pytest.raises(ValueError, match="direct publication"):
        validate_evidence_record(record)
