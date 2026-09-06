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

_METALLIC_ELEMENTS = {
    "Ac", "Ag", "Al", "Am", "Au", "Ba", "Be", "Bi", "Bk", "Ca", "Cd",
    "Ce", "Cf", "Cm", "Co", "Cr", "Cs", "Cu", "Dy", "Er", "Es", "Eu",
    "Fe", "Fm", "Fr", "Ga", "Gd", "Hf", "Hg", "Ho", "In", "Ir", "K",
    "La", "Li", "Lr", "Lu", "Md", "Mg", "Mn", "Mo", "Na", "Nb", "Nd",
    "Ni", "No", "Np", "Os", "Pa", "Pb", "Pd", "Pm", "Pr", "Pt", "Pu",
    "Ra", "Rb", "Re", "Rh", "Ru", "Sc", "Sm", "Sn", "Sr", "Ta", "Tb",
    "Tc", "Th", "Ti", "Tl", "Tm", "U", "V", "W", "Y", "Yb", "Zn", "Zr",
}
_CORE_THIN_FILM_CLASSES = {
    "oxide",
    "nitride",
    "sulfide",
    "selenide",
    "telluride",
    "boride",
    "silicide",
    "phosphide",
    "arsenide",
}
_SECONDARY_MATERIAL_CLASSES = {"fluoride", "halide", "intermetallic"}


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
    has_oxygen = "O" in present

    if has_oxygen:
        classes.add("oxide")
    if "N" in present and not has_oxygen:
        classes.add("nitride")
    if "S" in present and not has_oxygen:
        classes.add("sulfide")
    if "Se" in present and not has_oxygen:
        classes.add("selenide")
    if "Te" in present and not has_oxygen:
        classes.add("telluride")
    if "F" in present:
        classes.add("fluoride")
    if present.intersection({"Cl", "Br", "I"}):
        classes.add("halide")
    if "C" in present and not bool(metadata.get("organic")):
        classes.add("carbide-or-inorganic-carbon")
    if "B" in present and not has_oxygen:
        classes.add("boride")
    if "Si" in present and len(present) >= 2:
        classes.add("silicate" if has_oxygen else "silicide")
    if "P" in present:
        classes.add("phosphate" if has_oxygen else "phosphide")
    if "As" in present and not has_oxygen:
        classes.add("arsenide")
    if "Sb" in present and not has_oxygen:
        classes.add("antimonide")
    if "Ge" in present and not has_oxygen:
        classes.add("germanide")
    if "H" in present and "C" not in present and not has_oxygen and present.intersection(_METALLIC_ELEMENTS):
        classes.add("hydride")
    if len(present) >= 2 and present.issubset(_METALLIC_ELEMENTS):
        classes.add("intermetallic")

    explicit = metadata.get("material_classes", [])
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        classes.update(str(value).strip() for value in explicit if str(value).strip())
    return sorted(classes)


def _formula_complexity(reduced_formula: str) -> tuple[int, int]:
    try:
        counts = materials.parse_formula(reduced_formula)
    except ValueError:
        return (10_000, 10_000)
    return (len(counts), sum(counts.values()))


def relevance_score(record: Mapping[str, Any]) -> tuple[Any, ...]:
    provenance = record.get("provenance", [])
    phases = record.get("phases", [])
    identifiers = record.get("identifiers", {})
    pubchem = int(
        isinstance(identifiers, Mapping) and bool(identifiers.get("pubchem_cid"))
    )
    process = record.get("process_evidence", {})
    recipe_backed = int(
        isinstance(process, Mapping) and process.get("status") == "executable-recipe"
    )
    classes = set(str(value) for value in record.get("material_classes", []))
    if classes.intersection(_CORE_THIN_FILM_CLASSES):
        class_priority = 0
    elif classes.intersection(_SECONDARY_MATERIAL_CLASSES):
        class_priority = 1
    else:
        class_priority = 2
    element_count, atom_count = _formula_complexity(
        str(record.get("reduced_formula", ""))
    )
    return (
        -recipe_backed,
        class_priority,
        element_count,
        atom_count,
        -pubchem,
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
        formula = record.get("reduced_formula") or record.get("molecular_formula") or record.get("formula")
        if not isinstance(formula, str) or not formula.strip():
            continue
        try:
            reduced, _ = materials.reduce_formula(formula.strip())
        except ValueError:
            continue
        if reduced not in result:
            result[reduced] = record
    return result


def _recipe_index(
    recipe_entries: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for entry in recipe_entries:
        formula = entry.get("target_formula")
        recipe_id = str(entry.get("recipe_id", "")).strip()
        path = str(entry.get("path", "")).strip()
        if not isinstance(formula, str) or not recipe_id or not path:
            continue
        try:
            reduced, _ = materials.reduce_formula(formula)
        except ValueError:
            continue
        index.setdefault(reduced, []).append({"recipe_id": recipe_id, "path": path})
    for reduced in index:
        index[reduced].sort(key=lambda item: (item["recipe_id"], item["path"]))
    return index


def _merged_record(
    reduced_formula: str,
    elements: tuple[str, ...],
    source_records: Sequence[Mapping[str, Any]],
    pubchem: Mapping[str, Any] | None,
    pubchem_audit_metadata: Mapping[str, Any] | None = None,
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
    pubchem_audit: dict[str, Any] | None = None
    if pubchem is not None:
        cids_raw = pubchem.get("cids", [])
        cids = {
            str(value).strip()
            for value in cids_raw
            if str(value).strip()
        } if isinstance(cids_raw, Sequence) and not isinstance(cids_raw, (str, bytes)) else set()
        cid = pubchem.get("cid")
        if cid not in (None, ""):
            cids.add(str(cid).strip())
        ordered_cids = sorted(cids, key=lambda value: (int(value) if value.isdigit() else 10**30, value))
        if ordered_cids:
            identifiers["pubchem_cid"] = ordered_cids[0]
        for source_key, output_key in (("inchi", "inchi"), ("inchikey", "inchikey")):
            value = pubchem.get(source_key)
            if value not in (None, ""):
                identifiers[output_key] = str(value)
        metadata = dict(pubchem_audit_metadata or {})
        if ordered_cids and metadata.get("mirror") and metadata.get("mirror_release_date"):
            pubchem_audit = {
                "status": "matched",
                "mirror": str(metadata["mirror"]),
                "release_date": str(metadata["mirror_release_date"]),
                "cids": ordered_cids,
            }
    explicit_classes = {
        str(value).strip()
        for source_record in source_records
        for value in source_record.get("material_classes", [])
        if isinstance(source_record.get("material_classes", []), Sequence)
        and not isinstance(source_record.get("material_classes", []), (str, bytes))
        and str(value).strip()
    }
    classes = set(classify_material(elements, reduced_formula, {}))
    classes.update(explicit_classes)
    if not classes:
        classes.add("other-inorganic")
    result = {
        "material_id": materials.material_id(reduced_formula),
        "name": name,
        "formula": reduced_formula,
        "reduced_formula": reduced_formula,
        "elements": list(elements),
        "counted": True,
        "material_classes": sorted(classes),
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
    if pubchem_audit is not None:
        result["pubchem_audit"] = pubchem_audit
    return result


def build_material_artifacts(
    source_records: Sequence[Mapping[str, Any]],
    pubchem_records: Sequence[Mapping[str, Any]],
    recipe_entries: Sequence[Mapping[str, Any]],
    *,
    target_count: int = 1000,
    manifest_template: Mapping[str, Any] | None = None,
    require_pubchem_match: bool = False,
    pubchem_audit_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    recipe_index = _recipe_index(recipe_entries)
    candidates: list[dict[str, Any]] = []
    relevance_exclusions = 0
    for reduced in sorted(groups):
        _, elements = materials.reduce_formula(reduced)
        pubchem_record = pubchem.get(reduced)
        if require_pubchem_match and pubchem_record is None:
            continue
        record = _merged_record(
            reduced,
            elements,
            groups[reduced],
            pubchem_record,
            pubchem_audit_metadata,
        )
        links = recipe_index.get(reduced, [])
        if links:
            record["process_evidence"] = {
                "status": "executable-recipe",
                "recipe_ids": sorted({link["recipe_id"] for link in links}),
                "recipe_paths": sorted({link["path"] for link in links}),
            }
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
    if pubchem_audit_metadata:
        source_metadata = dict(manifest.get("source_metadata", {}))
        source_metadata["pubchem"] = {
            key: value
            for key, value in dict(pubchem_audit_metadata).items()
            if key not in {"records"}
        }
        manifest["source_metadata"] = source_metadata
    classes = Counter(
        material_class
        for entry in selected
        for material_class in entry.get("material_classes", [])
    )
    elements = Counter(
        element for entry in selected for element in entry.get("elements", [])
    )
    catalog_digest = _digest(catalog)
    recipe_linked = sum(
        1
        for entry in selected
        if entry.get("process_evidence", {}).get("status") == "executable-recipe"
    )
    pubchem_candidate_match_count = sum(
        1 for entry in candidates if entry.get("pubchem_audit", {}).get("status") == "matched"
    )
    pubchem_matched_count = sum(
        1 for entry in selected if entry.get("pubchem_audit", {}).get("status") == "matched"
    )
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "target_count": target_count,
        "selected_count": len(selected),
        "pubchem_matched_count": pubchem_matched_count,
        "pubchem_candidate_match_count": pubchem_candidate_match_count,
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
        "recipe_linked_materials": recipe_linked,
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


def _read_pubchem_snapshot(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        return [], {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        if not all(isinstance(record, dict) for record in payload):
            raise ValueError(f"{path}: every PubChem record must be an object")
        return [dict(record) for record in payload], {}
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{path}: expected an array or records array")
    records = payload["records"]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path}: every PubChem record must be an object")
    metadata = {key: value for key, value in payload.items() if key != "records"}
    return [dict(record) for record in records], metadata


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
    pubchem_records, pubchem_metadata = _read_pubchem_snapshot(PUBCHEM_SOURCE_PATH)
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
        require_pubchem_match=pubchem_metadata.get("audit_mode") == "bulk-mirror",
        pubchem_audit_metadata=pubchem_metadata,
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
