"""Deterministic, non-operational chemistry-evidence helpers for Substitute."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

import ald_materials as materials


EVIDENCE_SCHEMA = "ald-recipe-evidence/1"
ALLOWED_PROCESS_FAMILIES = frozenset({"thermal-ald", "plasma-ald", "mld", "hybrid"})
ALLOWED_GRADES = frozenset({"R1", "R2", "R3"})
ALLOWED_STATUSES = frozenset({"candidate", "selected", "rejected", "covered-existing"})

FORBIDDEN_OPERATIONAL_KEYS = frozenset(
    {
        "process_temperature",
        "temperature",
        "temperature_c",
        "pressure",
        "pressure_pa",
        "pulse",
        "pulse_time",
        "dose",
        "dose_time",
        "purge",
        "purge_time",
        "growth_rate",
        "growth_per_cycle",
        "plasma_power",
        "plasma_bias",
        "flow",
        "flow_sccm",
        "hardware",
        "reactor",
        "reactor_geometry",
        "handling_notes",
    }
)

_PROCESS_FAMILY_ALIASES = {
    "thermal ald": "thermal-ald",
    "thermal-ald": "thermal-ald",
    "ald": "thermal-ald",
    "peald": "plasma-ald",
    "plasma ald": "plasma-ald",
    "plasma-ald": "plasma-ald",
    "plasma enhanced atomic layer deposition": "plasma-ald",
    "plasma-enhanced atomic layer deposition": "plasma-ald",
    "mld": "mld",
    "molecular layer deposition": "mld",
    "hybrid": "hybrid",
    "hybrid ald": "hybrid",
    "hybrid mld": "hybrid",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def canonical_json_bytes(value: object) -> bytes:
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


def normalize_doi(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("DOI must be a non-empty string")
    normalized = value.strip().casefold()
    prefixes = (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    if not normalized or "/" not in normalized:
        raise ValueError(f"invalid DOI: {value}")
    return normalized


def normalize_process_family(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("process family must be a non-empty string")
    folded = " ".join(value.strip().casefold().replace("_", " ").split())
    normalized = _PROCESS_FAMILY_ALIASES.get(folded)
    if normalized is None and folded in ALLOWED_PROCESS_FAMILIES:
        normalized = folded
    if normalized is None:
        raise ValueError(f"unsupported process family: {value}")
    return normalized


def _reject_operational_keys(value: object, path: str = "record") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            folded = str(key).strip().casefold().replace("-", "_")
            if folded in FORBIDDEN_OPERATIONAL_KEYS:
                raise ValueError(f"operational field is forbidden at {path}.{key}")
            _reject_operational_keys(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_operational_keys(item, f"{path}[{index}]")


def _required_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def normalize_reactants(raw: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        raise ValueError("reactants must be a non-empty array")
    reactants: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"reactants[{index}] must be an object")
        name = _required_text(item.get("name"), f"reactants[{index}].name")
        formula = _required_text(item.get("formula"), f"reactants[{index}].formula")
        role = _required_text(item.get("role"), f"reactants[{index}].role")
        reactants.append({"name": name, "formula": formula, "role": role})
    reactants.sort(
        key=lambda item: (
            item["role"].casefold(),
            item["formula"].casefold(),
            item["name"].casefold(),
        )
    )
    return reactants


def chemistry_key(
    target_reduced_formula: str,
    process_family: str,
    reactants: Sequence[Mapping[str, str]],
) -> str:
    target, _ = materials.reduce_formula(target_reduced_formula)
    family = normalize_process_family(process_family)
    normalized = normalize_reactants(reactants)
    parts = [
        f"{item['role'].casefold()}:{item['formula'].casefold()}:{item['name'].casefold()}"
        for item in normalized
    ]
    return "|".join([target, family, *parts])


def _normalize_publications(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        raise ValueError("publications must be a non-empty array")
    publications: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"publications[{index}] must be an object")
        source_type = _required_text(item.get("type"), f"publications[{index}].type").casefold()
        identifier = _required_text(item.get("identifier"), f"publications[{index}].identifier")
        if source_type == "doi":
            identifier = normalize_doi(identifier)
        direct = item.get("direct", False)
        if type(direct) is not bool:
            raise ValueError(f"publications[{index}].direct must be a boolean")
        publication: dict[str, object] = {
            "type": source_type,
            "identifier": identifier,
            "direct": direct,
        }
        for key in ("title", "journal"):
            value = item.get(key)
            if type(value) is str and value.strip():
                publication[key] = value.strip()
        year = item.get("year")
        if type(year) is int:
            publication["year"] = year
        publications.append(publication)
    publications.sort(
        key=lambda item: (
            str(item["type"]),
            str(item["identifier"]),
            0 if item["direct"] else 1,
        )
    )
    return publications


def _normalize_sources(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("discovery_sources must be an array")
    values = {
        _required_text(value, "discovery_sources[]").casefold()
        for value in raw
    }
    return sorted(values)


def _evidence_id_payload(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "target_reduced_formula": record["target_reduced_formula"],
        "process_family": record["process_family"],
        "reactants": record["reactants"],
        "publications": [
            {"type": item["type"], "identifier": item["identifier"]}
            for item in record["publications"]
            if isinstance(item, Mapping)
        ],
    }


def evidence_id(record: Mapping[str, object]) -> str:
    target = _required_text(record.get("target_reduced_formula"), "target_reduced_formula")
    slug = _SLUG_RE.sub("-", target.casefold()).strip("-") or "material"
    digest = hashlib.sha256(canonical_json_bytes(_evidence_id_payload(record))).hexdigest()[:12]
    return f"ev-{slug}-{digest}"


def validate_evidence_record(record: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(record, Mapping):
        raise ValueError("evidence record must be an object")
    _reject_operational_keys(record)

    target_material = _required_text(record.get("target_material"), "target_material")
    target_formula = _required_text(record.get("target_formula"), "target_formula")
    target_reduced_formula, target_elements = materials.reduce_formula(target_formula)
    if len(target_elements) < 2:
        raise ValueError("target material must contain at least two elements")

    process_family = normalize_process_family(_required_text(record.get("process_family"), "process_family"))
    reactants = normalize_reactants(record.get("reactants", []))  # type: ignore[arg-type]
    publications = _normalize_publications(record.get("publications"))
    discovery_sources = _normalize_sources(record.get("discovery_sources"))

    grade = _required_text(record.get("evidence_grade"), "evidence_grade").upper()
    if grade not in ALLOWED_GRADES:
        raise ValueError(f"unsupported evidence grade: {grade}")
    status = _required_text(record.get("selection_status"), "selection_status").casefold()
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"unsupported selection status: {status}")

    direct_identifiers = {
        (str(item["type"]), str(item["identifier"]))
        for item in publications
        if item["direct"] is True
    }
    if grade in {"R2", "R3"} and not direct_identifiers:
        raise ValueError(f"{grade} evidence requires at least one direct publication")

    normalized: dict[str, object] = {
        "target_material": target_material,
        "target_formula": target_formula,
        "target_reduced_formula": target_reduced_formula,
        "target_elements": list(target_elements),
        "process_family": process_family,
        "reactants": reactants,
        "publications": publications,
        "discovery_sources": discovery_sources,
        "evidence_grade": grade,
        "selection_status": status,
        "reactant_identities_complete": True,
        "independent_direct_publication_count": len(direct_identifiers),
        "stable_publication_identifier_count": len(
            {(str(item["type"]), str(item["identifier"])) for item in publications}
        ),
    }
    normalized["chemistry_key"] = chemistry_key(
        target_reduced_formula,
        process_family,
        reactants,
    )

    for key in ("material_id", "rejection_reason"):
        value = record.get(key)
        if type(value) is str and value.strip():
            normalized[key] = value.strip()

    # Preserve safe provenance-only extensions without letting them affect identity.
    for key in ("provenance", "discovery_metadata"):
        value = record.get(key)
        if value is not None:
            normalized[key] = deepcopy(value)

    normalized["evidence_id"] = evidence_id(normalized)
    return normalized
