from __future__ import annotations

import json
from pathlib import Path

import ald_master
import ald_materials as materials


def _catalog(tmp_path: Path) -> Path:
    entries = [
        {
            "material_id": materials.material_id("Al2O3"),
            "name": "aluminum oxide",
            "formula": "Al2O3",
            "reduced_formula": "Al2O3",
            "elements": ["Al", "O"],
            "counted": True,
            "material_classes": ["oxide", "dielectric"],
            "aliases": ["alumina"],
            "identifiers": {"cod_ids": ["1001"]},
            "phases": [],
            "provenance": [{"source": "cod", "source_id": "1001", "evidence": "crystallographic_identity"}],
            "process_evidence": {"status": "executable-recipe", "recipe_ids": ["alumina-water"], "recipe_paths": ["recipes/alumina.json"]},
        },
        {
            "material_id": materials.material_id("HfO2"),
            "name": "hafnium dioxide",
            "formula": "HfO2",
            "reduced_formula": "HfO2",
            "elements": ["Hf", "O"],
            "counted": True,
            "material_classes": ["oxide", "dielectric"],
            "aliases": ["hafnia"],
            "identifiers": {"cod_ids": ["1002"]},
            "phases": [],
            "provenance": [{"source": "cod", "source_id": "1002", "evidence": "crystallographic_identity"}],
            "process_evidence": {"status": "identity-only", "recipe_ids": [], "recipe_paths": []},
        },
    ]
    path = tmp_path / "materials.json"
    path.write_bytes(
        materials.canonical_json_bytes(
            {
                "catalog_schema": materials.CATALOG_SCHEMA,
                "counted_non_elemental_reduced_formula_count": 2,
                "entries": entries,
            }
        )
    )
    return path


def test_parser_accepts_material_discovery_commands():
    args = ald_master.build_parser().parse_args(
        [
            "--materials-catalog",
            "custom-materials.json",
            "materials",
            "search",
            "hafnia",
            "--limit",
            "7",
            "--json",
        ]
    )
    assert args.command == "materials"
    assert args.material_action == "search"
    assert args.materials_catalog == Path("custom-materials.json")
    assert args.text == "hafnia"
    assert args.limit == 7
    assert args.json is True


def test_material_search_show_list_and_report_json(tmp_path: Path, capsys):
    catalog = _catalog(tmp_path)

    assert ald_master.main(["--materials-catalog", str(catalog), "materials", "search", "hafnia", "--json"]) == 0
    search = json.loads(capsys.readouterr().out)
    assert [item["formula"] for item in search] == ["HfO2"]

    assert ald_master.main(["--materials-catalog", str(catalog), "materials", "show", "HfO2", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["name"] == "hafnium dioxide"
    assert shown["process_evidence"]["status"] == "identity-only"

    assert ald_master.main(["--materials-catalog", str(catalog), "materials", "list", "--class", "oxide", "--element", "Hf", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["formula"] for item in listed] == ["HfO2"]

    assert ald_master.main(["--materials-catalog", str(catalog), "materials", "report", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counted_non_elemental_reduced_formula_count"] == 2
    assert report["recipe_linked_materials"] == 1


def test_material_not_found_returns_exit_two(tmp_path: Path, capsys):
    catalog = _catalog(tmp_path)
    code = ald_master.main(["--materials-catalog", str(catalog), "materials", "show", "NotARealMaterial"])
    assert code == 2
    assert "unknown material" in capsys.readouterr().err


def test_catalog_only_material_compatibility_is_explicit_unknown(tmp_path: Path, monkeypatch, capsys):
    catalog = _catalog(tmp_path)
    snapshot = {
        "schema": "ald-compatibility-snapshot/1",
        "safety_notice": "offline simulation evidence only",
        "materials": [
            {"id": "m-al2o3", "name": "aluminum oxide", "formula": "Al2O3", "aliases": []}
        ],
        "material_interfaces": [],
        "precursors": [],
        "precursor_pairs": [],
    }
    monkeypatch.setattr(ald_master, "_build_compatibility_snapshot_from_args", lambda args: snapshot)

    code = ald_master.main(
        [
            "--materials-catalog",
            str(catalog),
            "compatible",
            "material",
            "HfO2",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["identity_known"] is True
    assert result["evidence_level"] == "E0_UNKNOWN"
    assert result["verdict"] == "UNKNOWN"
    assert result["compatibility_evidence_available"] is False
    assert result["material"]["formula"] == "HfO2"
