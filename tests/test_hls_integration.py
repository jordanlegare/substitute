import shutil
import subprocess

import pytest

from ald_media_controller import (
    DependencyError,
    MediaBuildError,
    probe_media_capabilities,
    run_media_tool,
)


def _success(args, stdout=""):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


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
