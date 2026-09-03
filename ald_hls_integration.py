"""Local-only FFmpeg boundary for ALD HLS/fMP4 integration.

All external media-tool execution is centralized here. Calls use explicit
argument vectors, never a shell, never inherited stdin, and bounded timeouts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import subprocess

import ald_hardened_core as core


_MEDIA_TOOL_TIMEOUT_SECONDS = 15.0
_STDERR_TAIL_LINES = 20
_REQUIRED_MOV_DEMUXER_NAMES = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})


class MediaBuildError(core.ALDError):
    """Raised when local media tooling cannot construct a valid artifact."""

    exit_code = core.ExitCode.MEDIA


@dataclass(frozen=True)
class MediaCapabilities:
    ffmpeg: Path
    ffprobe: Path
    video_encoder: str
    audio_encoder: str = "aac"

    def __post_init__(self) -> None:
        if not isinstance(self.ffmpeg, Path) or not isinstance(self.ffprobe, Path):
            raise core.DependencyError("media executable paths must be Path values")
        if type(self.video_encoder) is not str or not self.video_encoder:
            raise core.DependencyError("video encoder name is invalid")
        if type(self.audio_encoder) is not str or not self.audio_encoder:
            raise core.DependencyError("audio encoder name is invalid")


def _stderr_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _stderr_tail(value: object) -> str:
    lines = _stderr_text(value).splitlines()
    return "\n".join(lines[-_STDERR_TAIL_LINES:])


def _validate_media_args(args: Sequence[str]) -> list[str]:
    if isinstance(args, (str, bytes, bytearray)):
        raise MediaBuildError("media tool arguments must be an argument vector")
    try:
        values = list(args)
    except TypeError as error:
        raise MediaBuildError("media tool arguments must be an argument vector") from error
    if not values:
        raise MediaBuildError("media tool argument vector is empty")
    for value in values:
        if type(value) is not str or not value or "\x00" in value:
            raise MediaBuildError("media tool arguments must be non-empty plain strings")
    return values


def run_media_tool(
    args: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Run one local FFmpeg-family command under the fixed subprocess policy."""
    values = _validate_media_args(args)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) <= 0.0
    ):
        raise MediaBuildError("media tool timeout must be positive and finite")

    tool = Path(values[0]).name or values[0]
    try:
        result = subprocess.run(
            values,
            shell=False,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as error:
        tail = _stderr_tail(error.stderr)
        detail = f"\n{tail}" if tail else ""
        raise MediaBuildError(
            f"{tool} timed out after {float(timeout_seconds):g} seconds{detail}"
        ) from error
    except OSError as error:
        raise MediaBuildError(f"unable to execute {tool}: {error}") from error

    if result.returncode != 0:
        tail = _stderr_tail(result.stderr)
        detail = f"\n{tail}" if tail else ""
        raise MediaBuildError(
            f"{tool} exited with status {result.returncode}{detail}"
        )
    return result


def _listing_entries(text: str) -> tuple[str, ...]:
    """Extract the capability-name column from FFmpeg listing output."""
    entries: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        flags = parts[0]
        if not all(character.isalpha() or character == "." for character in flags):
            continue
        if not any(character in flags for character in "DEVAS"):
            continue
        entries.append(parts[1])
    return tuple(entries)


def _require_muxer(entries: tuple[str, ...], name: str) -> None:
    if name not in entries:
        raise core.DependencyError(f"ffmpeg lacks required {name} muxer")


def _require_demuxers(entries: tuple[str, ...]) -> None:
    if "hls" not in entries:
        raise core.DependencyError("ffmpeg lacks required hls demuxer")
    if not any(_REQUIRED_MOV_DEMUXER_NAMES.issubset(set(entry.split(","))) for entry in entries):
        raise core.DependencyError("ffmpeg lacks required mov/mp4 demuxer family")


def probe_media_capabilities() -> MediaCapabilities:
    """Require the local FFmpeg feature set needed for deterministic bundles."""
    ffmpeg_name = shutil.which("ffmpeg")
    if ffmpeg_name is None:
        raise core.DependencyError("ffmpeg executable is required")
    ffprobe_name = shutil.which("ffprobe")
    if ffprobe_name is None:
        raise core.DependencyError("ffprobe executable is required")

    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    encoders = _listing_entries(
        run_media_tool(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            timeout_seconds=_MEDIA_TOOL_TIMEOUT_SECONDS,
        ).stdout
    )
    muxers = _listing_entries(
        run_media_tool(
            [str(ffmpeg), "-hide_banner", "-muxers"],
            timeout_seconds=_MEDIA_TOOL_TIMEOUT_SECONDS,
        ).stdout
    )
    demuxers = _listing_entries(
        run_media_tool(
            [str(ffmpeg), "-hide_banner", "-demuxers"],
            timeout_seconds=_MEDIA_TOOL_TIMEOUT_SECONDS,
        ).stdout
    )

    video_encoder = next((name for name in ("libx264", "h264") if name in encoders), None)
    if video_encoder is None:
        raise core.DependencyError("ffmpeg lacks required libx264 or h264 encoder")
    if "aac" not in encoders:
        raise core.DependencyError("ffmpeg lacks required aac encoder")
    _require_muxer(muxers, "mp4")
    _require_muxer(muxers, "hls")
    _require_demuxers(demuxers)

    return MediaCapabilities(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        video_encoder=video_encoder,
        audio_encoder="aac",
    )
