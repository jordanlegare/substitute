"""Read-only chemistry exploration over recipes, evidence, and material identity.

This module exposes non-operational process identity and provenance only. It
never reads recipe instruction payloads and deliberately excludes simulator
conditions such as temperature, pressure, timing, dose, purge, flow, and
hardware settings.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any

import ald_materials as materials
import ald_recipe_evidence as evidence_core


DEFAULT_RECIPE_CATALOG = Path("recipes/compounds/catalog.json")
DEFAULT_RECIPE_EVIDENCE = Path("recipes/evidence/process-evidence.json")
DEFAULT_MATERIAL_CATALOG = Path("materials/catalog.json")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be an array")
    return value


def _required_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if type(value) is str and value.strip():
        return value.strip()
    return None


def _safe_reduce(formula: object) -> tuple[str, tuple[str, ...]]:
    """Reduce a fixed formula while preserving historical symbolic labels."""
    text = _required_text(formula, "target formula")
    try:
        reduced, elements = materials.reduce_formula(text)
    except ValueError:
        return text, ()
    return reduced, tuple(elements)


def _chemistry_id(recipe_id: str) -> str:
    digest = hashlib.sha256(recipe_id.encode("utf-8")).hexdigest()[:16]
    return f"chem-{digest}"


def _material_indexes(
    material_entries: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    by_formula: dict[str, Mapping[str, object]] = {}
    by_id: dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(material_entries):
        material_id = _optional_text(entry.get("material_id"))
        reduced_value = entry.get("reduced_formula", entry.get("formula"))
        if reduced_value is not None:
            try:
                reduced, _elements = materials.reduce_formula(str(reduced_value))
            except ValueError:
                reduced = str(reduced_value).strip()
            if reduced:
                by_formula[reduced.casefold()] = entry
        if material_id:
            by_id[material_id.casefold()] = entry
    return by_formula, by_id


def _evidence_index(evidence_document: Mapping[str, object]) -> dict[str, dict[str, object]]:
    schema = evidence_document.get("schema")
    if schema != evidence_core.EVIDENCE_SCHEMA:
        raise ValueError(f"unsupported recipe evidence schema: {schema!r}")
    raw_records = _sequence(evidence_document.get("records"), "evidence.records")
    result: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(raw_records):
        record = evidence_core.validate_evidence_record(
            _mapping(raw, f"evidence.records[{index}]")
        )
        record_id = str(record["evidence_id"])
        if record_id in result:
            raise ValueError(f"duplicate evidence_id: {record_id}")
        result[record_id] = record
    return result


def _historical_reactants(entry: Mapping[str, object]) -> list[dict[str, str]]:
    raw = _sequence(entry.get("precursors", []), "recipe precursors")
    result: list[dict[str, str]] = []
    for index, item_raw in enumerate(raw):
        item = _mapping(item_raw, f"recipe precursors[{index}]")
        name = _optional_text(item.get("name"))
        formula = _optional_text(item.get("formula"))
        label = formula or name
        if not label:
            raise ValueError(f"recipe precursors[{index}] has no display identity")
        role = _required_text(item.get("role"), f"recipe precursors[{index}].role")
        record: dict[str, str] = {"label": label, "role": role}
        precursor_id = _optional_text(item.get("id"))
        if precursor_id:
            record["id"] = precursor_id
        if name:
            record["name"] = name
        if formula:
            record["formula"] = formula
        result.append(record)
    result.sort(
        key=lambda item: (
            item.get("id", "").casefold(),
            item["role"].casefold(),
            item["label"].casefold(),
        )
    )
    return result


def _historical_sources(entry: Mapping[str, object]) -> list[dict[str, object]]:
    raw = _sequence(entry.get("source_references", []), "recipe source_references")
    result: list[dict[str, object]] = []
    for index, source_raw in enumerate(raw):
        source = _mapping(source_raw, f"recipe source_references[{index}]")
        source_type = _required_text(source.get("type"), "source type").casefold()
        identifier = _required_text(source.get("identifier"), "source identifier")
        if source_type == "doi":
            try:
                identifier = evidence_core.normalize_doi(identifier)
            except ValueError:
                pass
        result.append({"type": source_type, "identifier": identifier})
    result.sort(key=lambda item: (str(item["type"]), str(item["identifier"])))
    return result


def _publication_sources(record: Mapping[str, object]) -> list[dict[str, object]]:
    raw = _sequence(record.get("publications", []), "evidence publications")
    result: list[dict[str, object]] = []
    for index, publication_raw in enumerate(raw):
        publication = _mapping(publication_raw, f"evidence publications[{index}]")
        item: dict[str, object] = {
            "type": _required_text(publication.get("type"), "publication type").casefold(),
            "identifier": _required_text(publication.get("identifier"), "publication identifier"),
            "direct": bool(publication.get("direct", False)),
        }
        for key in ("title", "journal"):
            value = _optional_text(publication.get(key))
            if value:
                item[key] = value
        year = publication.get("year")
        if type(year) is int:
            item["year"] = year
        result.append(item)
    result.sort(
        key=lambda item: (
            str(item["type"]),
            str(item["identifier"]),
            0 if item.get("direct") is True else 1,
        )
    )
    return result


def _material_for_target(
    reduced_formula: str,
    explicit_material_id: str | None,
    by_formula: Mapping[str, Mapping[str, object]],
    by_id: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object] | None:
    if explicit_material_id:
        match = by_id.get(explicit_material_id.casefold())
        if match is not None:
            return match
    return by_formula.get(reduced_formula.casefold())


def build_chemistry_index(
    recipe_entries: Sequence[Mapping[str, object]],
    evidence_document: Mapping[str, object],
    material_entries: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project executable recipes into safe chemistry/provenance records."""
    evidence_by_id = _evidence_index(evidence_document)
    material_by_formula, material_by_id = _material_indexes(material_entries)
    result: list[dict[str, object]] = []
    seen_recipe_ids: set[str] = set()

    for index, raw_entry in enumerate(recipe_entries):
        entry = _mapping(raw_entry, f"recipe_entries[{index}]")
        recipe_id = _required_text(entry.get("recipe_id"), f"recipe_entries[{index}].recipe_id")
        if recipe_id in seen_recipe_ids:
            raise ValueError(f"duplicate recipe_id: {recipe_id}")
        seen_recipe_ids.add(recipe_id)

        target_material = _required_text(
            entry.get("target_material"), f"recipe_entries[{index}].target_material"
        )
        target_formula = _required_text(
            entry.get("target_formula"), f"recipe_entries[{index}].target_formula"
        )
        reduced_formula, parsed_elements = _safe_reduce(target_formula)
        origin = "expansion" if entry.get("recipe_origin") == "evidence-expansion" else "historical"
        evidence_record_id: str | None = None
        evidence_grade = "historical"
        process_family: str | None = None
        reactants: list[dict[str, str]]
        sources: list[dict[str, object]]
        explicit_material_id: str | None = None

        if origin == "expansion":
            evidence_record_id = _required_text(
                entry.get("evidence_record_id"),
                f"recipe_entries[{index}].evidence_record_id",
            )
            record = evidence_by_id.get(evidence_record_id)
            if record is None:
                raise ValueError(
                    f"expansion recipe {recipe_id} references missing selected evidence: {evidence_record_id}"
                )
            if record.get("selection_status") != "selected" or record.get("evidence_grade") not in {"R2", "R3"}:
                raise ValueError(
                    f"expansion recipe {recipe_id} requires selected R2/R3 evidence"
                )
            evidence_target = str(record["target_reduced_formula"])
            if evidence_target != reduced_formula:
                raise ValueError(
                    f"expansion recipe {recipe_id} target does not match evidence: "
                    f"{reduced_formula} != {evidence_target}"
                )
            process_family = str(record["process_family"])
            entry_family = _optional_text(entry.get("process_family"))
            if entry_family is not None and entry_family != process_family:
                raise ValueError(
                    f"expansion recipe {recipe_id} process family does not match evidence"
                )
            evidence_grade = str(record["evidence_grade"])
            reactants = [dict(item) for item in record["reactants"]]  # type: ignore[index]
            sources = _publication_sources(record)
            explicit_material_id = _optional_text(record.get("material_id"))
        else:
            reactants = _historical_reactants(entry)
            sources = _historical_sources(entry)
            # Historical recipes are not retroactively classified. Preserve a family
            # only if it is already explicit in the catalog entry.
            process_family = _optional_text(entry.get("process_family"))

        material = _material_for_target(
            reduced_formula,
            explicit_material_id,
            material_by_formula,
            material_by_id,
        )
        material_id = explicit_material_id
        target_elements = list(parsed_elements)
        if material is not None:
            material_id = _optional_text(material.get("material_id")) or material_id
            raw_elements = material.get("elements")
            if isinstance(raw_elements, Sequence) and not isinstance(
                raw_elements, (str, bytes, bytearray)
            ):
                target_elements = [str(value) for value in raw_elements]

        result.append(
            {
                "chemistry_id": _chemistry_id(recipe_id),
                "target_material": target_material,
                "target_formula": target_formula,
                "target_reduced_formula": reduced_formula,
                "target_elements": target_elements,
                "chemistry_family": _required_text(
                    entry.get("chemistry_family"),
                    f"recipe_entries[{index}].chemistry_family",
                ),
                "process_family": process_family,
                "origin": origin,
                "evidence_grade": evidence_grade,
                "evidence_record_id": evidence_record_id,
                "recipe_id": recipe_id,
                "recipe_path": _required_text(
                    entry.get("path"), f"recipe_entries[{index}].path"
                ),
                "reactants": reactants,
                "sources": sources,
                "material_id": material_id,
                "simulation_only": True,
            }
        )

    result.sort(
        key=lambda item: (
            str(item["target_reduced_formula"]).casefold(),
            str(item["recipe_id"]).casefold(),
        )
    )
    return result


def _casefold(value: object) -> str:
    return str(value or "").strip().casefold()


def _reactant_strings(entry: Mapping[str, object]) -> list[str]:
    raw = entry.get("reactants", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        for key in ("label", "name", "formula", "role"):
            value = _optional_text(item.get(key))
            if value:
                result.append(value)
    return result


def _source_strings(entry: Mapping[str, object]) -> list[str]:
    raw = entry.get("sources", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        for key in ("type", "identifier", "title", "journal"):
            value = _optional_text(item.get(key))
            if value:
                result.append(value)
    return result


def _search_rank(entry: Mapping[str, object], query: str) -> tuple[object, ...]:
    q = query.casefold()
    target_formula = _casefold(entry.get("target_formula"))
    reduced_formula = _casefold(entry.get("target_reduced_formula"))
    target_name = _casefold(entry.get("target_material"))
    recipe_id = _casefold(entry.get("recipe_id"))
    chemistry_id = _casefold(entry.get("chemistry_id"))
    reactants = [_casefold(value) for value in _reactant_strings(entry)]
    grade_rank = {"R3": 0, "R2": 1, "historical": 2}.get(
        str(entry.get("evidence_grade")), 3
    )
    return (
        0 if recipe_id == q else 1,
        0 if chemistry_id == q else 1,
        0 if target_formula == q or reduced_formula == q else 1,
        0 if target_name == q else 1,
        0 if q in reactants else 1,
        grade_rank,
        reduced_formula,
        recipe_id,
    )


def _searchable_strings(entry: Mapping[str, object]) -> list[str]:
    values = [
        entry.get("target_material"),
        entry.get("target_formula"),
        entry.get("target_reduced_formula"),
        entry.get("recipe_id"),
        entry.get("chemistry_id"),
        entry.get("chemistry_family"),
        entry.get("process_family"),
        entry.get("evidence_grade"),
        entry.get("material_id"),
        *_reactant_strings(entry),
        *_source_strings(entry),
    ]
    return [str(value) for value in values if value not in (None, "")]


def search_chemistries(
    entries: Sequence[Mapping[str, object]],
    text: str,
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    query = _required_text(text, "chemistry search text").casefold()
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    matches = [
        dict(entry)
        for entry in entries
        if any(query in value.casefold() for value in _searchable_strings(entry))
    ]
    matches.sort(key=lambda entry: _search_rank(entry, query))
    return matches[:limit]


def resolve_chemistries(
    entries: Sequence[Mapping[str, object]], query: str
) -> list[dict[str, object]]:
    needle = _required_text(query, "chemistry query").casefold()

    exact_identifier = [
        dict(entry)
        for entry in entries
        if _casefold(entry.get("recipe_id")) == needle
        or _casefold(entry.get("chemistry_id")) == needle
    ]
    if exact_identifier:
        exact_identifier.sort(key=lambda item: _casefold(item.get("recipe_id")))
        return exact_identifier

    matches = [
        dict(entry)
        for entry in entries
        if needle
        in {
            _casefold(entry.get("target_formula")),
            _casefold(entry.get("target_reduced_formula")),
            _casefold(entry.get("target_material")),
            _casefold(entry.get("material_id")),
        }
    ]
    if not matches:
        raise ValueError(f"unknown chemistry: {query}")
    matches.sort(
        key=lambda item: (
            _casefold(item.get("target_reduced_formula")),
            _casefold(item.get("recipe_id")),
        )
    )
    return matches


def _precursor_matches(entry: Mapping[str, object], query: str) -> bool:
    q = query.casefold()
    return any(q in value.casefold() for value in _reactant_strings(entry))


def filter_chemistries(
    entries: Sequence[Mapping[str, object]],
    *,
    process_family: str | None = None,
    chemistry_family: str | None = None,
    element: str | None = None,
    precursor: str | None = None,
    evidence: str | None = None,
    origin: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    process_q = _casefold(process_family) if process_family else None
    chemistry_q = _casefold(chemistry_family) if chemistry_family else None
    element_q = _casefold(element) if element else None
    evidence_q = _casefold(evidence) if evidence else None
    origin_q = _casefold(origin) if origin else None

    result: list[dict[str, object]] = []
    for entry in entries:
        if process_q is not None and _casefold(entry.get("process_family")) != process_q:
            continue
        if chemistry_q is not None and chemistry_q not in _casefold(entry.get("chemistry_family")):
            continue
        if element_q is not None:
            raw_elements = entry.get("target_elements", [])
            if not isinstance(raw_elements, Sequence) or isinstance(
                raw_elements, (str, bytes, bytearray)
            ):
                continue
            if element_q not in {_casefold(value) for value in raw_elements}:
                continue
        if precursor is not None and not _precursor_matches(entry, precursor):
            continue
        if evidence_q is not None and _casefold(entry.get("evidence_grade")) != evidence_q:
            continue
        if origin_q is not None and _casefold(entry.get("origin")) != origin_q:
            continue
        result.append(dict(entry))

    result.sort(
        key=lambda item: (
            _casefold(item.get("target_reduced_formula")),
            _casefold(item.get("recipe_id")),
        )
    )
    return result[:limit]


def chemistry_sources(
    entries: Sequence[Mapping[str, object]], query: str
) -> list[dict[str, object]]:
    resolved = resolve_chemistries(entries, query)
    unique: dict[str, dict[str, object]] = {}
    for entry in resolved:
        sources = entry.get("sources", [])
        if not isinstance(sources, Sequence) or isinstance(
            sources, (str, bytes, bytearray)
        ):
            continue
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            item = dict(source)
            key = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            unique[key] = item
    return [unique[key] for key in sorted(unique)]


def chemistry_report(
    entries: Sequence[Mapping[str, object]], *, material_count: int = 8000
) -> dict[str, object]:
    if type(material_count) is not int or material_count < 0:
        raise ValueError("material_count must be a non-negative integer")
    origins = Counter(str(entry.get("origin", "historical")) for entry in entries)
    evidence_grades = Counter(str(entry.get("evidence_grade", "historical")) for entry in entries)
    process_families = Counter(
        str(entry.get("process_family") or "unspecified") for entry in entries
    )
    target_keys = {
        str(entry.get("target_reduced_formula") or entry.get("target_formula"))
        for entry in entries
    }
    material_ids = {
        str(entry["material_id"])
        for entry in entries
        if _optional_text(entry.get("material_id")) is not None
    }
    reactant_identities = {
        value.casefold()
        for entry in entries
        for value in _reactant_strings(entry)
        if value.strip()
    }
    publication_identifiers = {
        (str(source.get("type", "")), str(source.get("identifier", "")))
        for entry in entries
        for source in (
            entry.get("sources", [])
            if isinstance(entry.get("sources", []), Sequence)
            and not isinstance(entry.get("sources", []), (str, bytes, bytearray))
            else []
        )
        if isinstance(source, Mapping) and source.get("identifier")
    }
    recipe_backed_materials_in_identity_catalog = len(material_ids)
    return {
        "total_executable_recipes": len(entries),
        "unique_recipe_backed_materials": len(target_keys),
        "historical_recipe_count": origins.get("historical", 0),
        "expansion_recipe_count": origins.get("expansion", 0),
        "process_families": dict(sorted(process_families.items())),
        "evidence_grades": dict(sorted(evidence_grades.items())),
        "unique_reactant_identities": len(reactant_identities),
        "unique_publication_identifiers": len(publication_identifiers),
        "recipe_backed_materials_in_identity_catalog": recipe_backed_materials_in_identity_catalog,
        "recipe_backed_share": (
            recipe_backed_materials_in_identity_catalog / material_count
            if material_count
            else 0.0
        ),
        "remaining_identity_only_materials": max(
            0, material_count - recipe_backed_materials_in_identity_catalog
        ),
    }


def _load_json(path: Path, *, optional: bool = False) -> Mapping[str, object]:
    if optional and not path.exists():
        return {"schema": evidence_core.EVIDENCE_SCHEMA, "records": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read JSON from {path}: {error}") from error
    return _mapping(value, str(path))


def load_chemistry_catalog(
    recipe_catalog_path: Path = DEFAULT_RECIPE_CATALOG,
    evidence_path: Path | None = DEFAULT_RECIPE_EVIDENCE,
    material_catalog_path: Path | None = DEFAULT_MATERIAL_CATALOG,
) -> list[dict[str, object]]:
    recipe_catalog = _load_json(recipe_catalog_path)
    raw_recipes = _sequence(recipe_catalog.get("entries"), "recipe catalog entries")
    recipe_entries = [
        _mapping(value, f"recipe catalog entries[{index}]")
        for index, value in enumerate(raw_recipes)
    ]

    evidence_document: Mapping[str, object]
    if evidence_path is None:
        evidence_document = {"schema": evidence_core.EVIDENCE_SCHEMA, "records": []}
    else:
        evidence_document = _load_json(evidence_path, optional=True)

    material_entries: list[Mapping[str, object]] = []
    if material_catalog_path is not None and material_catalog_path.exists():
        material_catalog = _load_json(material_catalog_path)
        raw_materials = _sequence(material_catalog.get("entries"), "material catalog entries")
        material_entries = [
            _mapping(value, f"material catalog entries[{index}]")
            for index, value in enumerate(raw_materials)
        ]

    return build_chemistry_index(recipe_entries, evidence_document, material_entries)
