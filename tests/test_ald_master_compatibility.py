from __future__ import annotations

import json
from pathlib import Path

import pytest

import ald_compatibility as compatibility
import ald_master


SAFETY = (
    "Compatibility is evidence support for offline simulation research only; "
    "it is not a chemical-mixing, equipment-safety, or fabrication-readiness determination."
)


def sample_snapshot() -> dict[str, object]:
    return {
        "schema": "ald-compatibility-snapshot/1",
        "safety_notice": SAFETY,
        "model_digest": "model",
        "catalog_digest": "catalog",
        "evidence_digest": "evidence",
        "precursors": [],
        "materials": [],
        "recipes": [],
        "precursor_pairs": [],
        "material_interfaces": [],
        "summary": {
            "unique_precursors": 4,
            "precursor_pairs": 6,
            "unique_materials": 3,
            "directed_material_interfaces": 6,
            "precursor_verdicts": {"SUPPORTED": 2, "UNKNOWN": 4},
            "precursor_evidence_levels": {"E4_DIRECT": 2, "E0_UNKNOWN": 4},
            "material_verdicts": {"UNKNOWN": 6},
            "material_evidence_levels": {"E0_UNKNOWN": 6},
        },
        "candidate_model": {
            "weights": {
                "harmonic": 0.40,
                "minimum": 0.20,
                "coverage": 0.15,
                "roles": 0.15,
                "known": 0.10,
            },
            "beam_width": 50,
            "default_top": 20,
        },
    }


def test_parser_accepts_compatible_precursor_query():
    args = ald_master.build_parser().parse_args(
        ["compatible", "precursor", "HfCl4", "H2O", "--json"]
    )

    assert args.command == "compatible"
    assert args.graph == "precursor"
    assert args.entities == ["HfCl4", "H2O"]
    assert args.json is True


def test_parser_accepts_candidate_filters_and_model_inputs():
    args = ald_master.build_parser().parse_args(
        [
            "--compat-model",
            "compatibility/custom-model.json",
            "--compat-evidence",
            "compatibility/custom-evidence.json",
            "candidates",
            "--min-size",
            "3",
            "--max-size",
            "6",
            "--top",
            "30",
            "--beam-width",
            "100",
            "--search",
            "hafnium",
            "--novel-only",
            "--minimum-score",
            "55",
            "--minimum-evidence",
            "E2_ANALOGUE",
            "--json",
        ]
    )

    assert args.command == "candidates"
    assert args.compat_model == Path("compatibility/custom-model.json")
    assert args.compat_evidence == Path("compatibility/custom-evidence.json")
    assert (args.min_size, args.max_size, args.top, args.beam_width) == (3, 6, 30, 100)
    assert args.search == "hafnium"
    assert args.novel_only is True
    assert args.minimum_score == pytest.approx(55.0)
    assert args.minimum_evidence == "E2_ANALOGUE"
    assert args.json is True


def test_parser_accepts_explain_candidate_two_through_six_entities():
    args = ald_master.build_parser().parse_args(
        ["explain", "candidate", "HfCl4", "ZrCl4", "H2O", "--json"]
    )

    assert args.command == "explain"
    assert args.graph == "candidate"
    assert args.entities == ["HfCl4", "ZrCl4", "H2O"]


def test_compatibility_build_writes_canonical_snapshot(monkeypatch, tmp_path: Path):
    snapshot = sample_snapshot()
    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        ald_master,
        "_build_compatibility_snapshot_from_args",
        lambda args: snapshot,
        raising=False,
    )

    code = ald_master.main(["compatibility-build", "--output", str(output)])

    assert code == 0
    assert output.read_bytes() == compatibility.canonical_json_bytes(snapshot)


def test_compatible_precursor_json_is_machine_readable(monkeypatch, capsys):
    snapshot = sample_snapshot()
    pair = {
        "id": "pp-test",
        "a": {"id": "p-a", "name": "hafnium tetrachloride", "formula": "HfCl4"},
        "b": {"id": "p-b", "name": "water", "formula": "H2O"},
        "score": 90.0,
        "coverage": 0.6,
        "evidence_level": "E4_DIRECT",
        "verdict": "SUPPORTED",
        "features": [],
        "recipe_ids": ["hafnia-water"],
    }
    monkeypatch.setattr(
        ald_master,
        "_build_compatibility_snapshot_from_args",
        lambda args: snapshot,
        raising=False,
    )
    monkeypatch.setattr(compatibility, "query_precursor", lambda *args, **kwargs: pair)

    code = ald_master.main(
        ["compatible", "precursor", "HfCl4", "H2O", "--json"]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == pair


def test_compatibility_report_human_output_includes_counts_and_safety(monkeypatch, capsys):
    monkeypatch.setattr(
        ald_master,
        "_build_compatibility_snapshot_from_args",
        lambda args: sample_snapshot(),
        raising=False,
    )

    code = ald_master.main(["compatibility-report"])
    output = capsys.readouterr().out

    assert code == 0
    assert "4" in output and "6" in output
    assert "offline" in output.casefold()
    assert "safety" in output.casefold() or "chemical-mixing" in output.casefold()


def test_candidate_dispatch_passes_all_filters(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        ald_master,
        "_build_compatibility_snapshot_from_args",
        lambda args: sample_snapshot(),
        raising=False,
    )

    def fake_rank(snapshot, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(compatibility, "rank_candidates", fake_rank)

    code = ald_master.main(
        [
            "candidates",
            "--min-size",
            "3",
            "--max-size",
            "5",
            "--top",
            "7",
            "--beam-width",
            "40",
            "--search",
            "hafnium",
            "--novel-only",
            "--minimum-score",
            "61",
            "--minimum-evidence",
            "E2_ANALOGUE",
            "--json",
        ]
    )

    assert code == 0
    assert captured == {
        "min_size": 3,
        "max_size": 5,
        "top": 7,
        "beam_width": 40,
        "search": "hafnium",
        "novel_only": True,
        "minimum_score": 61.0,
        "minimum_evidence": "E2_ANALOGUE",
    }
    assert json.loads(capsys.readouterr().out) == []


def test_candidate_size_validation_returns_exit_two(monkeypatch, capsys):
    monkeypatch.setattr(
        ald_master,
        "_build_compatibility_snapshot_from_args",
        lambda args: sample_snapshot(),
        raising=False,
    )

    code = ald_master.main(["candidates", "--min-size", "6", "--max-size", "2"])

    assert code == 2
    assert "2 through 6" in capsys.readouterr().err


def test_pyproject_packages_compatibility_module_and_facade():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"ald_compatibility"' in text
    assert 'packages = ["ald_compatibility"' in text
