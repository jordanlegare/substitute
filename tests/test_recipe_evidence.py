from copy import deepcopy

import pytest

from ald_recipe_evidence import (
    chemistry_key,
    normalize_doi,
    normalize_process_family,
    select_best_candidates,
    selection_sort_key,
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


def test_selection_sort_key_prefers_r3_over_r2():
    r2 = validate_evidence_record(direct_record(evidence_grade="R2"))
    r3 = validate_evidence_record(
        direct_record(
            evidence_grade="R3",
            publications=[
                {"type": "doi", "identifier": "10.1234/a", "direct": True},
                {"type": "doi", "identifier": "10.1234/b", "direct": True},
            ],
        )
    )
    assert selection_sort_key(r3) < selection_sort_key(r2)


def test_select_best_candidates_selects_one_best_r3_per_new_target():
    r2 = direct_record(
        target_material="titanium nitride",
        target_formula="TiN",
        evidence_grade="R2",
        publications=[{"type": "doi", "identifier": "10.1234/tin-r2", "direct": True}],
    )
    r3 = direct_record(
        target_material="titanium nitride",
        target_formula="TiN",
        evidence_grade="R3",
        publications=[
            {"type": "doi", "identifier": "10.1234/tin-r3a", "direct": True},
            {"type": "doi", "identifier": "10.1234/tin-r3b", "direct": True},
        ],
    )

    selected = select_best_candidates([r2, r3], existing_target_formulas=set())
    winners = [item for item in selected if item["selection_status"] == "selected"]
    losers = [item for item in selected if item["selection_status"] == "rejected"]

    assert len(winners) == 1
    assert winners[0]["evidence_grade"] == "R3"
    assert len(losers) == 1
    assert losers[0]["rejection_reason"] == "not-best-chemistry"


def test_select_best_candidates_never_selects_r1():
    record = direct_record(evidence_grade="R1")
    result = select_best_candidates([record], existing_target_formulas=set())
    assert result[0]["selection_status"] == "rejected"
    assert result[0]["rejection_reason"] == "insufficient-evidence"


def test_select_best_candidates_preserves_existing_target_without_new_recipe():
    record = direct_record()
    result = select_best_candidates([record], existing_target_formulas={"HfO2"})
    assert result[0]["selection_status"] == "covered-existing"
    assert result[0]["rejection_reason"] == "already-recipe-backed"
