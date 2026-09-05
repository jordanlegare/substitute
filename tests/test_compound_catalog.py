from collections import Counter
import json
from pathlib import Path

import ald_core as core
from tools.build_compound_catalog import build_compound_catalog, canonical_catalog_bytes


ROOT = Path("recipes/compounds")
CATALOG = ROOT / "catalog.json"
FORBIDDEN_METADATA_KEYS = {
    "process_temperature",
    "pulse_time",
    "flow_sccm",
    "process_pressure",
    "growth_window",
    "dose_time",
    "handling_notes",
}


def load_catalog_entries():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]


def iter_catalog_recipe_json():
    for entry in load_catalog_entries():
        path = Path(entry["path"])
        yield path, json.loads(path.read_text(encoding="utf-8"))


def deposition_exposures(raw):
    cycles = [item for item in raw["instructions"] if item["opcode"] == "DEPOSITION_CYCLE"]
    assert cycles
    return cycles[0]["arguments"]["exposures"]


def test_checked_in_catalog_is_current_and_canonical():
    assert CATALOG.read_bytes() == canonical_catalog_bytes(build_compound_catalog())


def test_catalog_entries_are_unique_and_non_operational():
    entries = load_catalog_entries()
    assert len({entry["recipe_id"] for entry in entries}) == len(entries)
    assert [entry["path"] for entry in entries] == sorted(entry["path"] for entry in entries)
    for entry in entries:
        path = Path(entry["path"])
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["metadata"]["physical_fabrication_mapping"] is False, path
        assert not FORBIDDEN_METADATA_KEYS.intersection(raw["metadata"]), path
        assert raw["metadata"]["recipe_schema"] == "multi-precursor/1", path
        assert raw["surface"]["model_version"] == "site-sequential/1", path
        assert raw["metadata"]["source_references"], path
        names = [value["name"] for value in raw["precursors"].values()]
        assert len(names) == len(set(names)), path
        used = {item["precursor"] for item in deposition_exposures(raw)}
        assert used == set(raw["precursors"]), path
        core.compile_recipe(core.validate_recipe(raw))


def test_catalog_meets_coverage_floors():
    entries = load_catalog_entries()
    category = Counter(entry["category"] for entry in entries)
    counts = Counter(entry["precursor_count"] for entry in entries)
    assert len(entries) >= 100
    assert category["oxides"] >= 30
    assert category["nitrides"] >= 10
    assert category["chalcogenides"] >= 10
    assert sum(category[name] for name in ("metals", "carbides_and_other_inorganics")) >= 10
    assert sum(category[name] for name in ("ternary_and_multicomponent", "nanolaminates_and_supercycles")) >= 15
    assert sum(category[name] for name in ("molecular_layer_deposition", "research")) >= 15
    assert counts[3] >= 15
    assert counts[4] >= 8
    assert counts[5] >= 4
    assert counts[6] >= 4


def test_five_and_six_precursor_recipes_are_not_padded():
    for path, raw in iter_catalog_recipe_json():
        if len(raw["precursors"]) < 5:
            continue
        names = [item["name"] for item in raw["precursors"].values()]
        assert len(names) == len(set(names)), path
        used = {item["precursor"] for item in deposition_exposures(raw)}
        assert used == set(raw["precursors"]), path
        if raw["metadata"]["chemistry_status"] != "conceptual-multicomponent-surrogate":
            assert raw["metadata"]["source_references"], path
