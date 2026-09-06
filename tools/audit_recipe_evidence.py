"""Audit frozen recipe chemistry evidence and generated-recipe linkage offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from collections.abc import Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ald_materials as materials
import ald_recipe_evidence as evidence_core


EVIDENCE_PATH = _REPO_ROOT / "recipes" / "evidence" / "process-evidence.json"
MANIFEST_PATH = _REPO_ROOT / "recipes" / "evidence" / "source-manifest.json"
ACQUISITION_AUDIT_PATH = _REPO_ROOT / "recipes" / "evidence" / "acquisition-audit.json"
RECIPE_CATALOG_PATH = _REPO_ROOT / "recipes" / "compounds" / "catalog.json"
MATERIAL_CATALOG_PATH = _REPO_ROOT / "materials" / "catalog.json"

MANIFEST_SCHEMA = "ald-recipe-evidence-manifest/1"
ACQUISITION_AUDIT_SCHEMA = "ald-recipe-evidence-audit/1"


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be an array")
    return value


def _sha256_canonical(value: object) -> str:
    return hashlib.sha256(evidence_core.canonical_json_bytes(value)).hexdigest()


def _reduced_formula(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty formula string")
    return materials.reduce_formula(value)[0]


def _material_formula_set(material_catalog: Mapping[str, object]) -> set[str]:
    entries = _sequence(material_catalog.get("entries"), "material catalog entries")
    formulas: set[str] = set()
    for index, raw in enumerate(entries):
        entry = _mapping(raw, f"material catalog entries[{index}]")
        value = entry.get("reduced_formula", entry.get("formula"))
        formulas.add(_reduced_formula(value, f"material catalog entries[{index}].reduced_formula"))
    return formulas


def _recipe_entries(recipe_catalog: Mapping[str, object]) -> list[Mapping[str, object]]:
    entries = _sequence(recipe_catalog.get("entries"), "recipe catalog entries")
    return [_mapping(raw, f"recipe catalog entries[{index}]") for index, raw in enumerate(entries)]


def audit_evidence(
    evidence: Mapping[str, object],
    manifest: Mapping[str, object],
    acquisition_audit: Mapping[str, object],
    recipe_catalog: Mapping[str, object],
    material_catalog: Mapping[str, object],
) -> dict[str, object]:
    """Validate canonical evidence invariants without network access.

    This function intentionally performs semantic checks in a stable order so
    the earliest error identifies the strongest violated invariant.
    """

    if evidence.get("schema") != evidence_core.EVIDENCE_SCHEMA:
        raise ValueError(f"unsupported evidence schema: {evidence.get('schema')!r}")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unsupported evidence manifest schema: {manifest.get('schema')!r}")
    if acquisition_audit.get("schema") != ACQUISITION_AUDIT_SCHEMA:
        raise ValueError(
            f"unsupported acquisition audit schema: {acquisition_audit.get('schema')!r}"
        )

    _mapping(manifest.get("sources"), "manifest.sources")
    digests = _mapping(manifest.get("digests"), "manifest.digests")
    expected_digest = digests.get("process_evidence_sha256")
    if type(expected_digest) is not str or len(expected_digest) != 64:
        raise ValueError("manifest process evidence digest must be a SHA-256 hex string")
    actual_digest = _sha256_canonical(evidence)
    if expected_digest.casefold() != actual_digest:
        raise ValueError(
            f"process evidence digest mismatch: manifest={expected_digest} actual={actual_digest}"
        )

    _mapping(acquisition_audit.get("counts"), "acquisition audit counts")
    _mapping(acquisition_audit.get("rejections"), "acquisition audit rejections")

    raw_records = _sequence(evidence.get("records"), "evidence.records")
    records: list[dict[str, object]] = []
    seen_evidence_ids: set[str] = set()
    for index, raw in enumerate(raw_records):
        record = _mapping(raw, f"evidence.records[{index}]")
        normalized = evidence_core.validate_evidence_record(record)
        supplied_id = record.get("evidence_id")
        if supplied_id is not None and supplied_id != normalized["evidence_id"]:
            raise ValueError(
                f"evidence.records[{index}] evidence_id is not canonical: "
                f"{supplied_id!r} != {normalized['evidence_id']!r}"
            )
        record_id = str(normalized["evidence_id"])
        if record_id in seen_evidence_ids:
            raise ValueError(f"duplicate evidence_id: {record_id}")
        seen_evidence_ids.add(record_id)
        records.append(normalized)

    selected = [record for record in records if record["selection_status"] == "selected"]
    for record in selected:
        if record["evidence_grade"] == "R1":
            raise ValueError(
                f"R1 record cannot be selected: {record['evidence_id']}"
            )

    selected_by_target: dict[str, dict[str, object]] = {}
    for record in selected:
        target = str(record["target_reduced_formula"])
        if target in selected_by_target:
            raise ValueError(f"duplicate selected target: {target}")
        selected_by_target[target] = record

    material_formulas = _material_formula_set(material_catalog)
    for target in selected_by_target:
        if target not in material_formulas:
            raise ValueError(f"selected target is absent from material catalog: {target}")

    recipe_entries = _recipe_entries(recipe_catalog)
    historical_targets: set[str] = set()
    generated: list[Mapping[str, object]] = []
    for index, entry in enumerate(recipe_entries):
        field = f"recipe catalog entries[{index}].target_formula"
        if entry.get("recipe_origin") == "evidence-expansion":
            target = _reduced_formula(entry.get("target_formula"), field)
            generated.append(entry)
            continue
        try:
            target = _reduced_formula(entry.get("target_formula"), field)
        except ValueError:
            # Historical recipes may intentionally use symbolic/nonstoichiometric
            # labels such as CoSx. They remain valid historical recipes but cannot
            # participate in fixed-formula material/evidence collision checks.
            continue
        historical_targets.add(target)

    collisions = sorted(set(selected_by_target).intersection(historical_targets))
    if collisions:
        raise ValueError(
            "selected target was already recipe-backed before expansion: "
            + ", ".join(collisions)
        )

    selected_by_id = {str(record["evidence_id"]): record for record in selected}
    generated_by_evidence: dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(generated):
        record_id = entry.get("evidence_record_id")
        if type(record_id) is not str or not record_id:
            raise ValueError(
                f"generated recipe {entry.get('recipe_id', index)!r} is missing evidence_record_id"
            )
        if record_id not in selected_by_id:
            raise ValueError(
                f"generated recipe {entry.get('recipe_id', index)!r} references missing selected evidence: {record_id}"
            )
        if record_id in generated_by_evidence:
            raise ValueError(f"multiple generated recipes link to selected evidence: {record_id}")
        record = selected_by_id[record_id]
        recipe_target = _reduced_formula(
            entry.get("target_formula"),
            f"generated recipe {entry.get('recipe_id', index)!r}.target_formula",
        )
        if recipe_target != record["target_reduced_formula"]:
            raise ValueError(
                f"generated recipe target does not match selected evidence: "
                f"{recipe_target} != {record['target_reduced_formula']}"
            )
        generated_by_evidence[record_id] = entry

    missing_recipes = sorted(set(selected_by_id).difference(generated_by_evidence))
    if missing_recipes:
        raise ValueError(
            "selected evidence has no generated recipe: " + ", ".join(missing_recipes)
        )

    return {
        "record_count": len(records),
        "selected_record_count": len(selected),
        "historical_recipe_backed_target_count": len(historical_targets),
        "generated_recipe_count": len(generated),
        "linked_generated_recipe_count": len(generated_by_evidence),
        "material_catalog_target_count": len(material_formulas),
        "process_evidence_sha256": actual_digest,
    }


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read JSON from {path}: {error}") from error
    return _mapping(value, str(path))


def _assert_canonical_file(path: Path, value: object) -> None:
    try:
        current = path.read_bytes()
    except OSError as error:
        raise ValueError(f"unable to read {path}: {error}") from error
    canonical = evidence_core.canonical_json_bytes(value)
    if current != canonical:
        raise ValueError(f"{path} is not canonical JSON")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--acquisition-audit", type=Path, default=ACQUISITION_AUDIT_PATH)
    parser.add_argument("--recipe-catalog", type=Path, default=RECIPE_CATALOG_PATH)
    parser.add_argument("--material-catalog", type=Path, default=MATERIAL_CATALOG_PATH)
    args = parser.parse_args(argv)

    try:
        evidence = _load_json(args.evidence)
        manifest = _load_json(args.manifest)
        acquisition = _load_json(args.acquisition_audit)
        recipe_catalog = _load_json(args.recipe_catalog)
        material_catalog = _load_json(args.material_catalog)
        _assert_canonical_file(args.evidence, evidence)
        _assert_canonical_file(args.manifest, manifest)
        _assert_canonical_file(args.acquisition_audit, acquisition)
        result = audit_evidence(
            evidence,
            manifest,
            acquisition,
            recipe_catalog,
            material_catalog,
        )
    except ValueError as error:
        print(f"recipe evidence audit failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
