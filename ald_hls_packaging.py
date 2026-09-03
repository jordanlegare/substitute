"""Deterministic local packaging of verified ALD packet media into fMP4 HLS."""

from __future__ import annotations

from collections.abc import Sequence
import json
import math
from pathlib import Path
import shutil

import ald_hardened_core as core
import ald_media_codecs as media
import ald_media_staging as staging
from ald_hls_integration import MediaBuildError, MediaCapabilities, run_media_tool


_FFMPEG_TIMEOUT_SECONDS = 120.0
_FFPROBE_TIMEOUT_SECONDS = 30.0
_VIDEO_FRAME_RATE = 30


def _require_regular_file(path: Path, label: str) -> Path:
    value = Path(path)
    if not value.is_file():
        raise MediaBuildError(f"{label} is not a regular file: {value}")
    return value


def probe_media_json(path: Path, capabilities: MediaCapabilities) -> dict:
    """Return bounded ffprobe JSON for one local media file."""
    if type(capabilities) is not MediaCapabilities:
        raise MediaBuildError("media capabilities must be an exact MediaCapabilities value")
    source = _require_regular_file(Path(path), "media input")
    result = run_media_tool(
        [
            str(capabilities.ffprobe),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        ],
        timeout_seconds=_FFPROBE_TIMEOUT_SECONDS,
    )
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise MediaBuildError("ffprobe returned invalid JSON") from error
    if type(value) is not dict or type(value.get("streams")) is not list or type(value.get("format")) is not dict:
        raise MediaBuildError("ffprobe JSON is missing streams or format data")
    return value


def _validate_packet_mp4_probe(probe: dict, profile: media.MediaProfile) -> None:
    streams = probe["streams"]
    by_type = {}
    for stream in streams:
        if type(stream) is not dict:
            raise MediaBuildError("ffprobe stream entry is invalid")
        codec_type = stream.get("codec_type")
        if codec_type in ("video", "audio"):
            if codec_type in by_type:
                raise MediaBuildError(f"packet MP4 contains multiple {codec_type} streams")
            by_type[codec_type] = stream
    if set(by_type) != {"video", "audio"}:
        raise MediaBuildError("packet MP4 must contain exactly one video and one audio stream")

    video = by_type["video"]
    audio = by_type["audio"]
    try:
        if video.get("codec_name") != "h264":
            raise MediaBuildError("packet MP4 video codec is not H.264")
        if int(video.get("width")) != profile.width or int(video.get("height")) != profile.height:
            raise MediaBuildError("packet MP4 video dimensions do not match media profile")
        if audio.get("codec_name") != "aac":
            raise MediaBuildError("packet MP4 audio codec is not AAC")
        if int(audio.get("sample_rate")) != profile.sample_rate or int(audio.get("channels")) != 1:
            raise MediaBuildError("packet MP4 audio format does not match media profile")
        duration = float(probe["format"].get("duration"))
    except (TypeError, ValueError) as error:
        raise MediaBuildError("packet MP4 probe data is incomplete") from error
    if not math.isfinite(duration) or abs(duration - profile.interval_seconds) > 0.05:
        raise MediaBuildError("packet MP4 duration does not match media interval")


def mux_packet_mp4(
    artifact: staging.PacketMediaArtifact,
    destination: Path,
    capabilities: MediaCapabilities,
    profile: media.MediaProfile,
) -> Path:
    """Mux one verified PNG/WAV pair into a fixed-duration H.264/AAC MP4."""
    if type(artifact) is not staging.PacketMediaArtifact:
        raise MediaBuildError("packet MP4 input must be an exact PacketMediaArtifact")
    if type(capabilities) is not MediaCapabilities:
        raise MediaBuildError("media capabilities must be an exact MediaCapabilities value")
    if type(profile) is not media.MediaProfile:
        raise MediaBuildError("media profile must be an exact MediaProfile")
    frame = _require_regular_file(artifact.frame_path, "instruction frame")
    audio = _require_regular_file(artifact.audio_path, "checksum audio")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise MediaBuildError(f"packet MP4 destination already exists: {target}")

    args = [
        str(capabilities.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-n",
        "-loop",
        "1",
        "-framerate",
        str(_VIDEO_FRAME_RATE),
        "-i",
        str(frame),
        "-i",
        str(audio),
        "-t",
        f"{profile.interval_seconds:.6f}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        capabilities.video_encoder,
    ]
    if capabilities.video_encoder == "libx264":
        args.extend(["-preset", "veryfast"])
    args.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(_VIDEO_FRAME_RATE),
            "-g",
            str(_VIDEO_FRAME_RATE * 3),
            "-keyint_min",
            str(_VIDEO_FRAME_RATE * 3),
            "-sc_threshold",
            "0",
            "-fps_mode",
            "cfr",
            "-c:a",
            capabilities.audio_encoder,
            "-b:a",
            "128k",
            "-ar",
            str(profile.sample_rate),
            "-ac",
            "1",
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            str(target),
        ]
    )
    try:
        run_media_tool(args, timeout_seconds=_FFMPEG_TIMEOUT_SECONDS)
        _validate_packet_mp4_probe(probe_media_json(target, capabilities), profile)
    except BaseException:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _read_ffmpeg_hls_durations(path: Path) -> tuple[float, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise MediaBuildError(f"unable to read generated HLS playlist: {error}") from error
    durations: list[float] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXTINF:"):
            try:
                value = float(line.split(":", 1)[1].rstrip(","))
            except ValueError as error:
                raise MediaBuildError("generated HLS playlist contains an invalid EXTINF") from error
            if not math.isfinite(value) or value <= 0.0:
                raise MediaBuildError("generated HLS playlist contains an invalid duration")
            durations.append(value)
    return tuple(durations)


def _write_normalized_playlist(path: Path, durations: tuple[float, ...]) -> None:
    if not durations:
        raise MediaBuildError("cannot write an empty HLS playlist")
    target_duration = max(1, math.ceil(max(durations)))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        '#EXT-X-MAP:URI="init.mp4"',
    ]
    for index, duration in enumerate(durations):
        lines.append(f"#EXTINF:{duration:.6f},")
        lines.append(f"packet-{index:06d}.m4s")
    lines.append("#EXT-X-ENDLIST")
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    except OSError as error:
        raise MediaBuildError(f"unable to write normalized HLS playlist: {error}") from error


def package_hls(
    packet_mp4s: Sequence[Path],
    directory: Path,
    capabilities: MediaCapabilities,
    profile: media.MediaProfile,
) -> Path:
    """Concatenate packet MP4s and segment them as one fMP4 HLS VOD playlist."""
    if isinstance(packet_mp4s, (str, bytes, bytearray)):
        raise MediaBuildError("packet MP4 inputs must be a path sequence")
    sources = tuple(Path(item) for item in packet_mp4s)
    if not sources:
        raise MediaBuildError("at least one packet MP4 is required")
    for source in sources:
        _require_regular_file(source, "packet MP4")
    if type(capabilities) is not MediaCapabilities:
        raise MediaBuildError("media capabilities must be an exact MediaCapabilities value")
    if type(profile) is not media.MediaProfile:
        raise MediaBuildError("media profile must be an exact MediaProfile")

    target = Path(directory)
    if target.exists():
        raise MediaBuildError(f"HLS staging directory already exists: {target}")
    try:
        target.mkdir(parents=True, mode=0o700)
    except OSError as error:
        raise MediaBuildError(f"unable to create HLS staging directory: {error}") from error

    input_directory = target / "inputs"
    concat_list = target / "concat.txt"
    concatenated = target / "concatenated.mp4"
    ffmpeg_playlist = target / "_ffmpeg.m3u8"
    normalized_playlist = target / "stream.m3u8"
    init_segment = target / "init.mp4"
    try:
        input_directory.mkdir(mode=0o700)
        concat_lines: list[str] = []
        for index, source in enumerate(sources):
            local_name = f"packet-{index:06d}.mp4"
            shutil.copy2(source, input_directory / local_name)
            concat_lines.append(f"file 'inputs/{local_name}'")
        concat_list.write_text("\n".join(concat_lines) + "\n", encoding="utf-8", newline="\n")

        run_media_tool(
            [
                str(capabilities.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(concat_list),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-c",
                "copy",
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                str(concatenated),
            ],
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
        )

        run_media_tool(
            [
                str(capabilities.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-i",
                str(concatenated),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-c",
                "copy",
                "-f",
                "hls",
                "-hls_time",
                f"{profile.interval_seconds:.6f}",
                "-hls_list_size",
                "0",
                "-hls_playlist_type",
                "vod",
                "-hls_segment_type",
                "fmp4",
                "-hls_fmp4_init_filename",
                str(init_segment),
                "-hls_flags",
                "independent_segments",
                "-hls_segment_filename",
                str(target / "packet-%06d.m4s"),
                str(ffmpeg_playlist),
            ],
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
        )

        durations = _read_ffmpeg_hls_durations(ffmpeg_playlist)
        if len(durations) != len(sources):
            raise MediaBuildError(
                f"HLS segment count mismatch: expected {len(sources)}, found {len(durations)}"
            )
        for duration in durations:
            if abs(duration - profile.interval_seconds) > 0.05:
                raise MediaBuildError("HLS segment duration does not match media interval")
        if not init_segment.is_file():
            raise MediaBuildError("HLS initialization segment is missing")
        for index in range(len(sources)):
            if not (target / f"packet-{index:06d}.m4s").is_file():
                raise MediaBuildError(f"HLS media segment {index} is missing")

        _write_normalized_playlist(normalized_playlist, durations)

        shutil.rmtree(input_directory)
        concat_list.unlink()
        concatenated.unlink()
        ffmpeg_playlist.unlink()
        return normalized_playlist
    except BaseException:
        try:
            shutil.rmtree(target)
        except OSError:
            pass
        raise
