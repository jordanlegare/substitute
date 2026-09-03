from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import pytest

from ald_media_controller import (
    DEFAULT_MEDIA_PROFILE,
    DependencyError,
    MediaBuildError,
    MediaVerificationError,
    compile_recipe,
    load_recipe,
    mux_packet_mp4,
    package_hls,
    parse_local_playlist,
    probe_media_capabilities,
    probe_media_json,
    run_media_tool,
    stage_packet_media,
    validate_recipe,
    write_bundle_index,
)


def _success(args, stdout=""):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


@pytest.fixture(scope="module")
def media_capabilities():
    try:
        return probe_media_capabilities()
    except DependencyError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def compiled_recipe():
    return compile_recipe(validate_recipe(load_recipe(Path("recipes/generic_al2o3.json"))))


@pytest.fixture(scope="module")
def staged_artifacts(compiled_recipe, tmp_path_factory):
    directory = tmp_path_factory.mktemp("packet-media") / "artifacts"
    return stage_packet_media(compiled_recipe, directory, DEFAULT_MEDIA_PROFILE)


@pytest.fixture(scope="module")
def packet_mp4s(staged_artifacts, media_capabilities, tmp_path_factory):
    directory = tmp_path_factory.mktemp("packet-mp4s")
    return tuple(
        mux_packet_mp4(
            artifact,
            directory / f"packet-{artifact.sequence:06d}.mp4",
            media_capabilities,
            DEFAULT_MEDIA_PROFILE,
        )
        for artifact in staged_artifacts
    )


def _write_playlist(
    directory: Path,
    *,
    init_uri: str = "init.mp4",
    segment_uri: str = "packet-000000.m4s",
    duration: float = 3.0,
    extra_tags: tuple[str, ...] = (),
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if init_uri == "init.mp4":
        (directory / init_uri).write_bytes(b"init")
    if segment_uri == "packet-000000.m4s":
        (directory / segment_uri).write_bytes(b"segment")
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-TARGETDURATION:3",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{init_uri}"',
        *extra_tags,
        f"#EXTINF:{duration:.6f},",
        segment_uri,
        "#EXT-X-ENDLIST",
    ]
    path = directory / "stream.m3u8"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_missing_ffmpeg_maps_to_dependency_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}")
    with pytest.raises(DependencyError, match="ffmpeg"):
        probe_media_capabilities()


def test_missing_ffprobe_maps_to_dependency_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "ffprobe" else f"/usr/bin/{name}")
    with pytest.raises(DependencyError, match="ffprobe"):
        probe_media_capabilities()


def test_media_runner_uses_argument_vector_without_shell_or_stdin(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _success(args[0], "ffprobe version fake")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_media_tool(["ffprobe", "-version"], timeout_seconds=5.0)

    assert result.returncode == 0
    positional, keyword = calls[0]
    assert positional == (["ffprobe", "-version"],)
    assert keyword["shell"] is False
    assert keyword["check"] is False
    assert keyword["text"] is True
    assert keyword["encoding"] == "utf-8"
    assert keyword["errors"] == "replace"
    assert keyword["capture_output"] is True
    assert keyword["stdin"] is subprocess.DEVNULL
    assert keyword["timeout"] == 5.0


def test_media_runner_rejects_nonzero_status_with_bounded_stderr(monkeypatch):
    stderr = "\n".join(f"line-{index}" for index in range(30))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=9, stdout="ignored", stderr=stderr
        ),
    )

    with pytest.raises(MediaBuildError) as caught:
        run_media_tool(["ffmpeg", "-version"], timeout_seconds=5.0)

    message = str(caught.value)
    assert "ffmpeg" in message
    assert "9" in message
    assert "line-10" in message
    assert "line-29" in message
    assert "line-9" not in message
    assert "ignored" not in message


def test_media_runner_rejects_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], stderr="last failure line")

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(MediaBuildError, match="timed out"):
        run_media_tool(["ffmpeg", "-version"], timeout_seconds=0.25)


def test_capability_probe_selects_libx264_and_required_formats(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/media/{name}")

    def fake_run(args, timeout_seconds):
        if args[-1] == "-encoders":
            return _success(args, " V..... libx264 H.264\n A..... aac AAC")
        if args[-1] == "-muxers":
            return _success(args, " E mp4 MP4\n E hls Apple HTTP Live Streaming")
        if args[-1] == "-demuxers":
            return _success(args, " D mov,mp4,m4a,3gp,3g2,mj2 QuickTime / MOV\n D hls Apple HTTP Live Streaming")
        raise AssertionError(args)

    monkeypatch.setattr("ald_hls_integration.run_media_tool", fake_run)
    capabilities = probe_media_capabilities()

    assert capabilities.ffmpeg.as_posix() == "/opt/media/ffmpeg"
    assert capabilities.ffprobe.as_posix() == "/opt/media/ffprobe"
    assert capabilities.video_encoder == "libx264"
    assert capabilities.audio_encoder == "aac"


def test_capability_probe_rejects_missing_hls_muxer(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/opt/media/{name}")

    def fake_run(args, timeout_seconds):
        if args[-1] == "-encoders":
            return _success(args, " V..... libx264 H.264\n A..... aac AAC")
        if args[-1] == "-muxers":
            return _success(args, " E mp4 MP4")
        if args[-1] == "-demuxers":
            return _success(args, " D mov,mp4,m4a,3gp,3g2,mj2 QuickTime / MOV\n D hls HLS")
        raise AssertionError(args)

    monkeypatch.setattr("ald_hls_integration.run_media_tool", fake_run)
    with pytest.raises(DependencyError, match="hls"):
        probe_media_capabilities()


@pytest.mark.requires_ffmpeg
def test_packet_mp4_has_expected_streams(staged_artifacts, media_capabilities, tmp_path):
    mp4 = mux_packet_mp4(
        staged_artifacts[0],
        tmp_path / "packet.mp4",
        media_capabilities,
        DEFAULT_MEDIA_PROFILE,
    )
    probe = probe_media_json(mp4, media_capabilities)
    streams = {stream["codec_type"]: stream for stream in probe["streams"]}

    assert set(streams) == {"video", "audio"}
    assert streams["video"]["codec_name"] == "h264"
    assert int(streams["video"]["width"]) == 1920
    assert int(streams["video"]["height"]) == 1080
    assert streams["audio"]["codec_name"] == "aac"
    assert int(streams["audio"]["sample_rate"]) == 48000
    assert int(streams["audio"]["channels"]) == 1
    assert float(probe["format"]["duration"]) == pytest.approx(3.0, abs=0.05)


@pytest.mark.requires_ffmpeg
def test_hls_has_one_three_second_segment_per_packet(packet_mp4s, media_capabilities, tmp_path):
    manifest = package_hls(
        packet_mp4s,
        tmp_path / "hls",
        media_capabilities,
        DEFAULT_MEDIA_PROFILE,
    )
    text = manifest.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    durations = [float(line.split(":", 1)[1].rstrip(",")) for line in lines if line.startswith("#EXTINF:")]
    segment_uris = [line for line in lines if not line.startswith("#")]

    assert "#EXT-X-INDEPENDENT-SEGMENTS" in lines
    assert any(line.startswith("#EXT-X-MAP:URI=\"init.mp4\"") for line in lines)
    assert lines[-1] == "#EXT-X-ENDLIST"
    assert len(durations) == len(packet_mp4s)
    assert len(segment_uris) == len(packet_mp4s)
    assert all(duration == pytest.approx(3.0, abs=0.05) for duration in durations)
    assert segment_uris == [f"packet-{index:06d}.m4s" for index in range(len(packet_mp4s))]
    assert (manifest.parent / "init.mp4").is_file()
    assert all((manifest.parent / uri).is_file() for uri in segment_uris)


def test_parse_local_playlist_accepts_normalized_bundle_playlist(tmp_path):
    manifest = _write_playlist(tmp_path / "bundle")
    playlist = parse_local_playlist(manifest)

    assert playlist.path == manifest.resolve()
    assert playlist.initialization_path == (manifest.parent / "init.mp4").resolve()
    assert len(playlist.segments) == 1
    assert playlist.segments[0].index == 0
    assert playlist.segments[0].uri == "packet-000000.m4s"
    assert playlist.segments[0].duration == pytest.approx(3.0)


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.test/x.m4s",
        "file:///tmp/x.m4s",
        "/tmp/x.m4s",
        "../x.m4s",
        "nested/../../x.m4s",
    ],
)
def test_playlist_rejects_nonlocal_or_escaping_segment_uri(uri, tmp_path):
    manifest = _write_playlist(tmp_path / "bundle", segment_uri=uri)
    with pytest.raises(MediaVerificationError, match="local relative"):
        parse_local_playlist(manifest)


@pytest.mark.parametrize(
    "uri",
    ["https://example.test/init.mp4", "file:///tmp/init.mp4", "/tmp/init.mp4", "../init.mp4"],
)
def test_playlist_rejects_nonlocal_or_escaping_init_uri(uri, tmp_path):
    manifest = _write_playlist(tmp_path / "bundle", init_uri=uri)
    with pytest.raises(MediaVerificationError, match="local relative"):
        parse_local_playlist(manifest)


def test_playlist_rejects_discontinuity_and_out_of_range_duration(tmp_path):
    discontinuous = _write_playlist(
        tmp_path / "discontinuous",
        extra_tags=("#EXT-X-DISCONTINUITY",),
    )
    with pytest.raises(MediaVerificationError, match="discontinuity"):
        parse_local_playlist(discontinuous)

    too_long = _write_playlist(tmp_path / "too-long", duration=3.2)
    with pytest.raises(MediaVerificationError, match="duration"):
        parse_local_playlist(too_long)


def test_bundle_index_records_ordered_digests_and_root(compiled_recipe, tmp_path):
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / "init.mp4").write_bytes(b"init")
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-TARGETDURATION:3",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        '#EXT-X-MAP:URI="init.mp4"',
    ]
    for index in range(len(compiled_recipe.packets)):
        name = f"packet-{index:06d}.m4s"
        (directory / name).write_bytes(f"segment-{index}".encode())
        lines.extend(("#EXTINF:3.000000,", name))
    lines.append("#EXT-X-ENDLIST")
    manifest = directory / "stream.m3u8"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    playlist = parse_local_playlist(manifest)
    recipe_path = directory / "recipe.canonical.json"
    recipe_path.write_bytes(b'{"protocol":"ALD-MEDIA/1"}\n')

    path = write_bundle_index(
        compiled_recipe,
        playlist,
        DEFAULT_MEDIA_PROFILE,
        directory / "bundle.json",
        recipe_path=recipe_path,
        ffmpeg_version="ffmpeg-test-1",
        video_encoder="libx264",
        audio_encoder="aac",
    )
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)

    assert [packet["sequence"] for packet in data["packets"]] == list(range(len(compiled_recipe.packets)))
    assert [packet["digest"] for packet in data["packets"]] == [
        packet.digest.hex() for packet in compiled_recipe.packets
    ]
    assert data["root_hash"] == compiled_recipe.root_hash.hex()
    assert data["manifest"] == "stream.m3u8"
    assert data["initialization"] == "init.mp4"
    assert data["recipe"] == {
        "path": "recipe.canonical.json",
        "sha256": hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
    }
    assert data["ffmpeg"]["version"] == "ffmpeg-test-1"
    assert data["signature"] is None
    assert raw == json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
