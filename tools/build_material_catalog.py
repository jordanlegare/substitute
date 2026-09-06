"""Build Substitute's offline deterministic material identity catalog."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ald_materials as materials


MATERIALS_ROOT = _REPO_ROOT / "materials"
SOURCE_ROOT = MATERIALS_ROOT / "sources"
COD_SOURCE_PATH = SOURCE_ROOT / "cod-materials.json"
PUBCHEM_SOURCE_PATH = SOURCE_ROOT / "pubchem-identities.json"
RECIPE_CATALOG_PATH = _REPO_ROOT / "recipes" / "compounds" / "catalog.json"
CATALOG_PATH = MATERIALS_ROOT / "catalog.json"
MANIFEST_PATH = MATERIALS_ROOT / "source-manifest.json"
AUDIT_PATH = MATERIALS_ROOT / "build-audit.json"
BUILDER_SCHEMA = "ald-material-builder/1"
MANIFEST_SCHEMA = "ald-material-source-manifest/1"
AUDIT_SCHEMA = "ald-material-build-audit/1"


def _digest(value: object) -> str:
    return hashlib.sha256(materials.canonical_json_bytes(value)).hexdigest()


def _json_key(value: object) -> bytes:
    return materials.canonical_json_bytes(value)


def classify_material(
    elements: Sequence[str],
    reduced_formula: str,
    metadata: Mapping[str, Any],
) -> list[str]:
    del reduced_formula
    present = set(elements)
    classes: set[str] = set()
    if "O" in present:
        classes.add("oxide")
    if "N" in present and "O" not in present:
        classes.add("nitride")
    if "S" in present:
        classes.add("sulfide")
    if "Se" in present:
        classes.add("selenide")
    if "Te" in present:
        classes.add("telluride")
    if "F" in present:
        classes.add("fluoride")
    if present.intersection({"Cl", "Br", "I"}):
        classes.add("halide")
    if "C" in present and not bool(metadata.get("organic")):
        classes.add("carbide-or-inorganic-carbon")
    if "B" in present:
        classes.add("boride")
    if "Si" in present and len(present) >= 2:
        classes.add("silicide-or-silicate")
    if "P" in present:
        classes.add("phosphide-or-phosphate")
    if "As" in present:
        classes.add("arsenide")
    explicit = metadata.get("material_classes", [])
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        classes.update(str(value).strip() for value in explicit if str(value).strip())
    return sorted(classes)


def relevance_score(record: Mapping[str, Any]) -> tuple[int, int, int, str, str]:
    provenance = record.get("provenance", [])
    phases = record.get("phases", [])
    identifiers = record.get("identifiers", {})
    pubchem = int(isinstance(identifiers, Mapping) and bool(identifiers.get("pubchem_cid")))
    return (
        -len(record.get("material_classes", [])),
        -len(provenance) if isinstance(provenance, Sequence) else 0,
        -len(phases) if isinstance(phases, Sequence) else 0,
        str(record.get("reduced_formula", "")),
        str(record.get("material_id", "")),
    )


def _phase_from_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    source = str(record.get("source", "")).strip()
    source_id = str(record.get("source_id", "")).strip()
    phase: dict[str, Any] = {"source": source, "source_id": source_id}
    for key in ("space_group", "doi", "reference"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            phase[key] = value.strip()
    return phase if len(phase) > 2 else None


def _pubchem_index(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        reduced = str(record.get("reduced_formula", "")).strip()
        if not reduced:
            formula = record.get("molecular_formula") or record.get("formula")
            if isinstance(formula, str):
                try:
                    reduced, _ = materials.reduce_formula(formula)
                except ValueError:
                    continue
        if reduced and reduced not in result:
            result[reduced] = record
    return result


def _merged_record(
    reduced_formula: str,
    elements: tuple[str, ...],
    source_records: Sequence[Mapping[str, Any]],
    pubchem: Mapping[str, Any] | None,
) -> dict[str, Any]:
    names = sorted(
        {
            str(record.get("name", "")).strip()
            for record in source_records
            if str(record.get("name", "")).strip()
        },
        key=lambda value: (value.casefold(), value),
    )
    if pubchem is not None:
        normalized = pubchem.get("title") or pubchem.get("iupac_name")
        if isinstance(normalized, str) and normalized.strip():
            name = normalized.strip()
        else:
            name = names[0] if names else reduced_formula
    else:
        name = names[0] if names else reduced_formula
    aliases = [value for value in names if value.casefold() != name.casefold()]
    provenance = sorted(
        [
            {
                "source": str(record["source"]),
                "source_id": str(record["source_id"]),
                "evidence": (
                    "crystallographic_identity"
                    if str(record["source"]).casefold() == "cod"
                    else "materials_identity"
                ),
            }
            for record in source_records
        ],
        key=_json_key,
    )
    phases = sorted(
        {
            _json_key(phase): phase
            for record in source_records
            for phase in [_phase_from_record(record)]
            if phase is not None
        }.values(),
        key=_json_key,
    )
    identifiers: dict[str, Any] = {
        "cod_ids": sorted(
            {
                str(record["source_id"])
                for record in source_records
                if str(record["source"]).casefold() == "cod"
            }
        )
    }
    if not identifiers["cod_ids"]:
        identifiers.pop("cod_ids")
    if pubchem is not None:
        for source_key, output_key in (
            ("cid", "pubchem_cid"),
            ("inchi", "inchi"),
            ("inchikey", "inchikey"),
        ):
            value = pubchem.get(source_key)
            if value not in (None, ""):
                identifiers[output_key] = str(value)
    classes = classify_material(elements, reduced_formula, source_records[0])
    return {
        "material_id": materials.material_id(reduced_formula),
        "name": name,
        "formula": reduced_formula,
        "reduced_formula": reduced_formula,
        "elements": list(elements),
        "counted": True,
        "material_classes": classes,
        "aliases": aliases,
        "identifiers": identifiers,
        "phases": phases,
        "provenance": provenance,
        "process_evidence": {
            "status": "identity-only",
            "recipe_ids": [],
            "recipe_paths": [],
        },
    }


def build_material_artifacts(
    source_records: Sequence[Mapping[str, Any]],
    pubchem_records: Sequence[Mapping[str, Any]],
    recipe_entries: Sequence[Mapping[str, Any]],
    *,
    target_count: int = 1000,
    manifest_template: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    del recipe_entries
    if type(target_count) is not int or target_count <= 0:
        raise ValueError("target_count must be a positive integer")
    raw_candidate_count = len(source_records)
    provenance_failures = 0
    elemental_exclusions = 0
    ambiguous_exclusions = 0
    parseable_candidate_count = 0
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in source_records:
        source = str(record.get("source", "")).strip()
        source_id = str(record.get("source_id", "")).strip()
        if not source or not source_id:
            provenance_failures += 1
            continue
        formula = record.get("formula")
        if not isinstance(formula, str):
            ambiguous_exclusions += 1
            continue
        try:
            reduced, elements = materials.reduce_formula(formula)
        except ValueError:
            ambiguous_exclusions += 1
            continue
        parseable_candidate_count += 1
        if len(elements) < 2:
            elemental_exclusions += 1
            continue
        groups.setdefault(reduced, []).append(record)
    duplicate_collapses = sum(max(0, len(group) - 1) for group in groups.values())
    pubchem = _pubchem_index(pubchem_records)
    candidates: list[dict[str, Any]] = []
    relevance_exclusions = 0
    for reduced in sorted(groups):
        _, elements = materials.reduce_formula(reduced)
        record = _merged_record(reduced, elements, groups[reduced], pubchem.get(reduced))
        if not record["material_classes"]:
            relevance_exclusions += 1
            continue
        candidates.append(record)
    candidates.sort(key=relevance_score)
    if len(candidates) < target_count:
        raise ValueError(
            f"only {len(candidates)} eligible material identities are available; target is {target_count}"
        )
    selected = candidates[:target_count]
    selected.sort(key=lambda item: (item["reduced_formula"], item["material_id"]))
    catalog: dict[str, Any] = {
        "catalog_schema": materials.CATALOG_SCHEMA,
        "counted_non_elemental_reduced_formula_count": len(selected),
        "entries": selected,
    }
    source_digest = _digest([dict(record) for record in source_records])
    pubchem_digest = _digest([dict(record) for record in pubchem_records])
    template = dict(manifest_template or {})
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "builder_schema": BUILDER_SCHEMA,
        "target_count": target_count,
        "sources": {
            "cod": {"snapshot_sha256": source_digest},
            "pubchem": {"snapshot_sha256": pubchem_digest},
        },
    }
    manifest.update(template)
    classes = Counter(
        material_class
        for entry in selected
        for material_class in entry.get("material_classes", [])
    )
    elements = Counter(
        element for entry in selected for element in entry.get("elements", [])
    )
    catalog_digest = _digest(catalog)
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "raw_candidate_count": raw_candidate_count,
        "parseable_candidate_count": parseable_candidate_count,
        "elemental_exclusions": elemental_exclusions,
        "variable_or_ambiguous_formula_exclusions": ambiguous_exclusions,
        "materials_relevance_exclusions": relevance_exclusions,
        "duplicate_reduced_formula_collapses": duplicate_collapses,
        "provenance_failures": provenance_failures,
        "pubchem_enrichment_successes": sum(
            1 for entry in selected if entry.get("identifiers", {}).get("pubchem_cid")
        ),
        "pubchem_enrichment_unresolved": sum(
            1 for entry in selected if not entry.get("identifiers", {}).get("pubchem_cid")
        ),
        "accepted_candidate_count_before_selection": len(candidates),
        "counted_catalog_size": len(selected),
        "class_distribution": dict(sorted(classes.items())),
        "element_distribution": dict(sorted(elements.items())),
        "recipe_linked_materials": 0,
        "final_material_ids": [entry["material_id"] for entry in selected],
        "source_snapshot_sha256": source_digest,
        "pubchem_snapshot_sha256": pubchem_digest,
        "catalog_sha256": catalog_digest,
    }
    return catalog, manifest, audit


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        payload = payload["records"]
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected an array or records array")
    if not all(isinstance(record, dict) for record in payload):
        raise ValueError(f"{path}: every source record must be an object")
    return [dict(record) for record in payload]


def _read_recipe_entries(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected recipe catalog entries")
    return [dict(entry) for entry in entries if isinstance(entry, dict)]


def _artifact_bytes(value: object) -> bytes:
    return materials.canonical_json_bytes(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target-count", type=int, default=1000)
    args = parser.parse_args(argv)
    source_records = _read_json_array(COD_SOURCE_PATH)
    pubchem_records = _read_json_array(PUBCHEM_SOURCE_PATH) if PUBCHEM_SOURCE_PATH.exists() else []
    recipe_entries = _read_recipe_entries(RECIPE_CATALOG_PATH)
    existing_manifest = (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if MANIFEST_PATH.exists()
        else {}
    )
    template = {
        key: value
        for key, value in existing_manifest.items()
        if key not in {"schema", "builder_schema", "target_count", "sources"}
    }
    catalog, manifest, audit = build_material_artifacts(
        source_records,
        pubchem_records,
        recipe_entries,
        target_count=args.target_count,
        manifest_template=template,
    )
    artifacts = (
        (CATALOG_PATH, catalog),
        (MANIFEST_PATH, manifest),
        (AUDIT_PATH, audit),
    )
    if args.check:
        for path, value in artifacts:
            if not path.exists() or path.read_bytes() != _artifact_bytes(value):
                print(f"material catalog check failed: {path} is stale", file=sys.stderr)
                return 1
        return 0
    MATERIALS_ROOT.mkdir(parents=True, exist_ok=True)
    for path, value in artifacts:
        path.write_bytes(_artifact_bytes(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
