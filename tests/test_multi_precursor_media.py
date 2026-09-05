import json
from pathlib import Path

import pytest

from ald_media_controller import ExitCode, main


RECIPE = Path("recipes/compounds/research/acceptance_three_precursor.json")


def _json_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_json_keys(item))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(_json_keys(item))
        return keys
    return set()


@pytest.mark.requires_ffmpeg
def test_multi_precursor_product_round_trip_matches_direct(tmp_path, capsys):
    direct = tmp_path / "direct"
    bundle = tmp_path / "product-bundle"
    media_run = tmp_path / "product-media"

    assert main(["simulate", str(RECIPE), "--seed", "42", "--output", str(direct)]) == int(ExitCode.OK)
    capsys.readouterr()
    assert main(["compile-product", str(RECIPE), "--seed", "42", "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()

    document = json.loads((bundle / "product.json").read_text(encoding="utf-8"))
    assert document["recipe_schema"] == "multi-precursor/1"
    assert document["target_material"] == "aluminum-doped zinc oxide"
    assert [item["id"] for item in document["precursor_sequence"]] == ["A", "B", "C", "B"]
    assert [item["name"] for item in document["precursor_sequence"]] == [
        "diethylzinc",
        "water",
        "trimethylaluminum",
        "water",
    ]
    keys = _json_keys(document)
    for forbidden in ("dose", "purge_ms", "temperature_c", "pressure_pa", "flow_sccm", "reaction_factors"):
        assert forbidden not in keys

    assert main(["verify-product", str(bundle / "bundle.json")]) == int(ExitCode.OK)
    capsys.readouterr()
    assert main([
        "simulate-product", str(bundle / "bundle.json"), "--seed", "42", "--output", str(media_run)
    ]) == int(ExitCode.OK)
    capsys.readouterr()

    for name in ("cycles.csv", "surface-final.json", "audit.jsonl"):
        assert (direct / name).read_bytes() == (media_run / name).read_bytes()


@pytest.mark.requires_ffmpeg
def test_multi_precursor_hls_round_trip_matches_direct(tmp_path, capsys):
    direct = tmp_path / "direct"
    bundle = tmp_path / "hls-bundle"
    media_run = tmp_path / "hls-media"

    assert main(["compile", str(RECIPE), "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()
    assert main(["verify", str(bundle / "stream.m3u8")]) == int(ExitCode.OK)
    capsys.readouterr()
    assert main(["simulate", str(RECIPE), "--seed", "42", "--output", str(direct)]) == int(ExitCode.OK)
    capsys.readouterr()
    assert main([
        "simulate-media", str(bundle / "stream.m3u8"), "--seed", "42", "--output", str(media_run)
    ]) == int(ExitCode.OK)
    capsys.readouterr()

    for name in ("cycles.csv", "surface-final.json", "audit.jsonl"):
        assert (direct / name).read_bytes() == (media_run / name).read_bytes()


@pytest.mark.requires_ffmpeg
def test_product_verify_rejects_changed_multi_precursor_dose(tmp_path, capsys):
    bundle = tmp_path / "product-bundle"
    assert main(["compile-product", str(RECIPE), "--seed", "42", "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()

    recipe_path = bundle / "recipe.canonical.json"
    raw = json.loads(recipe_path.read_text(encoding="utf-8"))
    cycle = next(item for item in raw["instructions"] if item["opcode"] == "DEPOSITION_CYCLE")
    cycle["arguments"]["exposures"][0]["dose"] += 0.01
    recipe_path.write_text(
        json.dumps(raw, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert main(["verify-product", str(bundle / "bundle.json")]) == int(ExitCode.INTEGRITY)
