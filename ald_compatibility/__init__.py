"""Public compatibility-engine facade and deterministic candidate ranking.

The legacy core implementation remains in the repository root module so the
TDD history stays reviewable.  This package facade loads that core, re-exports
its API, and adds bounded 2-6 precursor candidate search.  All outputs describe
evidence support for offline sequential simulation research only; they are not
chemical-mixing or process-safety determinations.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any


_CORE_PATH = Path(__file__).resolve().parent.parent / "ald_compatibility.py"
_SPEC = importlib.util.spec_from_file_location("_ald_compatibility_core", _CORE_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise ImportError(f"unable to load compatibility core from {_CORE_PATH}")
_core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_core)

# Preserve the established public/core API.  The ranking functions below are
# intentionally defined after this export so they override nothing in the core.
for _name, _value in vars(_core).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


_EVIDENCE_ORDER = {
    "E_CONFLICT": -1,
    "E0_UNKNOWN": 0,
    "E1_HEURISTIC": 1,
    "E2_ANALOGUE": 2,
    "E3_CORROBORATED": 3,
    "E4_DIRECT": 4,
}
_DEFAULT_CANDIDATE_WEIGHTS = {
    "harmonic": 0.40,
    "minimum": 0.20,
    "coverage": 0.15,
    "roles": 0.15,
    "known": 0.10,
}
_REACTANT_ROLES = {
    "OXIDANT",
    "REDUCTANT",
    "CHALCOGEN_REACTANT",
    "NITROGEN_REACTANT",
    "HALOGEN_REACTANT",
    "CARBON_REACTANT",
    "OTHER_REACTANT",
}


def build_compatibility_snapshot(entries, model, overrides):
    """Build a core snapshot and bind candidate-search configuration to it."""
    snapshot = _core.build_compatibility_snapshot(entries, model, overrides)
    snapshot["candidate_model"] = {
        "weights": {
            key: float(value)
            for key, value in sorted(model["candidate_weights"].items())
        },
        "beam_width": int(model["beam_width"]),
        "default_top": int(model["default_top"]),
    }
    return snapshot


def _candidate_config(snapshot: dict[str, Any] | Any) -> dict[str, Any]:
    raw = snapshot.get("candidate_model", {}) if hasattr(snapshot, "get") else {}
    raw_weights = raw.get("weights", {}) if hasattr(raw, "get") else {}
    weights = {
        key: float(raw_weights.get(key, default))
        for key, default in _DEFAULT_CANDIDATE_WEIGHTS.items()
    }
    return {
        "weights": weights,
        "beam_width": int(raw.get("beam_width", 500)),
        "default_top": int(raw.get("default_top", 20)),
    }


def _pair_index(snapshot: Any) -> dict[frozenset[str], dict[str, Any]]:
    result: dict[frozenset[str], dict[str, Any]] = {}
    for pair in snapshot.get("precursor_pairs", []):
        key = frozenset((str(pair["a"]["id"]), str(pair["b"]["id"])))
        result[key] = pair
    return result


def _recipe_sets(snapshot: Any) -> list[tuple[str, frozenset[str]]]:
    values: list[tuple[str, frozenset[str]]] = []
    for recipe in snapshot.get("recipes", []):
        recipe_id = str(recipe.get("recipe_id", ""))
        ids = frozenset(str(item) for item in recipe.get("precursor_ids", []))
        if recipe_id and ids:
            values.append((recipe_id, ids))
    values.sort(key=lambda item: item[0])
    return values


def _role_complete(entities: list[dict[str, Any]]) -> bool:
    roles = {str(role) for entity in entities for role in entity.get("roles", [])}
    return "SOURCE" in roles and bool(roles & _REACTANT_ROLES)


def _harmonic_mean(values: list[float]) -> float:
    if not values or any(value <= 0.0 for value in values):
        return 0.0
    return len(values) / sum(1.0 / value for value in values)


def _candidate_verdict(score: float, evidence_level: str) -> str:
    if evidence_level == "E_CONFLICT":
        return "CONFLICTING"
    if evidence_level == "E0_UNKNOWN":
        return "UNKNOWN"
    if score >= 75.0:
        return "SUPPORTED"
    if score >= 60.0:
        return "PLAUSIBLE"
    if score >= 45.0:
        return "UNCERTAIN"
    return "LOW_SUPPORT"


def _entity_matches_search(entity: dict[str, Any], search: str) -> bool:
    needle = normalize_name(search)
    formula_needle = normalize_formula(search).casefold()
    haystacks = [
        normalize_name(str(entity.get("name", ""))),
        str(entity.get("formula", "")).casefold(),
        *(normalize_name(str(alias)) for alias in entity.get("aliases", [])),
    ]
    return any(needle in value or formula_needle in value.casefold() for value in haystacks)


def _evaluate_candidate(
    snapshot: Any,
    entity_ids: tuple[str, ...],
    pair_index: dict[frozenset[str], dict[str, Any]],
    recipe_sets: list[tuple[str, frozenset[str]]],
    weights: dict[str, float],
) -> dict[str, Any]:
    entities_by_id = {str(item["id"]): item for item in snapshot.get("precursors", [])}
    entities = [entities_by_id[item] for item in entity_ids]
    pairs: list[dict[str, Any]] = []
    for left_index in range(len(entity_ids)):
        for right_index in range(left_index + 1, len(entity_ids)):
            key = frozenset((entity_ids[left_index], entity_ids[right_index]))
            pair = pair_index.get(key)
            if pair is None:
                raise ValueError("snapshot is missing an exhaustive precursor pair")
            pairs.append(pair)
    pairs.sort(key=lambda item: str(item["id"]))

    conflict = any(
        str(pair.get("evidence_level")) == "E_CONFLICT"
        or str(pair.get("verdict")) == "CONFLICTING"
        for pair in pairs
    )
    pair_scores = [float(pair.get("score", 0.0)) for pair in pairs]
    pair_coverages = [float(pair.get("coverage", 0.0)) for pair in pairs]
    harmonic = _harmonic_mean(pair_scores)
    minimum = min(pair_scores) if pair_scores else 0.0
    coverage = (
        100.0 * sum(pair_coverages) / len(pair_coverages)
        if pair_coverages
        else 0.0
    )
    role_complete = _role_complete(entities)
    candidate_set = frozenset(entity_ids)
    matching_recipe_ids = [
        recipe_id for recipe_id, recipe_set in recipe_sets if recipe_set == candidate_set
    ]
    known_support = 100.0 if matching_recipe_ids else 0.0
    components = {
        "harmonic": round(harmonic, 6),
        "minimum": round(minimum, 6),
        "coverage": round(coverage, 6),
        "roles": 100.0 if role_complete else 0.0,
        "known": known_support,
    }
    total_weight = sum(float(value) for value in weights.values())
    score = (
        0.0
        if total_weight <= 0.0
        else sum(float(weights[key]) * components[key] for key in components)
        / total_weight
    )
    if conflict:
        score = 0.0

    weakest_pair = min(
        pairs,
        key=lambda item: (
            float(item.get("score", 0.0)),
            float(item.get("coverage", 0.0)),
            str(item.get("id", "")),
        ),
    ) if pairs else None
    evidence_level = "E0_UNKNOWN"
    if pairs:
        evidence_level = min(
            (str(pair.get("evidence_level", "E0_UNKNOWN")) for pair in pairs),
            key=lambda level: _EVIDENCE_ORDER.get(level, -2),
        )
    if conflict:
        evidence_level = "E_CONFLICT"

    refs = [
        {
            "id": str(entity["id"]),
            "name": str(entity.get("name", "")),
            "formula": str(entity.get("formula", "")),
            "roles": sorted(str(role) for role in entity.get("roles", [])),
            "aliases": sorted(str(alias) for alias in entity.get("aliases", [])),
        }
        for entity in sorted(entities, key=lambda item: str(item["id"]))
    ]
    candidate_key = "|".join(sorted(entity_ids))
    return {
        "id": _core._stable_id("pc", candidate_key),
        "precursors": refs,
        "score": round(score, 6),
        "coverage": round(coverage, 6),
        "evidence_level": evidence_level,
        "verdict": _candidate_verdict(score, evidence_level),
        "role_complete": role_complete,
        "known_support": known_support,
        "novel": not bool(matching_recipe_ids),
        "matching_recipe_ids": matching_recipe_ids,
        "components": components,
        "weakest_pair": weakest_pair,
        "pairs": pairs,
        "conflict": conflict,
        "safety_notice": snapshot.get("safety_notice", _core.SAFETY_NOTICE),
    }


def explain_candidate(snapshot: Any, precursors: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Explain one explicit 2-6 precursor candidate from the exhaustive graph."""
    if not 2 <= len(precursors) <= 6:
        raise ValueError("candidate size must be 2 through 6")
    entities = snapshot.get("precursors", [])
    resolved = [_core._resolve_one(entities, str(query)) for query in precursors]
    ids = tuple(sorted(str(entity["id"]) for entity in resolved))
    if len(set(ids)) != len(ids):
        raise ValueError("candidate precursors must be unique")
    config = _candidate_config(snapshot)
    return _evaluate_candidate(
        snapshot,
        ids,
        _pair_index(snapshot),
        _recipe_sets(snapshot),
        config["weights"],
    )


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -float(candidate["score"]),
        -float(candidate["components"]["minimum"]),
        -float(candidate["components"]["coverage"]),
        -float(candidate["known_support"]),
        tuple(str(item["id"]) for item in candidate["precursors"]),
    )


def rank_candidates(
    snapshot: Any,
    *,
    min_size: int = 2,
    max_size: int = 6,
    top: int | None = None,
    beam_width: int | None = None,
    minimum_evidence: str = "E0_UNKNOWN",
    minimum_score: float = 0.0,
    novel_only: bool = False,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Rank bounded 2-6 precursor candidates using deterministic beam search.

    Every size-two candidate is considered before pruning.  Larger sets are
    expanded only from the current beam, which bounds combinatorial growth.
    Candidates containing any explicit E_CONFLICT pair are rejected.
    """
    if not (2 <= min_size <= 6 and 2 <= max_size <= 6 and min_size <= max_size):
        raise ValueError("candidate sizes must be ordered values from 2 through 6")
    if minimum_evidence not in _EVIDENCE_ORDER or minimum_evidence == "E_CONFLICT":
        raise ValueError("minimum_evidence must be E0_UNKNOWN through E4_DIRECT")
    if isinstance(minimum_score, bool) or not 0.0 <= float(minimum_score) <= 100.0:
        raise ValueError("minimum_score must be between 0 and 100")

    config = _candidate_config(snapshot)
    if top is None:
        top = config["default_top"]
    if beam_width is None:
        beam_width = config["beam_width"]
    if isinstance(top, bool) or int(top) < 1:
        raise ValueError("top must be a positive integer")
    if isinstance(beam_width, bool) or int(beam_width) < 1:
        raise ValueError("beam_width must be a positive integer")
    top = int(top)
    beam_width = int(beam_width)

    entities = sorted(snapshot.get("precursors", []), key=lambda item: str(item["id"]))
    entity_ids = [str(item["id"]) for item in entities]
    pair_index = _pair_index(snapshot)
    recipe_sets = _recipe_sets(snapshot)
    weights = config["weights"]
    search_text = str(search).strip() if search is not None else ""
    matching_search_ids = {
        str(entity["id"])
        for entity in entities
        if search_text and _entity_matches_search(entity, search_text)
    }
    if search_text and not matching_search_ids:
        return []

    accepted: list[dict[str, Any]] = []

    # Exhaustive pair layer: this is the complete basis of the bounded search.
    beam: list[dict[str, Any]] = []
    for left_index in range(len(entity_ids)):
        for right_index in range(left_index + 1, len(entity_ids)):
            ids = (entity_ids[left_index], entity_ids[right_index])
            candidate = _evaluate_candidate(snapshot, ids, pair_index, recipe_sets, weights)
            if candidate["conflict"]:
                continue
            beam.append(candidate)
    beam.sort(key=_candidate_sort_key)
    beam = beam[:beam_width]

    for size in range(2, max_size + 1):
        if size > 2:
            expanded: dict[tuple[str, ...], dict[str, Any]] = {}
            for parent in beam:
                parent_ids = tuple(sorted(str(item["id"]) for item in parent["precursors"]))
                last_position = entity_ids.index(parent_ids[-1])
                for new_id in entity_ids[last_position + 1 :]:
                    ids = tuple(sorted((*parent_ids, new_id)))
                    if len(ids) != size or ids in expanded:
                        continue
                    candidate = _evaluate_candidate(snapshot, ids, pair_index, recipe_sets, weights)
                    if candidate["conflict"]:
                        continue
                    expanded[ids] = candidate
            beam = sorted(expanded.values(), key=_candidate_sort_key)[:beam_width]

        if size < min_size:
            continue
        for candidate in beam:
            if len(candidate["precursors"]) != size:
                continue
            if not candidate["role_complete"]:
                continue
            if novel_only and not candidate["novel"]:
                continue
            if float(candidate["score"]) < float(minimum_score):
                continue
            if _EVIDENCE_ORDER[candidate["evidence_level"]] < _EVIDENCE_ORDER[minimum_evidence]:
                continue
            if search_text and not (
                {str(item["id"]) for item in candidate["precursors"]} & matching_search_ids
            ):
                continue
            accepted.append(candidate)

    # De-duplicate defensively across beam layers and keep deterministic ordering.
    unique = {str(candidate["id"]): candidate for candidate in accepted}
    ranked = sorted(unique.values(), key=_candidate_sort_key)
    return ranked[:top]


__all__ = sorted(
    name
    for name in globals()
    if not name.startswith("_") and name not in {"Any", "Path", "math"}
)
