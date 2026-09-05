"""Deterministic evidence primitives for Substitute compatibility research.

This module evaluates evidence for offline sequential simulation research only.
It does not determine chemical mixing safety, reactor compatibility, physical
fabrication readiness, or equipment operating conditions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any


MODEL_SCHEMA = "ald-compatibility-model/1"
EVIDENCE_SCHEMA = "ald-compatibility-evidence/1"
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


def normalize_formula(value: str) -> str:
    """Remove presentation whitespace without guessing chemical identity."""
    if not isinstance(value, str):
        raise ValueError("formula must be a string")
    return "".join(character for character in unicodedata.normalize("NFKC", value) if not character.isspace())


def normalize_name(value: str) -> str:
    """Normalize a human chemical/material name for conservative alias lookup."""
    if not isinstance(value, str):
        raise ValueError("name must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


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
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or float(weight) <= 0.0:
            raise ValueError(f"model {label}.{family} must be positive")
        total += float(weight)
    if total <= 0.0:
        raise ValueError(f"model {label} must have positive total weight")


def validate_model(value: Mapping[str, Any]) -> dict[str, Any]:
    model = dict(value)
    if model.get("schema") != MODEL_SCHEMA:
        raise ValueError(f"unsupported compatibility model schema: {model.get('schema')!r}")
    _validate_weight_map(model.get("precursor_weights"), "precursor_weights")
    _validate_weight_map(model.get("material_weights"), "material_weights")
    _validate_weight_map(model.get("candidate_weights"), "candidate_weights")

    coverage = model.get("coverage_unknown_below")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not 0.0 <= float(coverage) <= 1.0:
        raise ValueError("model coverage_unknown_below must be between 0 and 1")

    if not isinstance(model.get("status_reliability"), dict):
        raise ValueError("model status_reliability must be an object")
    for status, reliability in model["status_reliability"].items():
        if not isinstance(status, str) or isinstance(reliability, bool) or not isinstance(reliability, (int, float)):
            raise ValueError("model status_reliability values must be numeric")
        if not 0.0 <= float(reliability) <= 1.0:
            raise ValueError("model status_reliability values must be between 0 and 1")

    role_keywords = model.get("role_keywords")
    if not isinstance(role_keywords, dict):
        raise ValueError("model role_keywords must be an object")
    for role_class, keywords in role_keywords.items():
        if not isinstance(role_class, str) or not isinstance(keywords, list) or not all(isinstance(item, str) and item for item in keywords):
            raise ValueError("model role_keywords values must be arrays of non-empty strings")

    return model


def load_model(path: Path | str) -> dict[str, Any]:
    return validate_model(_read_json_object(path, "compatibility model"))


def load_evidence_overrides(path: Path | str) -> list[dict[str, Any]]:
    payload = _read_json_object(path, "compatibility evidence")
    if payload.get("schema") != EVIDENCE_SCHEMA:
        raise ValueError(f"unsupported compatibility evidence schema: {payload.get('schema')!r}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("compatibility evidence records must be an array")

    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ValueError(f"evidence record {index} must be an object")
        graph = raw.get("graph")
        if graph not in {"precursor", "material"}:
            raise ValueError(f"evidence record {index} graph must be precursor or material")
        for field in ("a", "b", "family"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ValueError(f"evidence record {index} {field} must be a non-empty string")
        value = raw.get("value")
        reliability = raw.get("reliability")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1.0 <= float(value) <= 1.0:
            raise ValueError(f"evidence record {index} value must be between -1 and 1")
        if isinstance(reliability, bool) or not isinstance(reliability, (int, float)) or not 0.0 <= float(reliability) <= 1.0:
            raise ValueError(f"evidence record {index} reliability must be between 0 and 1")
        source = raw.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("type"), str) or not isinstance(source.get("identifier"), str):
            raise ValueError(f"evidence record {index} source must contain type and identifier")
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
                if isinstance(keyword, str) and normalize_name(keyword) in text:
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
            entity_key = f"formula:{formula}" if formula else f"name:{name_key}"
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
                "formula": sorted(bucket["formulas"])[0] if bucket["formulas"] else "",
                "aliases": sorted(bucket["names"], key=lambda item: (normalize_name(item), item)),
                "roles": sorted(bucket["roles"]),
                "recipe_ids": sorted(bucket["recipe_ids"]),
                "chemistry_statuses": sorted(bucket["chemistry_statuses"]),
                "categories": sorted(bucket["categories"]),
                "chemistry_families": sorted(bucket["chemistry_families"]),
                "source_references": references,
            }
        )
    return sorted(entities, key=lambda item: item["id"])


def build_material_entities(entries: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base_buckets: dict[str, dict[str, Any]] = {}
    composites: list[dict[str, Any]] = []
    for entry in entries:
        raw_formula = str(entry.get("target_formula", "")).strip()
        raw_name = str(entry.get("target_material", "")).strip()
        if not raw_formula and not raw_name:
            continue
        if "/" in raw_formula:
            components = [normalize_formula(part) for part in raw_formula.split("/") if normalize_formula(part)]
            composites.append(
                {
                    "recipe_id": str(entry.get("recipe_id", "")),
                    "formula": normalize_formula(raw_formula),
                    "name": raw_name,
                    "components": components,
                    "chemistry_status": str(entry.get("chemistry_status", "")),
                    "chemistry_family": str(entry.get("chemistry_family", "")),
                    "source_references": [dict(item) for item in entry.get("source_references", []) if isinstance(item, Mapping)],
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
                "formula": sorted(bucket["formulas"])[0] if bucket["formulas"] else "",
                "aliases": sorted(bucket["names"], key=lambda item: (normalize_name(item), item)),
                "recipe_ids": sorted(bucket["recipe_ids"]),
                "categories": sorted(bucket["categories"]),
                "chemistry_families": sorted(bucket["chemistry_families"]),
                "product_families": sorted(bucket["product_families"]),
            }
        )

    return {
        "base": sorted(base, key=lambda item: item["formula"] or item["name"]),
        "composites": sorted(composites, key=lambda item: (item["formula"], item["recipe_id"])),
    }
