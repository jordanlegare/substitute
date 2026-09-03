from pathlib import Path
import shutil
import subprocess

import pytest

from ald_media_controller import (
    DEFAULT_MEDIA_PROFILE,
    DependencyError,
    MediaBuildError,
    compile_recipe,
    load_recipe,
    mux_packet_mp4,
    package_hls,
    probe_media_capabilities,
    probe_media_json,
    run_media_tool,
    stage_packet_media,
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
    return compile_recipe(load_recipe(Path("recipes/generic_al2o3.json")))


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
