"""Build deterministic simulator recipes from selected recipe-chemistry evidence.

Literature evidence controls only target identity, reactant identity, process
family, and publication provenance. All executable ordering/numbers emitted by
this module are fixed synthetic simulator values and are not literature process
conditions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import re
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ald_core as core
import ald_materials as materials
import ald_recipe_evidence as evidence_core


CATALOG_ROOT = _REPO_ROOT / "recipes" / "compounds"
EVIDENCE_PATH = _REPO_ROOT / "recipes" / "evidence" / "process-evidence.json"

SIMULATION_NOTICE = (
    "Literature-recognition chemistry only. Executable ordering and numbers are synthetic "
    "simulator values; not a physical fabrication recipe or machine-control instruction."
)

_DOSES = (0.20, 0.23, 0.26, 0.29, 0.32, 0.35)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: object) -> str:
    text = str(value).strip().casefold()
    return _SLUG_RE.sub("-", text).strip("-") or "material"


def _selected_record(record: Mapping[str, object]) -> dict[str, object]:
    normalized = evidence_core.validate_evidence_record(record)
    if normalized["selection_status"] != "selected":
        raise ValueError("recipe generation requires selection_status=selected")
    if normalized["evidence_grade"] not in {"R2", "R3"}:
        raise ValueError("recipe generation requires R2 or R3 evidence")
    reactants = normalized["reactants"]
    if not isinstance(reactants, Sequence) or isinstance(reactants, (str, bytes, bytearray)):
        raise ValueError("selected evidence reactants must be an array")
    if not 1 <= len(reactants) <= len(_DOSES):
        raise ValueError(f"selected evidence must contain 1-{len(_DOSES)} reactants")
    return normalized


def recipe_category(record: Mapping[str, object]) -> str:
    normalized = evidence_core.validate_evidence_record(record)
    family = str(normalized["process_family"])
    if family in {"mld", "hybrid"}:
        return "molecular_layer_deposition"

    _reduced, elements = materials.reduce_formula(str(normalized["target_formula"]))
    element_set = set(elements)
    if len(element_set) >= 3:
        return "ternary_and_multicomponent"
    if "O" in element_set:
        return "oxides"
    if "N" in element_set:
        return "nitrides"
    if element_set.intersection({"S", "Se", "Te"}):
        return "chalcogenides"
    if element_set.intersection({"C", "B"}):
        return "carbides_and_other_inorganics"
    return "research"


def _chemistry_digest(record: Mapping[str, object], length: int = 12) -> str:
    normalized = evidence_core.validate_evidence_record(record)
    value = str(normalized["chemistry_key"]).encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:length]


def recipe_filename(record: Mapping[str, object]) -> str:
    normalized = evidence_core.validate_evidence_record(record)
    formula_slug = _slug(normalized["target_formula"])
    return f"{formula_slug}_{_chemistry_digest(normalized, 10)}.json"


def _recipe_id(record: Mapping[str, object]) -> str:
    normalized = evidence_core.validate_evidence_record(record)
    formula_slug = _slug(normalized["target_formula"])
    return f"cat-exp-{formula_slug}-{_chemistry_digest(normalized, 12)}"


def _source_references(record: Mapping[str, object]) -> list[dict[str, str]]:
    publications = record.get("publications")
    if not isinstance(publications, Sequence) or isinstance(publications, (str, bytes, bytearray)):
        raise ValueError("selected evidence publications must be an array")
    references: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in publications:
        if not isinstance(raw, Mapping):
            raise ValueError("selected evidence publication must be an object")
        source_type = str(raw.get("type", "")).strip().casefold()
        identifier = str(raw.get("identifier", "")).strip()
        if not source_type or not identifier:
            raise ValueError("selected evidence publication reference is incomplete")
        key = (source_type, identifier)
        if key in seen:
            continue
        seen.add(key)
        references.append({"type": source_type, "identifier": identifier})
    references.sort(key=lambda item: (item["type"], item["identifier"]))
    if not references:
        raise ValueError("selected evidence has no source references")
    return references


def _precursors(record: Mapping[str, object]) -> tuple[dict[str, dict[str, str]], list[dict[str, object]]]:
    reactants = record.get("reactants")
    if not isinstance(reactants, Sequence) or isinstance(reactants, (str, bytes, bytearray)):
        raise ValueError("selected evidence reactants must be an array")

    precursors: dict[str, dict[str, str]] = {}
    exposures: list[dict[str, object]] = []
    display_names: set[str] = set()
    for index, raw in enumerate(reactants):
        if not isinstance(raw, Mapping):
            raise ValueError(f"reactants[{index}] must be an object")
        if index >= len(_DOSES):
            raise ValueError(f"at most {len(_DOSES)} reactants are supported")
        precursor_id = chr(ord("A") + index)
        label = str(raw.get("label", "")).strip()
        if not label:
            raise ValueError(f"reactants[{index}].label must be non-empty")
        name = str(raw.get("name") or label).strip()
        formula = str(raw.get("formula") or label).strip()
        role = str(raw.get("role", "")).strip()
        if not role:
            raise ValueError(f"reactants[{index}].role must be non-empty")
        if name in display_names:
            raise ValueError(f"duplicate precursor display name: {name}")
        display_names.add(name)
        precursors[precursor_id] = {"name": name, "formula": formula, "role": role}
        exposures.append(
            {
                "precursor": precursor_id,
                "dose": _DOSES[index],
                "purge_ms": 4000,
            }
        )
    if not precursors:
        raise ValueError("selected evidence must contain at least one reactant")
    return precursors, exposures


def build_recipe(record: Mapping[str, object]) -> dict[str, object]:
    normalized = _selected_record(record)
    precursors, exposures = _precursors(normalized)
    family = str(normalized["process_family"])
    raw: dict[str, object] = {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": _recipe_id(normalized),
        "metadata": {
            "recipe_schema": "multi-precursor/1",
            "target_material": str(normalized["target_material"]),
            "target_formula": str(normalized["target_formula"]),
            "chemistry_family": family,
            "chemistry_status": "literature-backed-simulation-surrogate",
            "product_family": "evidence-backed material chemistry",
            "process_family": family,
            "recipe_origin": "evidence-expansion",
            "evidence_record_id": str(normalized["evidence_id"]),
            "physical_fabrication_mapping": False,
            "simulation_notice": SIMULATION_NOTICE,
            "source_references": _source_references(normalized),
        },
        "precursors": precursors,
        "initial_conditions": {"temperature_c": 25.0, "pressure_pa": 101325.0},
        "limits": {
            "min_purge_ms": 1000,
            "max_temperature_c": 300.0,
            "max_pressure_pa": 200000.0,
            "max_cycles": 20,
            "max_runtime_ms": 500000,
            "max_residual_fraction": 0.05,
            "max_packet_bytes": 800,
        },
        "surface": {"model_version": "site-sequential/1"},
        "instructions": [
            {"opcode": "CONFIGURE", "arguments": {}},
            {
                "opcode": "SET_TEMPERATURE",
                "arguments": {"target_c": 25.0, "ramp_c_per_min": 1.0, "tolerance_c": 1.0},
            },
            {"opcode": "EVACUATE", "arguments": {"target_pa": 100.0, "timeout_ms": 100000}},
            {"opcode": "STABILIZE", "arguments": {"duration_ms": 1000}},
            {"opcode": "DEPOSITION_CYCLE", "arguments": {"exposures": exposures, "repeat": 1}},
            {
                "opcode": "MEASURE",
                "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]},
            },
            {
                "opcode": "SHUTDOWN",
                "arguments": {"heater_ramp_c_per_min": 1.0, "vent_target_pa": 101325.0},
            },
        ],
    }
    core.compile_recipe(core.validate_recipe(raw))
    return raw


def _canonical_recipe_bytes(value: object) -> bytes:
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


def expected_expansion_files(
    evidence: Mapping[str, object],
    root: Path = CATALOG_ROOT,
) -> dict[Path, bytes]:
    if evidence.get("schema") != evidence_core.EVIDENCE_SCHEMA:
        raise ValueError(f"unsupported evidence schema: {evidence.get('schema')!r}")
    records = evidence.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ValueError("evidence.records must be an array")

    result: dict[Path, bytes] = {}
    seen_targets: set[str] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise ValueError(f"evidence.records[{index}] must be an object")
        normalized = evidence_core.validate_evidence_record(raw)
        if normalized["selection_status"] != "selected":
            continue
        if normalized["evidence_grade"] not in {"R2", "R3"}:
            raise ValueError(f"selected record is not R2/R3: {normalized['evidence_id']}")
        target = str(normalized["target_reduced_formula"])
        if target in seen_targets:
            raise ValueError(f"duplicate selected target: {target}")
        seen_targets.add(target)
        path = root / recipe_category(normalized) / recipe_filename(normalized)
        if path in result:
            raise ValueError(f"duplicate expansion recipe path: {path}")
        result[path] = _canonical_recipe_bytes(build_recipe(normalized))
    return dict(sorted(result.items(), key=lambda item: item[0].as_posix()))


def _load_evidence(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read evidence from {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise ValueError("evidence document must be an object")
    return value


def _existing_generated_files(root: Path) -> set[Path]:
    result: set[Path] = set()
    if not root.exists():
        return result
    for path in root.rglob("*.json"):
        if path.name == "catalog.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metadata = raw.get("metadata") if isinstance(raw, Mapping) else None
        if isinstance(metadata, Mapping) and metadata.get("recipe_origin") == "evidence-expansion":
            result.add(path)
    return result


def _check_files(expected: Mapping[Path, bytes], root: Path) -> None:
    expected_paths = set(expected)
    existing_generated = _existing_generated_files(root)
    missing = sorted(path for path in expected_paths if not path.exists())
    stale = sorted(
        path
        for path, payload in expected.items()
        if path.exists() and path.read_bytes() != payload
    )
    extra = sorted(existing_generated - expected_paths)
    messages: list[str] = []
    if missing:
        messages.append("missing: " + ", ".join(path.relative_to(_REPO_ROOT).as_posix() for path in missing))
    if stale:
        messages.append("stale: " + ", ".join(path.relative_to(_REPO_ROOT).as_posix() for path in stale))
    if extra:
        messages.append("extra: " + ", ".join(path.relative_to(_REPO_ROOT).as_posix() for path in extra))
    if messages:
        raise ValueError("expansion recipe check failed; " + "; ".join(messages))


def _write_files(expected: Mapping[Path, bytes], root: Path) -> None:
    expected_paths = set(expected)
    for stale in sorted(_existing_generated_files(root) - expected_paths):
        stale.unlink()
    for path, payload in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_PATH)
    parser.add_argument("--root", type=Path, default=CATALOG_ROOT)
    args = parser.parse_args(argv)

    try:
        document = _load_evidence(args.evidence)
        expected = expected_expansion_files(document, args.root)
        if args.check:
            _check_files(expected, args.root)
        else:
            _write_files(expected, args.root)
    except (OSError, ValueError) as error:
        print(f"recipe expansion build failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps({"generated_recipe_count": len(expected)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
