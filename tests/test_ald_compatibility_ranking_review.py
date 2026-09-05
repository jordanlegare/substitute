from __future__ import annotations

import pytest

import ald_compatibility as compat


def entity(identifier: str, formula: str, role: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": formula,
        "formula": formula,
        "aliases": [formula],
        "roles": [role],
    }


def pair(a: dict[str, object], b: dict[str, object], *, score: float, coverage: float) -> dict[str, object]:
    return {
        "id": f"pair-{a['id']}-{b['id']}",
        "a": {"id": a["id"], "name": a["name"], "formula": a["formula"]},
        "b": {"id": b["id"], "name": b["name"], "formula": b["formula"]},
        "features": [],
        "score": score,
        "coverage": coverage,
        "evidence_level": "E0_UNKNOWN" if coverage == 0 else "E1_HEURISTIC",
        "verdict": "UNKNOWN" if coverage == 0 else "SUPPORTED",
        "recipe_ids": [],
    }


def snapshot_for(entities: list[dict[str, object]], pairs: list[dict[str, object]], recipes=None):
    return {
        "schema": "ald-compatibility-snapshot/1",
        "safety_notice": "test",
        "precursors": entities,
        "precursor_pairs": pairs,
        "recipes": recipes or [],
        "candidate_model": {
            "weights": {
                "harmonic": 0.40,
                "minimum": 0.20,
                "coverage": 0.15,
                "roles": 0.15,
                "known": 0.10,
            },
            "beam_width": 50,
            "default_top": 20,
        },
    }


def test_candidate_pair_scores_shrink_toward_neutral_when_coverage_is_sparse():
    source = entity("p-source", "M1", "SOURCE")
    reactant = entity("p-reactant", "X1", "OXIDANT")
    snap = snapshot_for(
        [source, reactant],
        [pair(source, reactant, score=100.0, coverage=0.0)],
    )

    result = compat.explain_candidate(snap, ["M1", "X1"])

    assert result["components"]["harmonic"] == pytest.approx(50.0)
    assert result["components"]["minimum"] == pytest.approx(50.0)
    assert result["components"]["coverage"] == pytest.approx(0.0)


def test_candidate_subset_of_catalog_recipe_gets_partial_known_support():
    source = entity("p-source", "M1", "SOURCE")
    reactant = entity("p-reactant", "X1", "OXIDANT")
    extra = entity("p-extra", "Y1", "SOURCE")
    snap = snapshot_for(
        [source, reactant, extra],
        [
            pair(source, reactant, score=80.0, coverage=0.5),
            pair(source, extra, score=80.0, coverage=0.5),
            pair(reactant, extra, score=80.0, coverage=0.5),
        ],
        recipes=[
            {
                "recipe_id": "known-three",
                "precursor_ids": ["p-source", "p-reactant", "p-extra"],
            }
        ],
    )

    result = compat.explain_candidate(snap, ["M1", "X1"])

    assert result["matching_recipe_ids"] == []
    assert result["subset_recipe_ids"] == ["known-three"]
    assert result["known_support"] == pytest.approx(60.0)
    assert result["novel"] is True
