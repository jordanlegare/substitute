from __future__ import annotations

import json
from pathlib import Path

import pytest

import ald_compatibility as compat


MODEL = json.loads(Path("compatibility/model-v1.json").read_text(encoding="utf-8"))


def p(identifier: str, name: str, formula: str, role: str) -> dict[str, str]:
    return {"id": identifier, "name": name, "formula": formula, "role": role}


def entry(
    recipe_id: str,
    precursors: list[dict[str, str]],
    *,
    target_formula: str,
    target_material: str,
    status: str = "established",
    signature: list[str] | None = None,
) -> dict[str, object]:
    return {
        "recipe_id": recipe_id,
        "path": f"recipes/{recipe_id}.json",
        "precursor_count": len(precursors),
        "precursors": precursors,
        "target_formula": target_formula,
        "target_material": target_material,
        "category": "candidate-test",
        "chemistry_family": "candidate-test-family",
        "chemistry_status": status,
        "product_family": "candidate-test-product",
        "source_references": [{"type": "doi", "identifier": f"10.0000/{recipe_id}"}],
        "exposure_signature": signature or [item["id"] for item in precursors],
    }


def entries() -> list[dict[str, object]]:
    hf = p("A", "hafnium tetrachloride", "HfCl4", "hafnium source")
    zr = p("A", "zirconium tetrachloride", "ZrCl4", "zirconium source")
    tma = p("A", "trimethylaluminum", "Al(CH3)3", "aluminum source")
    water_b = p("B", "water", "H2O", "oxygen co-reactant")
    ozone_b = p("B", "ozone", "O3", "oxidant")
    water_c = p("C", "water", "H2O", "oxygen co-reactant")
    zr_b = p("B", "zirconium tetrachloride", "ZrCl4", "zirconium source")
    return [
        entry("hafnia-water", [hf, water_b], target_formula="HfO2", target_material="hafnium oxide"),
        entry("zirconia-water", [zr, water_b], target_formula="ZrO2", target_material="zirconium oxide"),
        entry("alumina-water", [tma, water_b], target_formula="Al2O3", target_material="aluminum oxide"),
        entry("alumina-ozone", [tma, ozone_b], target_formula="Al2O3", target_material="aluminum oxide"),
        entry(
            "hafnia-zirconia-water",
            [
                p("A", "hafnium tetrachloride", "HfCl4", "hafnium source"),
                zr_b,
                water_c,
            ],
            target_formula="HfZrO4",
            target_material="hafnium zirconium oxide surrogate",
            signature=["A", "C", "B"],
        ),
    ]


def snapshot(*, conflict: bool = False) -> dict[str, object]:
    overrides = []
    if conflict:
        overrides.append(
            {
                "graph": "precursor",
                "a": "ZrCl4",
                "b": "O3",
                "family": "external_thermochemistry",
                "value": -1.0,
                "reliability": 0.95,
                "source": {"type": "curated-test", "identifier": "conflict-zr-o3"},
            }
        )
    return compat.build_compatibility_snapshot(entries(), MODEL, overrides)


def formulas(candidate: dict[str, object]) -> set[str]:
    return {item["formula"] for item in candidate["precursors"]}


def test_rank_candidates_is_deterministic_and_bounded_to_requested_sizes():
    snap = snapshot()
    first = compat.rank_candidates(snap, min_size=2, max_size=4, top=30, beam_width=50)
    second = compat.rank_candidates(snap, min_size=2, max_size=4, top=30, beam_width=50)

    assert first == second
    assert first
    assert all(2 <= len(item["precursors"]) <= 4 for item in first)
    assert all(item["role_complete"] is True for item in first)
    assert len({item["id"] for item in first}) == len(first)


def test_conflicting_pair_is_rejected_from_every_candidate():
    ranked = compat.rank_candidates(snapshot(conflict=True), min_size=2, max_size=5, top=100, beam_width=100)

    assert ranked
    assert not any({"ZrCl4", "O3"}.issubset(formulas(item)) for item in ranked)


def test_known_catalog_set_receives_full_known_support_and_novel_filter_excludes_it():
    snap = snapshot()
    ranked = compat.rank_candidates(snap, min_size=2, max_size=2, top=100, beam_width=100)
    known = next(item for item in ranked if formulas(item) == {"HfCl4", "H2O"})

    assert known["known_support"] == pytest.approx(100.0)
    assert known["novel"] is False
    assert "hafnia-water" in known["matching_recipe_ids"]

    novel = compat.rank_candidates(
        snap,
        min_size=2,
        max_size=2,
        top=100,
        beam_width=100,
        novel_only=True,
    )
    assert novel
    assert all(item["novel"] is True for item in novel)
    assert not any(formulas(item) == {"HfCl4", "H2O"} for item in novel)


def test_candidate_explanation_exposes_weakest_pair_and_component_scores():
    explanation = compat.explain_candidate(snapshot(), ["HfCl4", "ZrCl4", "H2O"])

    assert formulas(explanation) == {"HfCl4", "ZrCl4", "H2O"}
    assert explanation["known_support"] == pytest.approx(100.0)
    assert explanation["weakest_pair"]["id"]
    assert set(explanation["components"]) == {"harmonic", "minimum", "coverage", "roles", "known"}
    assert len(explanation["pairs"]) == 3


def test_minimum_evidence_and_score_filters_are_enforced():
    snap = snapshot()
    e4 = compat.rank_candidates(
        snap,
        min_size=2,
        max_size=3,
        top=100,
        beam_width=100,
        minimum_evidence="E4_DIRECT",
    )
    assert e4
    assert all(item["evidence_level"] == "E4_DIRECT" for item in e4)

    high = compat.rank_candidates(
        snap,
        min_size=2,
        max_size=3,
        top=100,
        beam_width=100,
        minimum_score=90.0,
    )
    assert all(item["score"] >= 90.0 for item in high)


def test_search_matches_formula_name_or_alias():
    ranked = compat.rank_candidates(
        snapshot(),
        min_size=2,
        max_size=3,
        top=100,
        beam_width=100,
        search="hafnium",
    )
    assert ranked
    assert all("HfCl4" in formulas(item) for item in ranked)


def test_invalid_candidate_size_and_evidence_inputs_are_rejected():
    snap = snapshot()
    with pytest.raises(ValueError, match="2 through 6"):
        compat.rank_candidates(snap, min_size=1, max_size=6)
    with pytest.raises(ValueError, match="minimum_evidence"):
        compat.rank_candidates(snap, minimum_evidence="E99")
    with pytest.raises(ValueError, match="unique"):
        compat.explain_candidate(snap, ["H2O", "H2O"])
