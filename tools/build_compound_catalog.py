"""Build and verify the deterministic ALD/MLD compound-recipe index."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from typing import Any

# The tool is invoked from the repository root in CI and by authors.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ald_core as core


CATALOG_ROOT = _REPO_ROOT / "recipes" / "compounds"
CATALOG_PATH = CATALOG_ROOT / "catalog.json"
CATEGORY_DIRS = (
    "oxides",
    "nitrides",
    "chalcogenides",
    "metals",
    "carbides_and_other_inorganics",
    "ternary_and_multicomponent",
    "nanolaminates_and_supercycles",
    "molecular_layer_deposition",
    "research",
)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, list):
        return [_thaw(item) for item in value]
    return value


def _source_references(metadata: Mapping[str, Any], path: Path) -> list[dict[str, str]]:
    raw = metadata.get("source_references")
    if not isinstance(raw, tuple) or not raw:
        raise ValueError(f"{path}: metadata.source_references must be a non-empty array")
    references: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != {"type", "identifier"}:
            raise ValueError(f"{path}: source_references[{index}] must contain type and identifier")
        source_type = item["type"]
        identifier = item["identifier"]
        if type(source_type) is not str or not source_type or type(identifier) is not str or not identifier:
            raise ValueError(f"{path}: source reference values must be non-empty strings")
        references.append({"type": source_type, "identifier": identifier})
    return references


def _deposition_signature(recipe: core.Recipe, path: Path) -> list[str]:
    cycles = [instruction for instruction in recipe.instructions if instruction["opcode"] == "DEPOSITION_CYCLE"]
    if not cycles:
        raise ValueError(f"{path}: catalog recipe has no DEPOSITION_CYCLE")
    return [item["precursor"] for item in cycles[0]["arguments"]["exposures"]]


def _entry(path: Path, recipe: core.Recipe) -> dict[str, object]:
    metadata = recipe.metadata
    if metadata.get("recipe_schema") != "multi-precursor/1":
        raise ValueError(f"{path}: catalog recipes must use multi-precursor/1")
    if metadata.get("physical_fabrication_mapping") is not False:
        raise ValueError(f"{path}: physical_fabrication_mapping must be false")
    category = path.parent.name
    if category not in CATEGORY_DIRS:
        raise ValueError(f"{path}: unsupported catalog category")

    required_strings = (
        "target_material",
        "target_formula",
        "chemistry_family",
        "chemistry_status",
        "product_family",
        "simulation_notice",
    )
    normalized_strings: dict[str, str] = {}
    for field in required_strings:
        value = metadata.get(field)
        if type(value) is not str or not value:
            raise ValueError(f"{path}: metadata.{field} must be a non-empty string")
        normalized_strings[field] = value

    precursor_names = [recipe.precursors[key]["name"] for key in recipe.precursors]
    if len(set(precursor_names)) != len(precursor_names):
        raise ValueError(f"{path}: precursor chemical names must be unique")

    return {
        "category": category,
        "chemistry_family": normalized_strings["chemistry_family"],
        "chemistry_status": normalized_strings["chemistry_status"],
        "path": path.relative_to(_REPO_ROOT).as_posix(),
        "precursor_count": len(recipe.precursors),
        "precursors": [
            {
                "formula": recipe.precursors[key]["formula"],
                "id": key,
                "name": recipe.precursors[key]["name"],
                "role": recipe.precursors[key]["role"],
            }
            for key in recipe.precursors
        ],
        "product_family": normalized_strings["product_family"],
        "recipe_id": recipe.recipe_id,
        "source_references": _source_references(metadata, path),
        "target_formula": normalized_strings["target_formula"],
        "target_material": normalized_strings["target_material"],
        "exposure_signature": _deposition_signature(recipe, path),
    }


def iter_recipe_paths(root: Path = CATALOG_ROOT):
    for category in CATEGORY_DIRS:
        directory = root / category
        if not directory.exists():
            continue
        yield from sorted(directory.glob("*.json"))


def build_compound_catalog(root: Path = CATALOG_ROOT) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for path in iter_recipe_paths(root):
        recipe = core.validate_recipe(core.load_recipe(path))
        if recipe.recipe_id in seen_ids:
            raise ValueError(f"duplicate recipe_id: {recipe.recipe_id}")
        seen_ids.add(recipe.recipe_id)
        entries.append(_entry(path, recipe))
    entries.sort(key=lambda item: str(item["path"]))
    return {
        "catalog_schema": "ald-compound-catalog/1",
        "entry_count": len(entries),
        "entries": entries,
    }


def canonical_catalog_bytes(value: object) -> bytes:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if catalog.json is not canonical/current")
    args = parser.parse_args(argv)
    generated = canonical_catalog_bytes(build_compound_catalog())
    if args.check:
        try:
            current = CATALOG_PATH.read_bytes()
        except OSError as error:
            print(f"catalog check failed: unable to read {CATALOG_PATH}: {error}", file=sys.stderr)
            return 1
        if current != generated:
            print("catalog check failed: recipes/compounds/catalog.json is stale; run tools/build_compound_catalog.py", file=sys.stderr)
            return 1
        return 0
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_bytes(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
