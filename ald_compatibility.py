"""Deterministic evidence primitives for Substitute compatibility research.

This module evaluates evidence for offline sequential simulation research only.
It does not determine chemical mixing safety, reactor compatibility, physical
fabrication readiness, or equipment operating conditions.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import itertools
import json
from pathlib import Path
import unicodedata
from typing import Any


MODEL_SCHEMA = "ald-compatibility-model/1"
EVIDENCE_SCHEMA = "ald-compatibility-evidence/1"
SNAPSHOT_SCHEMA = "ald-compatibility-snapshot/1"
SAFETY_NOTICE = (
    "Compatibility scores describe evidence support for offline sequential "
    "simulation research; they are not chemical-mixing, equipment-safety, "
    "or production-readiness determinations."
)
_ROLE_PRIORITY = (
    "OXIDANT",
    "REDUCTANT",
    "CHALCOGEN_REACTANT",
    "NITROGEN_REACTANT",
    "HALOGEN_REACTANT",
    "CARBON_REACTANT",
    "SOURCE",
    "OTHER_REACTANT",
)
_REACTANT_CLASSES = {
    "OXIDANT",
    "REDUCTANT",
    "CHALCOGEN_REACTANT",
    "NITROGEN_REACTANT",
    "HALOGEN_REACTANT",
    "CARBON_REACTANT",
    "OTHER_REACTANT",
}


def normalize_formula(value: str) -> str:
    """Remove presentation whitespace without guessing chemical identity."""
    if not isinstance(value, str):
        raise ValueError("formula must be a string")
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value)
        if not character.isspace()
    )


def normalize_name(value: str) -> str:
    """Normalize a human chemical/material name for conservative alias lookup."""
    if not isinstance(value, str):
        raise ValueError("name must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _read_json_object(path: Path | str, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"unable to read {label} {source}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_weight_map(value: Any, label: str) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"model {label} must be a non-empty object")
    total = 0.0
    for family, weight in value.items():
        if not isinstance(family, str) or not family:
            raise ValueError(f"model {label} contains an invalid family name")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or float(weight) <= 0.0
        ):
            raise ValueError(f"model {label}.{family} must be positive")
        total += float(weight)
    if total <= 0.0:
        raise ValueError(f"model {label} must have positive total weight")


def validate_model(value: Mapping[str, Any]) -> dict[str, Any]:
    model = dict(value)
    if model.get("schema") != MODEL_SCHEMA:
        raise ValueError(
            f"unsupported compatibility model schema: {model.get('schema')!r}"
        )
    _validate_weight_map(model.get("precursor_weights"), "precursor_weights")
    _validate_weight_map(model.get("material_weights"), "material_weights")
    _validate_weight_map(model.get("candidate_weights"), "candidate_weights")

    coverage = model.get("coverage_unknown_below")
    if (
        isinstance(coverage, bool)
        or not isinstance(coverage, (int, float))
        or not 0.0 <= float(coverage) <= 1.0
    ):
        raise ValueError("model coverage_unknown_below must be between 0 and 1")

    thresholds = model.get("verdict_thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("model verdict_thresholds must be an object")
    for key in ("low_support", "plausible", "supported"):
        threshold = thresholds.get(key)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError(f"model verdict_thresholds.{key} must be numeric")

    if not isinstance(model.get("status_reliability"), dict):
        raise ValueError("model status_reliability must be an object")
    for status, reliability in model["status_reliability"].items():
        if (
            not isinstance(status, str)
            or isinstance(reliability, bool)
            or not isinstance(reliability, (int, float))
        ):
            raise ValueError("model status_reliability values must be numeric")
        if not 0.0 <= float(reliability) <= 1.0:
            raise ValueError(
                "model status_reliability values must be between 0 and 1"
            )

    role_keywords = model.get("role_keywords")
    if not isinstance(role_keywords, dict):
        raise ValueError("model role_keywords must be an object")
    for role_class, keywords in role_keywords.items():
        if (
            not isinstance(role_class, str)
            or not isinstance(keywords, list)
            or not all(isinstance(item, str) and item for item in keywords)
        ):
            raise ValueError(
                "model role_keywords values must be arrays of non-empty strings"
            )

    beam_width = model.get("beam_width")
    default_top = model.get("default_top")
    if (
        isinstance(beam_width, bool)
        or not isinstance(beam_width, int)
        or beam_width < 1
    ):
        raise ValueError("model beam_width must be a positive integer")
    if (
        isinstance(default_top, bool)
        or not isinstance(default_top, int)
        or default_top < 1
    ):
        raise ValueError("model default_top must be a positive integer")
    return model


def load_model(path: Path | str) -> dict[str, Any]:
    return validate_model(_read_json_object(path, "compatibility model"))


def load_evidence_overrides(path: Path | str) -> list[dict[str, Any]]:
    payload = _read_json_object(path, "compatibility evidence")
    if payload.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError(
            f"unsupported compatibility evidence schema: {payload.get('schema')!r}"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("compatibility evidence records must be an array")

    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ValueError(f"evidence record {index} must be an object")
        graph = raw.get("graph")
        if graph not in {"precursor", "material"}:
            raise ValueError(
                f"evidence record {index} graph must be precursor or material"
            )
        for field in ("a", "b", "family"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ValueError(
                    f"evidence record {index} {field} must be a non-empty string"
                )
        value = raw.get("value")
        reliability = raw.get("reliability")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not -1.0 <= float(value) <= 1.0
        ):
            raise ValueError(
                f"evidence record {index} value must be between -1 and 1"
            )
        if (
            isinstance(reliability, bool)
            or not isinstance(reliability, (int, float))
            or not 0.0 <= float(reliability) <= 1.0
        ):
            raise ValueError(
                f"evidence record {index} reliability must be between 0 and 1"
            )
        source = raw.get("source")
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("type"), str)
            or not isinstance(source.get("identifier"), str)
        ):
            raise ValueError(
                f"evidence record {index} source must contain type and identifier"
            )
        item = dict(raw)
        item["value"] = float(value)
        item["reliability"] = float(reliability)
        validated.append(item)
    return validated


def classify_role(role: str, model: Mapping[str, Any]) -> str:
    text = normalize_name(role)
    keywords = model.get("role_keywords", {})
    if not isinstance(keywords, Mapping):
        return "OTHER"
    for role_class in _ROLE_PRIORITY:
        values = keywords.get(role_class, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            for keyword in values:
                if (
                    isinstance(keyword, str)
                    and normalize_name(keyword) in text
                ):
                    return role_class
    return "OTHER"


def _canonical_display(values: set[str], *, fallback: str = "") -> str:
    if not values:
        return fallback
    return sorted(values, key=lambda item: (normalize_name(item), item))[0]


def _reference_key(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    source_type = value.get("type")
    identifier = value.get("identifier")
    if not isinstance(source_type, str) or not isinstance(identifier, str):
        return None
    return source_type, identifier


def build_precursor_entities(
    entries: Sequence[dict[str, Any]], model: Mapping[str, Any]
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for entry in entries:
        recipe_id = str(entry.get("recipe_id", ""))
        status = str(entry.get("chemistry_status", ""))
        category = str(entry.get("category", ""))
        family = str(entry.get("chemistry_family", ""))
        references = entry.get("source_references", [])
        for precursor in entry.get("precursors", []):
            if not isinstance(precursor, Mapping):
                continue
            raw_name = str(precursor.get("name", "")).strip()
            raw_formula = str(precursor.get("formula", "")).strip()
            formula = normalize_formula(raw_formula) if raw_formula else ""
            name_key = normalize_name(raw_name) if raw_name else ""
            if not formula and not name_key:
                continue
            entity_key = (
                f"formula:{formula}" if formula else f"name:{name_key}"
            )
            bucket = buckets.setdefault(
                entity_key,
                {
                    "names": set(),
                    "formulas": set(),
                    "roles": set(),
                    "recipe_ids": set(),
                    "chemistry_statuses": set(),
                    "categories": set(),
                    "chemistry_families": set(),
                    "source_references": set(),
                },
            )
            if raw_name:
                bucket["names"].add(raw_name)
            if formula:
                bucket["formulas"].add(formula)
            raw_role = str(precursor.get("role", ""))
            bucket["roles"].add(classify_role(raw_role, model))
            if recipe_id:
                bucket["recipe_ids"].add(recipe_id)
            if status:
                bucket["chemistry_statuses"].add(status)
            if category:
                bucket["categories"].add(category)
            if family:
                bucket["chemistry_families"].add(family)
            if isinstance(references, list):
                for reference in references:
                    key = _reference_key(reference)
                    if key is not None:
                        bucket["source_references"].add(key)

    entities: list[dict[str, Any]] = []
    for entity_key in sorted(buckets):
        bucket = buckets[entity_key]
        references = [
            {"type": source_type, "identifier": identifier}
            for source_type, identifier in sorted(bucket["source_references"])
        ]
        entities.append(
            {
                "id": _stable_id("p", entity_key),
                "key": entity_key,
                "name": _canonical_display(bucket["names"]),
                "formula": (
                    sorted(bucket["formulas"])[0]
                    if bucket["formulas"]
                    else ""
                ),
                "aliases": sorted(
                    bucket["names"],
                    key=lambda item: (normalize_name(item), item),
                ),
                "roles": sorted(bucket["roles"]),
                "recipe_ids": sorted(bucket["recipe_ids"]),
                "chemistry_statuses": sorted(
                    bucket["chemistry_statuses"]
                ),
                "categories": sorted(bucket["categories"]),
                "chemistry_families": sorted(
                    bucket["chemistry_families"]
                ),
                "source_references": references,
            }
        )
    return sorted(entities, key=lambda item: item["id"])


def build_material_entities(
    entries: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    base_buckets: dict[str, dict[str, Any]] = {}
    composites: list[dict[str, Any]] = []
    for entry in entries:
        raw_formula = str(entry.get("target_formula", "")).strip()
        raw_name = str(entry.get("target_material", "")).strip()
        if not raw_formula and not raw_name:
            continue
        if "/" in raw_formula:
            components = [
                normalize_formula(part)
                for part in raw_formula.split("/")
                if normalize_formula(part)
            ]
            composites.append(
                {
                    "recipe_id": str(entry.get("recipe_id", "")),
                    "formula": normalize_formula(raw_formula),
                    "name": raw_name,
                    "components": components,
                    "chemistry_status": str(
                        entry.get("chemistry_status", "")
                    ),
                    "chemistry_family": str(
                        entry.get("chemistry_family", "")
                    ),
                    "source_references": [
                        dict(item)
                        for item in entry.get("source_references", [])
                        if isinstance(item, Mapping)
                    ],
                }
            )
            continue

        formula = normalize_formula(raw_formula) if raw_formula else ""
        name_key = normalize_name(raw_name) if raw_name else ""
        entity_key = f"formula:{formula}" if formula else f"name:{name_key}"
        bucket = base_buckets.setdefault(
            entity_key,
            {
                "names": set(),
                "formulas": set(),
                "recipe_ids": set(),
                "categories": set(),
                "chemistry_families": set(),
                "product_families": set(),
            },
        )
        if raw_name:
            bucket["names"].add(raw_name)
        if formula:
            bucket["formulas"].add(formula)
        for field, target in (
            ("recipe_id", "recipe_ids"),
            ("category", "categories"),
            ("chemistry_family", "chemistry_families"),
            ("product_family", "product_families"),
        ):
            value = entry.get(field)
            if isinstance(value, str) and value:
                bucket[target].add(value)

    base: list[dict[str, Any]] = []
    for entity_key in sorted(base_buckets):
        bucket = base_buckets[entity_key]
        base.append(
            {
                "id": _stable_id("m", entity_key),
                "key": entity_key,
                "name": _canonical_display(bucket["names"]),
                "formula": (
                    sorted(bucket["formulas"])[0]
                    if bucket["formulas"]
                    else ""
                ),
                "aliases": sorted(
                    bucket["names"],
                    key=lambda item: (normalize_name(item), item),
                ),
                "recipe_ids": sorted(bucket["recipe_ids"]),
                "categories": sorted(bucket["categories"]),
                "chemistry_families": sorted(
                    bucket["chemistry_families"]
                ),
                "product_families": sorted(bucket["product_families"]),
            }
        )

    return {
        "base": sorted(
            base, key=lambda item: item["formula"] or item["name"]
        ),
        "composites": sorted(
            composites,
            key=lambda item: (item["formula"], item["recipe_id"]),
        ),
    }


def _status_reliability(status: str, model: Mapping[str, Any]) -> float:
    values = model.get("status_reliability", {})
    if not isinstance(values, Mapping):
        return 0.5
    raw = values.get(status, values.get("default", 0.5))
    return max(0.0, min(1.0, float(raw)))


def _empty_features(weights: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        family: {
            "family": family,
            "available": False,
            "value": 0.0,
            "reliability": 0.0,
            "sources": [],
            "note": "",
        }
        for family in weights
    }


def _set_feature(
    features: dict[str, dict[str, Any]],
    family: str,
    *,
    value: float,
    reliability: float,
    sources: Sequence[Mapping[str, Any]] = (),
    note: str = "",
) -> None:
    if family not in features:
        raise ValueError(f"unknown evidence family: {family}")
    value = max(-1.0, min(1.0, float(value)))
    reliability = max(0.0, min(1.0, float(reliability)))
    source_values = []
    seen = set()
    for source in sources:
        item = {
            key: source[key]
            for key in sorted(source)
            if isinstance(key, str)
            and isinstance(source[key], (str, int, float, bool))
        }
        token = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if token not in seen:
            seen.add(token)
            source_values.append(item)
    source_values.sort(key=lambda item: json.dumps(item, sort_keys=True))
    features[family] = {
        "family": family,
        "available": True,
        "value": round(value, 6),
        "reliability": round(reliability, 6),
        "sources": source_values,
        "note": note,
    }


def _merge_feature(
    features: dict[str, dict[str, Any]],
    family: str,
    *,
    value: float,
    reliability: float,
    sources: Sequence[Mapping[str, Any]] = (),
    note: str = "",
) -> None:
    current = features.get(family)
    if current is None:
        raise ValueError(f"unknown evidence family: {family}")
    if not current["available"]:
        _set_feature(
            features,
            family,
            value=value,
            reliability=reliability,
            sources=sources,
            note=note,
        )
        return
    old_rel = float(current["reliability"])
    new_rel = max(0.0, min(1.0, float(reliability)))
    denominator = old_rel + new_rel
    merged_value = (
        float(current["value"])
        if denominator == 0.0
        else (
            float(current["value"]) * old_rel + float(value) * new_rel
        )
        / denominator
    )
    merged_sources = [
        *[item for item in current.get("sources", []) if isinstance(item, Mapping)],
        *sources,
    ]
    merged_note = "; ".join(
        part
        for part in (str(current.get("note", "")).strip(), note.strip())
        if part
    )
    _set_feature(
        features,
        family,
        value=merged_value,
        reliability=max(old_rel, new_rel),
        sources=merged_sources,
        note=merged_note,
    )


def score_evidence(
    features: Sequence[Mapping[str, Any]], weights: Mapping[str, Any]
) -> tuple[float, float]:
    """Return (compatibility score, evidence coverage)."""
    numerator = 0.0
    denominator = 0.0
    available_weight = 0.0
    total_weight = sum(float(weight) for weight in weights.values())
    for feature in features:
        family = feature.get("family")
        if family not in weights or not feature.get("available"):
            continue
        weight = float(weights[family])
        reliability = max(
            0.0, min(1.0, float(feature.get("reliability", 0.0)))
        )
        value = max(-1.0, min(1.0, float(feature.get("value", 0.0))))
        numerator += weight * reliability * value
        denominator += weight * reliability
        available_weight += weight
    raw = 0.0 if denominator == 0.0 else numerator / denominator
    score = max(0.0, min(100.0, 50.0 * (raw + 1.0)))
    coverage = 0.0 if total_weight == 0.0 else available_weight / total_weight
    return round(score, 6), round(coverage, 6)


def _entity_ref(entity: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": str(entity["id"]),
        "name": str(entity.get("name", "")),
        "formula": str(entity.get("formula", "")),
    }


def _precursor_key_from_raw(precursor: Mapping[str, Any]) -> str | None:
    raw_formula = str(precursor.get("formula", "")).strip()
    raw_name = str(precursor.get("name", "")).strip()
    if raw_formula:
        return f"formula:{normalize_formula(raw_formula)}"
    if raw_name:
        return f"name:{normalize_name(raw_name)}"
    return None


def _canonical_entries(
    entries: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        [dict(entry) for entry in entries],
        key=lambda item: (
            str(item.get("recipe_id", "")),
            str(item.get("path", "")),
            canonical_json_bytes(item),
        ),
    )


def _build_recipe_index(
    entries: Sequence[dict[str, Any]],
    precursor_entities: Sequence[dict[str, Any]],
    model: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    by_key = {str(entity["key"]): str(entity["id"]) for entity in precursor_entities}
    recipes: list[dict[str, Any]] = []
    exact_neighbors: dict[str, set[str]] = {
        str(entity["id"]): set() for entity in precursor_entities
    }
    entity_recipes: dict[str, set[str]] = {
        str(entity["id"]): set() for entity in precursor_entities
    }

    for entry in _canonical_entries(entries):
        id_map: dict[str, str] = {}
        precursor_ids: list[str] = []
        for raw in entry.get("precursors", []):
            if not isinstance(raw, Mapping):
                continue
            key = _precursor_key_from_raw(raw)
            if key is None or key not in by_key:
                continue
            entity_id = by_key[key]
            raw_id = raw.get("id")
            if isinstance(raw_id, str):
                id_map[raw_id] = entity_id
            if entity_id not in precursor_ids:
                precursor_ids.append(entity_id)

        recipe_id = str(entry.get("recipe_id", ""))
        precursor_ids = sorted(precursor_ids)
        for a, b in itertools.combinations(precursor_ids, 2):
            exact_neighbors[a].add(b)
            exact_neighbors[b].add(a)
        for entity_id in precursor_ids:
            if recipe_id:
                entity_recipes[entity_id].add(recipe_id)

        exposure = []
        for token in entry.get("exposure_signature", []):
            if isinstance(token, str) and token in id_map:
                exposure.append(id_map[token])

        sources = [
            dict(source)
            for source in entry.get("source_references", [])
            if isinstance(source, Mapping)
        ]
        recipes.append(
            {
                "recipe_id": recipe_id,
                "precursor_ids": precursor_ids,
                "exposure_ids": exposure,
                "chemistry_status": str(entry.get("chemistry_status", "")),
                "status_reliability": _status_reliability(
                    str(entry.get("chemistry_status", "")), model
                ),
                "source_references": sorted(
                    sources,
                    key=lambda item: json.dumps(
                        item, sort_keys=True, separators=(",", ":")
                    ),
                ),
                "target_formula": normalize_formula(
                    str(entry.get("target_formula", ""))
                ),
                "target_material": str(entry.get("target_material", "")),
                "category": str(entry.get("category", "")),
                "chemistry_family": str(
                    entry.get("chemistry_family", "")
                ),
                "product_family": str(entry.get("product_family", "")),
            }
        )
    return recipes, exact_neighbors, entity_recipes


def _cooccurring_recipes(
    recipes: Sequence[Mapping[str, Any]], a: str, b: str
) -> list[Mapping[str, Any]]:
    return [
        recipe
        for recipe in recipes
        if a in recipe.get("precursor_ids", [])
        and b in recipe.get("precursor_ids", [])
    ]


def _surface_sequence_value(
    recipes: Sequence[Mapping[str, Any]], a: str, b: str
) -> tuple[float, float, list[dict[str, Any]], str] | None:
    relevant = _cooccurring_recipes(recipes, a, b)
    if not relevant:
        return None
    adjacent = False
    sources = []
    reliability = 0.0
    for recipe in relevant:
        exposure = list(recipe.get("exposure_ids", []))
        for left, right in zip(exposure, exposure[1:]):
            if {left, right} == {a, b}:
                adjacent = True
                break
        reliability = max(
            reliability, float(recipe.get("status_reliability", 0.0))
        )
        sources.append(
            {
                "type": "catalog-recipe",
                "identifier": str(recipe.get("recipe_id", "")),
            }
        )
    value = 1.0 if adjacent else 0.4
    note = (
        "pair appears adjacently in a catalog exposure sequence"
        if adjacent
        else "pair co-occurs in a catalog recipe but not adjacently"
    )
    return value, reliability, sources, note


def _role_feature(
    a: Mapping[str, Any], b: Mapping[str, Any]
) -> tuple[float, float, str] | None:
    roles_a = set(a.get("roles", []))
    roles_b = set(b.get("roles", []))
    if not roles_a or not roles_b:
        return None
    a_source = "SOURCE" in roles_a
    b_source = "SOURCE" in roles_b
    a_reactant = bool(roles_a & _REACTANT_CLASSES)
    b_reactant = bool(roles_b & _REACTANT_CLASSES)
    if (a_source and b_reactant) or (b_source and a_reactant):
        return 0.8, 0.6, "broad source/reactant role complementarity"
    if a_source and b_source:
        return 0.2, 0.4, "two source-class precursors; weak heuristic support only"
    if a_reactant and b_reactant:
        return 0.1, 0.35, "two reactant-class precursors; weak heuristic support only"
    return None


def _evidence_level(
    features: Mapping[str, Mapping[str, Any]],
    *,
    direct_family: str,
    analogue_family: str,
    conflict: bool,
    direct_statuses: Sequence[str] = (),
) -> str:
    if conflict:
        return "E_CONFLICT"
    direct = features.get(direct_family, {})
    literature = features.get("direct_literature", {})
    direct_status = any(
        status in {
            "established",
            "literature-grounded",
            "literature-grounded-surrogate",
        }
        for status in direct_statuses
    )
    if (
        direct.get("available")
        and literature.get("available")
        and direct_status
    ):
        return "E4_DIRECT"
    if direct.get("available"):
        other = sum(
            1
            for family, feature in features.items()
            if family != direct_family and feature.get("available")
        )
        if other:
            return "E3_CORROBORATED"
    if features.get(analogue_family, {}).get("available"):
        return "E2_ANALOGUE"
    if any(feature.get("available") for feature in features.values()):
        return "E1_HEURISTIC"
    return "E0_UNKNOWN"


def _verdict(
    score: float,
    coverage: float,
    level: str,
    model: Mapping[str, Any],
) -> str:
    if level == "E_CONFLICT":
        return "CONFLICTING"
    if coverage < float(model["coverage_unknown_below"]):
        return "UNKNOWN"
    thresholds = model["verdict_thresholds"]
    if score < float(thresholds["low_support"]):
        return "LOW_SUPPORT"
    if score < float(thresholds["plausible"]):
        return "UNCERTAIN"
    if score < float(thresholds["supported"]):
        return "PLAUSIBLE"
    return "SUPPORTED"


def _apply_precursor_overrides(
    features: dict[str, dict[str, Any]],
    overrides: Sequence[Mapping[str, Any]],
    a_entity: Mapping[str, Any],
    b_entity: Mapping[str, Any],
    resolver: Mapping[str, set[str]],
) -> bool:
    conflict = False
    a_id = str(a_entity["id"])
    b_id = str(b_entity["id"])
    for record in overrides:
        if record.get("graph") != "precursor":
            continue
        family = str(record.get("family", ""))
        if family not in features:
            raise ValueError(
                f"unknown precursor evidence family in override: {family}"
            )
        resolved_a = _resolve_ids(resolver, str(record.get("a", "")))
        resolved_b = _resolve_ids(resolver, str(record.get("b", "")))
        if len(resolved_a) != 1 or len(resolved_b) != 1:
            raise ValueError(
                "precursor evidence override must resolve each endpoint uniquely"
            )
        if {next(iter(resolved_a)), next(iter(resolved_b))} != {a_id, b_id}:
            continue
        value = float(record["value"])
        reliability = float(record["reliability"])
        _merge_feature(
            features,
            family,
            value=value,
            reliability=reliability,
            sources=[record["source"]],
            note=str(record.get("note", "curated evidence override")),
        )
        if value <= -0.75 and reliability >= 0.75:
            conflict = True
    return conflict


def _resolver_index(
    entities: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    resolver: dict[str, set[str]] = {}
    for entity in entities:
        entity_id = str(entity["id"])
        tokens = {entity_id}
        formula = str(entity.get("formula", ""))
        if formula:
            tokens.add(formula)
            tokens.add(normalize_formula(formula))
        name = str(entity.get("name", ""))
        if name:
            tokens.add(normalize_name(name))
        for alias in entity.get("aliases", []):
            if isinstance(alias, str):
                tokens.add(normalize_name(alias))
        for token in tokens:
            resolver.setdefault(token, set()).add(entity_id)
    return resolver


def _resolve_ids(
    resolver: Mapping[str, set[str]], query: str
) -> set[str]:
    candidates = set()
    raw = query.strip()
    for token in (
        raw,
        normalize_formula(raw),
        normalize_name(raw),
    ):
        candidates.update(resolver.get(token, set()))
    return candidates


def _resolve_one(
    entities: Sequence[Mapping[str, Any]], query: str
) -> Mapping[str, Any]:
    resolver = _resolver_index(entities)
    ids = _resolve_ids(resolver, query)
    if not ids:
        raise ValueError(f"unknown compatibility entity: {query}")
    if len(ids) > 1:
        names = [
            str(entity.get("formula") or entity.get("name"))
            for entity in entities
            if entity["id"] in ids
        ]
        raise ValueError(
            f"ambiguous compatibility entity {query!r}: {', '.join(sorted(names))}"
        )
    entity_id = next(iter(ids))
    return next(entity for entity in entities if entity["id"] == entity_id)


def _precursor_pair_record(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    recipes: Sequence[Mapping[str, Any]],
    exact_neighbors: Mapping[str, set[str]],
    model: Mapping[str, Any],
    overrides: Sequence[Mapping[str, Any]],
    resolver: Mapping[str, set[str]],
) -> dict[str, Any]:
    weights = model["precursor_weights"]
    features = _empty_features(weights)
    a_id = str(a["id"])
    b_id = str(b["id"])
    relevant = _cooccurring_recipes(recipes, a_id, b_id)
    statuses = [
        str(recipe.get("chemistry_status", "")) for recipe in relevant
    ]
    if relevant:
        reliability = max(
            float(recipe.get("status_reliability", 0.0))
            for recipe in relevant
        )
        _set_feature(
            features,
            "exact_process",
            value=1.0,
            reliability=reliability,
            sources=[
                {
                    "type": "catalog-recipe",
                    "identifier": str(recipe.get("recipe_id", "")),
                }
                for recipe in relevant
            ],
            note="exact precursor pair co-occurs in catalog recipe(s)",
        )
        references = []
        for recipe in relevant:
            references.extend(
                item
                for item in recipe.get("source_references", [])
                if isinstance(item, Mapping)
            )
        if references:
            _set_feature(
                features,
                "direct_literature",
                value=1.0,
                reliability=reliability,
                sources=references,
                note="co-occurring catalog recipe supplies source reference(s)",
            )

        surface = _surface_sequence_value(recipes, a_id, b_id)
        if surface is not None:
            value, sequence_rel, sources, note = surface
            _set_feature(
                features,
                "surface_sequence",
                value=value,
                reliability=sequence_rel,
                sources=sources,
                note=note,
            )

    role = _role_feature(a, b)
    if role is not None:
        value, reliability, note = role
        _set_feature(
            features,
            "role_complementarity",
            value=value,
            reliability=reliability,
            sources=[],
            note=note,
        )

    neighbors_a = exact_neighbors.get(a_id, set())
    neighbors_b = exact_neighbors.get(b_id, set())
    union = neighbors_a | neighbors_b
    shared = (neighbors_a & neighbors_b) - {a_id, b_id}
    if shared and union:
        jaccard = len(shared) / len(union)
        _set_feature(
            features,
            "chemistry_analogue",
            value=min(1.0, 0.35 + jaccard),
            reliability=0.5,
            sources=[
                {"type": "catalog-neighbor", "identifier": item}
                for item in sorted(shared)
            ],
            note="pair shares catalog process neighbors",
        )

    conflict = _apply_precursor_overrides(
        features, overrides, a, b, resolver
    )
    feature_list = [features[family] for family in weights]
    score, coverage = score_evidence(feature_list, weights)
    level = _evidence_level(
        features,
        direct_family="exact_process",
        analogue_family="chemistry_analogue",
        conflict=conflict,
        direct_statuses=statuses,
    )
    verdict = _verdict(score, coverage, level, model)
    endpoints = sorted((a_id, b_id))
    return {
        "id": _stable_id("pp", "|".join(endpoints)),
        "a": _entity_ref(a),
        "b": _entity_ref(b),
        "features": feature_list,
        "score": score,
        "coverage": coverage,
        "evidence_level": level,
        "verdict": verdict,
        "recipe_ids": sorted(
            {
                str(recipe.get("recipe_id", ""))
                for recipe in relevant
                if recipe.get("recipe_id")
            }
        ),
    }


def _material_recipe_precursors(
    recipes: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for recipe in recipes:
        formula = str(recipe.get("target_formula", ""))
        if not formula or "/" in formula:
            continue
        result.setdefault(formula, set()).update(
            str(item) for item in recipe.get("precursor_ids", [])
        )
    return result


def _material_composite_support(
    composites: Sequence[Mapping[str, Any]],
    a_formula: str,
    b_formula: str,
    model: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], float]:
    supporting = []
    reliability = 0.0
    for composite in composites:
        components = list(composite.get("components", []))
        if a_formula in components and b_formula in components:
            supporting.append(composite)
            reliability = max(
                reliability,
                _status_reliability(
                    str(composite.get("chemistry_status", "")), model
                ),
            )
    return supporting, reliability


def _apply_material_overrides(
    features: dict[str, dict[str, Any]],
    overrides: Sequence[Mapping[str, Any]],
    a_entity: Mapping[str, Any],
    b_entity: Mapping[str, Any],
    resolver: Mapping[str, set[str]],
) -> bool:
    conflict = False
    a_id = str(a_entity["id"])
    b_id = str(b_entity["id"])
    for record in overrides:
        if record.get("graph") != "material":
            continue
        family = str(record.get("family", ""))
        if family not in features:
            raise ValueError(
                f"unknown material evidence family in override: {family}"
            )
        resolved_a = _resolve_ids(resolver, str(record.get("a", "")))
        resolved_b = _resolve_ids(resolver, str(record.get("b", "")))
        if len(resolved_a) != 1 or len(resolved_b) != 1:
            raise ValueError(
                "material evidence override must resolve each endpoint uniquely"
            )
        source_a = next(iter(resolved_a))
        source_b = next(iter(resolved_b))
        directional = bool(record.get("directional", False))
        matches = (
            source_a == a_id and source_b == b_id
            if directional
            else {source_a, source_b} == {a_id, b_id}
        )
        if not matches:
            continue
        value = float(record["value"])
        reliability = float(record["reliability"])
        _merge_feature(
            features,
            family,
            value=value,
            reliability=reliability,
            sources=[record["source"]],
            note=str(record.get("note", "curated evidence override")),
        )
        if value <= -0.75 and reliability >= 0.75:
            conflict = True
    return conflict


def _material_interface_record(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    composites: Sequence[Mapping[str, Any]],
    material_precursors: Mapping[str, set[str]],
    model: Mapping[str, Any],
    overrides: Sequence[Mapping[str, Any]],
    resolver: Mapping[str, set[str]],
) -> dict[str, Any]:
    weights = model["material_weights"]
    features = _empty_features(weights)
    a_formula = str(a.get("formula", ""))
    b_formula = str(b.get("formula", ""))
    supporting, reliability = _material_composite_support(
        composites, a_formula, b_formula, model
    )
    statuses = [
        str(item.get("chemistry_status", "")) for item in supporting
    ]
    if supporting:
        sources = [
            {
                "type": "catalog-recipe",
                "identifier": str(item.get("recipe_id", "")),
            }
            for item in supporting
        ]
        _set_feature(
            features,
            "direct_stack",
            value=1.0,
            reliability=reliability,
            sources=sources,
            note=(
                "materials occur as resolved constituents of a catalog "
                "composite target; source direction is not established"
            ),
        )
        refs = []
        for item in supporting:
            refs.extend(
                source
                for source in item.get("source_references", [])
                if isinstance(source, Mapping)
            )
        if refs:
            _set_feature(
                features,
                "direct_literature",
                value=1.0,
                reliability=reliability,
                sources=refs,
                note="composite catalog entry supplies source reference(s)",
            )

    precursor_a = material_precursors.get(a_formula, set())
    precursor_b = material_precursors.get(b_formula, set())
    if precursor_a and precursor_b:
        union = precursor_a | precursor_b
        shared = precursor_a & precursor_b
        if shared and union:
            jaccard = len(shared) / len(union)
            _set_feature(
                features,
                "shared_precursors",
                value=min(0.8, 0.2 + 0.6 * jaccard),
                reliability=0.5,
                sources=[
                    {"type": "precursor-entity", "identifier": item}
                    for item in sorted(shared)
                ],
                note="base material recipes share precursor entities",
            )

    family_overlap = set(a.get("chemistry_families", [])) & set(
        b.get("chemistry_families", [])
    )
    category_overlap = set(a.get("categories", [])) & set(
        b.get("categories", [])
    )
    product_overlap = set(a.get("product_families", [])) & set(
        b.get("product_families", [])
    )
    if family_overlap or category_overlap or product_overlap:
        signals = sum(
            bool(value)
            for value in (
                family_overlap,
                category_overlap,
                product_overlap,
            )
        )
        _set_feature(
            features,
            "family_analogue",
            value=min(0.7, 0.25 + 0.15 * signals),
            reliability=0.4,
            sources=[],
            note="materials share catalog family/category/product metadata",
        )

    conflict = _apply_material_overrides(
        features, overrides, a, b, resolver
    )
    feature_list = [features[family] for family in weights]
    score, coverage = score_evidence(feature_list, weights)
    level = _evidence_level(
        features,
        direct_family="direct_stack",
        analogue_family="family_analogue",
        conflict=conflict,
        direct_statuses=statuses,
    )
    verdict = _verdict(score, coverage, level, model)
    return {
        "id": _stable_id(
            "mi", f"{a['id']}->{b['id']}"
        ),
        "a": _entity_ref(a),
        "b": _entity_ref(b),
        "features": feature_list,
        "score": score,
        "coverage": coverage,
        "evidence_level": level,
        "verdict": verdict,
        "recipe_ids": sorted(
            {
                str(item.get("recipe_id", ""))
                for item in supporting
                if item.get("recipe_id")
            }
        ),
    }


def _histogram(
    records: Sequence[Mapping[str, Any]], field: str
) -> dict[str, int]:
    counts = Counter(str(record.get(field, "")) for record in records)
    return {key: counts[key] for key in sorted(counts) if key}


def build_compatibility_snapshot(
    entries: Sequence[dict[str, Any]],
    model: Mapping[str, Any],
    overrides: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the exhaustive deterministic evidence snapshot."""
    checked_model = validate_model(model)
    canonical_entries = _canonical_entries(entries)
    normalized_overrides = sorted(
        [dict(record) for record in overrides],
        key=lambda item: canonical_json_bytes(item),
    )

    precursor_entities = build_precursor_entities(
        canonical_entries, checked_model
    )
    material_data = build_material_entities(canonical_entries)
    materials = material_data["base"]
    composites = material_data["composites"]

    recipes, exact_neighbors, _entity_recipes = _build_recipe_index(
        canonical_entries, precursor_entities, checked_model
    )
    precursor_resolver = _resolver_index(precursor_entities)
    material_resolver = _resolver_index(materials)

    precursor_pairs = [
        _precursor_pair_record(
            a,
            b,
            recipes,
            exact_neighbors,
            checked_model,
            normalized_overrides,
            precursor_resolver,
        )
        for a, b in itertools.combinations(
            sorted(precursor_entities, key=lambda item: item["id"]), 2
        )
    ]

    material_precursors = _material_recipe_precursors(recipes)
    material_interfaces = []
    sorted_materials = sorted(materials, key=lambda item: item["id"])
    for a in sorted_materials:
        for b in sorted_materials:
            if a["id"] == b["id"]:
                continue
            material_interfaces.append(
                _material_interface_record(
                    a,
                    b,
                    composites,
                    material_precursors,
                    checked_model,
                    normalized_overrides,
                    material_resolver,
                )
            )

    precursor_pairs.sort(key=lambda item: item["id"])
    material_interfaces.sort(key=lambda item: item["id"])
    recipes.sort(key=lambda item: item["recipe_id"])

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "safety_notice": SAFETY_NOTICE,
        "model_digest": _digest(checked_model),
        "catalog_digest": _digest(canonical_entries),
        "evidence_digest": _digest(normalized_overrides),
        "precursors": sorted(
            precursor_entities, key=lambda item: item["id"]
        ),
        "materials": sorted(materials, key=lambda item: item["id"]),
        "recipes": recipes,
        "precursor_pairs": precursor_pairs,
        "material_interfaces": material_interfaces,
        "summary": {
            "unique_precursors": len(precursor_entities),
            "precursor_pairs": len(precursor_pairs),
            "unique_materials": len(materials),
            "directed_material_interfaces": len(material_interfaces),
            "precursor_verdicts": _histogram(
                precursor_pairs, "verdict"
            ),
            "precursor_evidence_levels": _histogram(
                precursor_pairs, "evidence_level"
            ),
            "material_verdicts": _histogram(
                material_interfaces, "verdict"
            ),
            "material_evidence_levels": _histogram(
                material_interfaces, "evidence_level"
            ),
        },
    }
    return snapshot


def query_precursor(
    snapshot: Mapping[str, Any],
    a: str,
    b: str | None = None,
    top: int = 20,
) -> Any:
    entities = snapshot.get("precursors", [])
    entity_a = _resolve_one(entities, a)
    a_id = str(entity_a["id"])
    pairs = snapshot.get("precursor_pairs", [])
    if b is not None:
        entity_b = _resolve_one(entities, b)
        wanted = {a_id, str(entity_b["id"])}
        for pair in pairs:
            if {pair["a"]["id"], pair["b"]["id"]} == wanted:
                return pair
        raise ValueError(f"precursor pair not found: {a}, {b}")
    related = [
        pair
        for pair in pairs
        if a_id in {pair["a"]["id"], pair["b"]["id"]}
    ]
    related.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item["coverage"]),
            str(item["id"]),
        )
    )
    return related[: max(0, int(top))]


def query_material(
    snapshot: Mapping[str, Any],
    a: str,
    b: str | None = None,
    top: int = 20,
) -> Any:
    entities = snapshot.get("materials", [])
    entity_a = _resolve_one(entities, a)
    a_id = str(entity_a["id"])
    interfaces = snapshot.get("material_interfaces", [])
    if b is not None:
        entity_b = _resolve_one(entities, b)
        b_id = str(entity_b["id"])
        for edge in interfaces:
            if edge["a"]["id"] == a_id and edge["b"]["id"] == b_id:
                return edge
        raise ValueError(f"material interface not found: {a} -> {b}")
    related = [
        edge for edge in interfaces if edge["a"]["id"] == a_id
    ]
    related.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item["coverage"]),
            str(item["id"]),
        )
    )
    return related[: max(0, int(top))]
