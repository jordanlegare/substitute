from __future__ import annotations

import json
from pathlib import Path
import py_compile

import pytest

import ald_compatibility as compatibility
import ald_master


CATALOG = Path("recipes/compounds/catalog.json")
MODEL = Path("compatibility/model-v1.json")
EVIDENCE = Path("compatibility/evidence-overrides.json")
GUIDE = Path("docs/compatibility-engine.md")


@pytest.fixture(scope="module")
def real_catalog_snapshot() -> dict[str, object]:
    entries = ald_master.load_catalog(CATALOG)
    model = compatibility.load_model(MODEL)
    evidence = compatibility.load_evidence_overrides(EVIDENCE)
    return compatibility.build_compatibility_snapshot(entries, model, evidence)


def test_real_catalog_snapshot_is_exhaustive_and_byte_deterministic(
    real_catalog_snapshot: dict[str, object],
):
    snapshot = real_catalog_snapshot
    summary = snapshot["summary"]
    precursor_count = int(summary["unique_precursors"])
    material_count = int(summary["unique_materials"])

    assert precursor_count > 1
    assert material_count > 1
    assert len(snapshot["precursor_pairs"]) == precursor_count * (precursor_count - 1) // 2
    assert len(snapshot["material_interfaces"]) == material_count * (material_count - 1)

    entries = ald_master.load_catalog(CATALOG)
    rebuilt = compatibility.build_compatibility_snapshot(
        entries,
        compatibility.load_model(MODEL),
        compatibility.load_evidence_overrides(EVIDENCE),
    )
    assert compatibility.canonical_json_bytes(snapshot) == compatibility.canonical_json_bytes(
        rebuilt
    )


def test_real_catalog_reference_queries_and_candidate_ranking(
    real_catalog_snapshot: dict[str, object],
):
    snapshot = real_catalog_snapshot

    precursor_pair = compatibility.query_precursor(snapshot, "HfCl4", "H2O")
    assert {precursor_pair["a"]["formula"], precursor_pair["b"]["formula"]} == {
        "HfCl4",
        "H2O",
    }
    assert any(
        feature["family"] == "exact_process" and feature["available"]
        for feature in precursor_pair["features"]
    )

    material_edge = compatibility.query_material(snapshot, "HfO2", "Al2O3")
    assert material_edge["a"]["formula"] == "HfO2"
    assert material_edge["b"]["formula"] == "Al2O3"
    assert 0.0 <= float(material_edge["score"]) <= 100.0

    ranked = compatibility.rank_candidates(snapshot, min_size=2, max_size=6, top=10)
    assert ranked
    assert len(ranked) <= 10
    assert all(2 <= len(candidate["precursors"]) <= 6 for candidate in ranked)
    assert all(candidate["role_complete"] for candidate in ranked)


def test_real_catalog_cli_acceptance(tmp_path: Path, capsys):
    assert ald_master.main(["compatibility-report"]) == 0
    report = capsys.readouterr().out
    assert "Compatibility evidence report" in report

    output_a = tmp_path / "snapshot-a.json"
    output_b = tmp_path / "snapshot-b.json"
    for output in (output_a, output_b):
        assert ald_master.main(["compatibility-build", "--output", str(output)]) == 0
        assert output.exists()
        capsys.readouterr()
    assert output_a.read_bytes() == output_b.read_bytes()
    assert json.loads(output_a.read_text(encoding="utf-8"))["schema"] == (
        "ald-compatibility-snapshot/1"
    )

    assert ald_master.main(["compatible", "precursor", "HfCl4", "H2O"]) == 0
    assert "HfCl4" in capsys.readouterr().out

    assert ald_master.main(["compatible", "material", "HfO2", "Al2O3"]) == 0
    assert "HfO2" in capsys.readouterr().out

    assert (
        ald_master.main(
            [
                "candidates",
                "--min-size",
                "2",
                "--max-size",
                "6",
                "--top",
                "10",
            ]
        )
        == 0
    )
    assert "score=" in capsys.readouterr().out


def test_compatibility_modules_compile():
    for source in (
        "ald_compatibility.py",
        "ald_master.py",
        "ald_media_controller.py",
        "ald_media_cli.py",
    ):
        py_compile.compile(source, doraise=True)


def test_compatibility_guide_and_readme_document_real_catalog_workflow(
    real_catalog_snapshot: dict[str, object],
):
    summary = real_catalog_snapshot["summary"]
    diagnostic = json.dumps(summary, sort_keys=True)

    assert GUIDE.exists(), diagnostic
    guide = GUIDE.read_text(encoding="utf-8")
    for phrase in (
        "E0_UNKNOWN",
        "E4_DIRECT",
        "score",
        "coverage",
        "directed",
        "beam",
        "compatibility-build",
        "evidence-overrides.json",
        "chemical-mixing",
    ):
        assert phrase.casefold() in guide.casefold(), phrase

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Compatibility evidence engine" in readme
    for command in (
        "ald-master compatibility-report",
        "ald-master compatible precursor HfCl4 H2O",
        "ald-master compatible material HfO2 Al2O3",
        "ald-master candidates --min-size 2 --max-size 6 --top 20",
        "ald-master compatibility-build --output build/compatibility/snapshot.json",
    ):
        assert command in readme, command
