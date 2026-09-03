import json
from pathlib import Path
import shutil

import pytest

from ald_media_controller import ExitCode, MediaVerificationError, main, parse_local_playlist


SAMPLE_RECIPE = Path("recipes/generic_al2o3.json")


def test_compile_refuses_existing_output(tmp_path):
    output = tmp_path / "exists"
    output.mkdir()

    result = main(["compile", str(SAMPLE_RECIPE), "--output", str(output)])

    assert result == int(ExitCode.OUTPUT)


def test_playlist_rejects_missing_required_independent_segments_tag(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "init.mp4").write_bytes(b"init")
    (bundle / "packet-000000.m4s").write_bytes(b"segment")
    manifest = bundle / "stream.m3u8"
    manifest.write_text(
        "\n".join(
            [
                "#EXTM3U",
                "#EXT-X-VERSION:7",
                "#EXT-X-TARGETDURATION:3",
                "#EXT-X-MEDIA-SEQUENCE:0",
                "#EXT-X-PLAYLIST-TYPE:VOD",
                '#EXT-X-MAP:URI="init.mp4"',
                "#EXTINF:3.000000,",
                "packet-000000.m4s",
                "#EXT-X-ENDLIST",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(MediaVerificationError, match="missing|required"):
        parse_local_playlist(manifest)


@pytest.mark.requires_ffmpeg
def test_compile_verify_and_media_simulation_are_equivalent(tmp_path, capsys):
    bundle = tmp_path / "bundle"
    direct = tmp_path / "direct"
    media = tmp_path / "media"

    assert main(["compile", str(SAMPLE_RECIPE), "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()
    assert (bundle / "stream.m3u8").is_file()
    assert (bundle / "init.mp4").is_file()
    assert (bundle / "bundle.json").is_file()
    assert (bundle / "recipe.canonical.json").is_file()

    assert main(["verify", str(bundle / "stream.m3u8")]) == int(ExitCode.OK)
    verification = json.loads(capsys.readouterr().out)
    assert verification["protocol"] == "ALD-MEDIA/1"
    assert verification["packet_count"] == 7
    assert len(verification["root_hash"]) == 64
    assert verification["signature_status"] == "UNSIGNED"

    assert main(
        [
            "simulate",
            str(SAMPLE_RECIPE),
            "--seed",
            "42",
            "--output",
            str(direct),
        ]
    ) == int(ExitCode.OK)
    capsys.readouterr()
    assert main(
        [
            "simulate-media",
            str(bundle / "stream.m3u8"),
            "--seed",
            "42",
            "--output",
            str(media),
        ]
    ) == int(ExitCode.OK)
    capsys.readouterr()

    for name in ("surface-final.json", "cycles.csv", "audit.jsonl"):
        assert (direct / name).read_bytes() == (media / name).read_bytes()


@pytest.mark.requires_ffmpeg
def test_verify_rejects_tampered_canonical_recipe_configuration(tmp_path, capsys):
    bundle = tmp_path / "bundle"

    assert main(["compile", str(SAMPLE_RECIPE), "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()

    recipe_path = bundle / "recipe.canonical.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["surface"]["sites_per_region"] += 1
    recipe_path.write_text(
        json.dumps(recipe, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert main(["verify", str(bundle / "stream.m3u8")]) == int(ExitCode.INTEGRITY)


@pytest.mark.requires_ffmpeg
def test_verify_rejects_unindexed_noncanonical_media_segment(tmp_path, capsys):
    bundle = tmp_path / "bundle"

    assert main(["compile", str(SAMPLE_RECIPE), "--output", str(bundle)]) == int(ExitCode.OK)
    capsys.readouterr()
    shutil.copy2(bundle / "packet-000000.m4s", bundle / "rogue.m4s")

    assert main(["verify", str(bundle / "stream.m3u8")]) == int(ExitCode.INTEGRITY)


@pytest.mark.requires_ffmpeg
def test_compile_overwrite_replaces_verified_bundle(tmp_path):
    bundle = tmp_path / "bundle"

    assert main(["compile", str(SAMPLE_RECIPE), "--output", str(bundle)]) == int(ExitCode.OK)
    first_index = (bundle / "bundle.json").read_bytes()

    assert main(["compile", str(SAMPLE_RECIPE), "--output", str(bundle)]) == int(ExitCode.OUTPUT)
    assert (bundle / "bundle.json").read_bytes() == first_index

    assert main(
        [
            "compile",
            str(SAMPLE_RECIPE),
            "--output",
            str(bundle),
            "--overwrite",
        ]
    ) == int(ExitCode.OK)
    assert (bundle / "bundle.json").read_bytes() == first_index
