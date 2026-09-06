from __future__ import annotations

import json
from pathlib import Path

import ald_master
import ald_materials as materials
import ald_recipe_evidence as evidence_core


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _fixture_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    evidence = evidence_core.validate_evidence_record(
        {
            "target_material": "titanium dioxide",
            "target_formula": "TiO2",
            "material_id": materials.material_id("O2Ti"),
            "process_family": "plasma-ald",
            "reactants": [
                {
                    "label": "TiCl4",
                    "name": "titanium tetrachloride",
                    "formula": "TiCl4",
                    "role": "reactant-a",
                },
                {"label": "O2 plasma", "role": "reactant-b"},
            ],
            "publications": [
                {
                    "type": "doi",
                    "identifier": "10.1234/tio2-direct",
                    "direct": True,
                    "title": "Plasma ALD of titanium dioxide",
                    "year": 2024,
                    "journal": "Example Journal",
                }
            ],
            "discovery_sources": ["atomiclimits", "crossref"],
            "evidence_grade": "R3",
            "selection_status": "selected",
        }
    )
    recipe_catalog = {
        "catalog_schema": "ald-compound-catalog/1",
        "entry_count": 1,
        "entries": [
            {
                "category": "oxides",
                "chemistry_family": "plasma-ald",
                "chemistry_status": "literature-backed-simulation-surrogate",
                "path": "recipes/compounds/oxides/tio2_expansion.json",
                "precursor_count": 2,
                "precursors": [
                    {
                        "formula": "TiCl4",
                        "id": "A",
                        "name": "titanium tetrachloride",
                        "role": "reactant-a",
                    },
                    {
                        "formula": "O2 plasma",
                        "id": "B",
                        "name": "O2 plasma",
                        "role": "reactant-b",
                    },
                ],
                "product_family": "evidence-backed material chemistry",
                "recipe_id": "cat-exp-tio2-abc123",
                "source_references": [
                    {"type": "doi", "identifier": "10.1234/tio2-direct"}
                ],
                "target_formula": "TiO2",
                "target_material": "titanium dioxide",
                "exposure_signature": ["A", "B"],
                "recipe_origin": "evidence-expansion",
                "evidence_record_id": evidence["evidence_id"],
                "process_family": "plasma-ald",
            }
        ],
    }
    material_catalog = {
        "catalog_schema": materials.CATALOG_SCHEMA,
        "counted_non_elemental_reduced_formula_count": 1,
        "entries": [
            {
                "material_id": materials.material_id("O2Ti"),
                "name": "titanium dioxide",
                "formula": "TiO2",
                "reduced_formula": "O2Ti",
                "elements": ["O", "Ti"],
                "counted": True,
                "material_classes": ["oxide"],
                "aliases": ["titania"],
                "identifiers": {},
                "phases": [],
                "provenance": [],
                "process_evidence": {
                    "status": "executable-recipe",
                    "recipe_ids": ["cat-exp-tio2-abc123"],
                    "recipe_paths": ["recipes/compounds/oxides/tio2_expansion.json"],
                },
            }
        ],
    }
    return (
        _write_json(tmp_path / "recipes.json", recipe_catalog),
        _write_json(
            tmp_path / "evidence.json",
            {"schema": evidence_core.EVIDENCE_SCHEMA, "records": [evidence]},
        ),
        _write_json(tmp_path / "materials.json", material_catalog),
    )


def _base_args(recipe_catalog: Path, evidence: Path, material_catalog: Path) -> list[str]:
    return [
        "--catalog",
        str(recipe_catalog),
        "--recipe-evidence",
        str(evidence),
        "--materials-catalog",
        str(material_catalog),
    ]


def test_parser_accepts_chemistry_namespace_and_filters():
    args = ald_master.build_parser().parse_args(
        [
            "--recipe-evidence",
            "custom-evidence.json",
            "chemistry",
            "list",
            "--process-family",
            "plasma-ald",
            "--chemistry-family",
            "oxide",
            "--element",
            "Ti",
            "--precursor",
            "TiCl4",
            "--evidence",
            "R3",
            "--origin",
            "expansion",
            "--limit",
            "7",
            "--json",
        ]
    )
    assert args.command == "chemistry"
    assert args.chemistry_action == "list"
    assert args.recipe_evidence == Path("custom-evidence.json")
    assert args.process_family == "plasma-ald"
    assert args.chemistry_family == "oxide"
    assert args.element == "Ti"
    assert args.precursor == "TiCl4"
    assert args.evidence == "R3"
    assert args.origin == "expansion"
    assert args.limit == 7
    assert args.json is True


def test_chemistry_search_show_sources_and_report_json(tmp_path: Path, capsys):
    recipe_catalog, evidence, material_catalog = _fixture_files(tmp_path)
    base = _base_args(recipe_catalog, evidence, material_catalog)

    assert ald_master.main([*base, "chemistry", "search", "TiCl4", "--json"]) == 0
    search = json.loads(capsys.readouterr().out)
    assert [item["recipe_id"] for item in search] == ["cat-exp-tio2-abc123"]

    assert ald_master.main([*base, "chemistry", "show", "TiO2", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert len(shown) == 1
    assert shown[0]["evidence_grade"] == "R3"
    assert shown[0]["reactants"][1]["label"] == "O2 plasma"

    assert ald_master.main([*base, "chemistry", "sources", "TiO2", "--json"]) == 0
    sources = json.loads(capsys.readouterr().out)
    assert sources[0]["identifier"] == "10.1234/tio2-direct"

    assert ald_master.main([*base, "chemistry", "report", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_executable_recipes"] == 1
    assert report["expansion_recipe_count"] == 1
    assert report["remaining_identity_only_materials"] == 0


def test_human_chemistry_show_is_non_operational(tmp_path: Path, capsys):
    recipe_catalog, evidence, material_catalog = _fixture_files(tmp_path)
    base = _base_args(recipe_catalog, evidence, material_catalog)

    assert ald_master.main([*base, "chemistry", "show", "TiO2"]) == 0
    output = capsys.readouterr().out
    folded = output.casefold()
    assert "tio2" in folded
    assert "plasma-ald" in folded
    assert "ticl4" in folded
    assert "o2 plasma" in folded
    assert "10.1234/tio2-direct" in folded
    assert "simulation" in folded
    for forbidden in (
        "purge_ms",
        "temperature_c",
        "pressure_pa",
        "plasma_power",
        "flow_sccm",
        "dose=",
    ):
        assert forbidden not in folded


def test_material_show_hints_at_recipe_chemistry(tmp_path: Path, capsys):
    recipe_catalog, evidence, material_catalog = _fixture_files(tmp_path)
    base = _base_args(recipe_catalog, evidence, material_catalog)

    assert ald_master.main([*base, "materials", "show", "TiO2"]) == 0
    output = capsys.readouterr().out
    assert "cat-exp-tio2-abc123" in output
    assert "ald-master chemistry show cat-exp-tio2-abc123" in output


def test_unknown_chemistry_returns_exit_two(tmp_path: Path, capsys):
    recipe_catalog, evidence, material_catalog = _fixture_files(tmp_path)
    base = _base_args(recipe_catalog, evidence, material_catalog)
    assert ald_master.main([*base, "chemistry", "show", "NotARealChemistry"]) == 2
    assert "unknown chemistry" in capsys.readouterr().err


def test_empty_chemistry_search_returns_exit_one(tmp_path: Path, capsys):
    recipe_catalog, evidence, material_catalog = _fixture_files(tmp_path)
    base = _base_args(recipe_catalog, evidence, material_catalog)
    assert ald_master.main([*base, "chemistry", "search", "unmatched-text"]) == 1
    assert "no recipe chemistries" in capsys.readouterr().out.casefold()
