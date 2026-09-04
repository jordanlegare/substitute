"""Strict local FFmpeg transport for product-MP4 instruction data tracks.

The MP4 video is display-only. Executable packet bytes live only in the timed
``bin_data/gpmd`` stream, with BFSK audio retained as an independent witness.
No subtitle, OCR, file-metadata, or sidecar fallback is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import ald_hardened_core as core
from ald_hls_integration import MediaBuildError, MediaCapabilities, run_media_tool
import ald_product_data as product_data


_FFMPEG_TIMEOUT_SECONDS = 120.0
_FFPROBE_TIMEOUT_SECONDS = 30.0
_TIMING_TOLERANCE_SECONDS = 0.05
_PRODUCT_WIDTH = 1920
_PRODUCT_HEIGHT = 1080
_PRODUCT_SAMPLE_RATE = 48_000
_PRODUCT_CHANNELS = 1
_DATA_CODEC = "bin_data"
_DATA_TAG = "gpmd"
_DATA_HANDLER = "ALD Instruction Data"


@dataclass(frozen=True)
class ProductDataPacketProbe:
    pts_seconds: float
    duration_seconds: float
    size: int


@dataclass(frozen=True)
class ProductMP4Probe:
    video_codec: str
    width: int
    height: int
    audio_codec: str
    sample_rate: int
    channels: int
    data_codec: str
    data_tag: str
    data_handler: str
    data_packets: tuple[ProductDataPacketProbe, ...]
    duration_seconds: float


def _require_capabilities(capabilities: MediaCapabilities) -> MediaCapabilities:
    if type(capabilities) is not MediaCapabilities:
        raise MediaBuildError("product MP4 capabilities must be an exact MediaCapabilities value")
    return capabilities


def _require_regular_file(path: Path, label: str) -> Path:
    value = Path(path)
    if not value.is_file() or value.is_symlink():
        raise MediaBuildError(f"{label} is not a regular non-symlink file: {value}")
    return value


def _probe_json(
    path: Path,
    capabilities: MediaCapabilities,
    *,
    packets_only: bool = False,
) -> dict[str, Any]:
    source = _require_regular_file(path, "product MP4")
    args = [str(capabilities.ffprobe), "-v", "error"]
    if packets_only:
        args.extend(["-select_streams", "d:0", "-show_packets"])
    else:
        args.extend(["-show_streams", "-show_format"])
    args.extend(["-of", "json", str(source)])
    result = run_media_tool(args, timeout_seconds=_FFPROBE_TIMEOUT_SECONDS)
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise MediaBuildError("ffprobe returned invalid product MP4 JSON") from error
    if type(value) is not dict:
        raise MediaBuildError("ffprobe product MP4 result must be an object")
    return value


def _finite_seconds(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise MediaBuildError(f"product MP4 {label} is missing or invalid") from error
    if not math.isfinite(result):
        raise MediaBuildError(f"product MP4 {label} must be finite")
    return result


def _exact_streams(probe: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    streams = probe.get("streams")
    if type(streams) is not list or len(streams) != 3:
        raise MediaBuildError("product MP4 must contain exactly three streams")
    by_type: dict[str, dict[str, Any]] = {}
    for stream in streams:
        if type(stream) is not dict:
            raise MediaBuildError("product MP4 stream entry is invalid")
        codec_type = stream.get("codec_type")
        if codec_type not in {"video", "audio", "data"} or codec_type in by_type:
            raise MediaBuildError("product MP4 must contain exactly one video, audio, and data stream")
        by_type[codec_type] = stream
    if set(by_type) != {"video", "audio", "data"}:
        raise MediaBuildError("product MP4 must contain exactly one video, audio, and data stream")
    return by_type["video"], by_type["audio"], by_type["data"]


def _packet_summary(packets: list[Any]) -> str:
    summary: list[dict[str, object]] = []
    for packet in packets[:8]:
        if type(packet) is not dict:
            summary.append({"entry_type": type(packet).__name__})
            continue
        summary.append(
            {
                "pts_time": packet.get("pts_time"),
                "duration_time": packet.get("duration_time"),
                "size": packet.get("size"),
            }
        )
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))


def probe_product_mp4(
    path: Path,
    capabilities: MediaCapabilities,
    *,
    packet_count: int,
    interval_seconds: float,
) -> ProductMP4Probe:
    """Fail closed unless a product MP4 matches the exact transport profile."""
    _require_capabilities(capabilities)
    if type(packet_count) is not int or packet_count <= 0:
        raise MediaBuildError("product MP4 packet_count must be a positive integer")
    if type(interval_seconds) is not float or not math.isfinite(interval_seconds) or interval_seconds <= 0.0:
        raise MediaBuildError("product MP4 interval_seconds must be a positive finite float")

    stream_probe = _probe_json(path, capabilities)
    video, audio, data = _exact_streams(stream_probe)
    try:
        width = int(video.get("width"))
        height = int(video.get("height"))
        sample_rate = int(audio.get("sample_rate"))
        channels = int(audio.get("channels"))
    except (TypeError, ValueError) as error:
        raise MediaBuildError("product MP4 stream metadata is incomplete") from error

    if video.get("codec_name") != "h264" or (width, height) != (_PRODUCT_WIDTH, _PRODUCT_HEIGHT):
        raise MediaBuildError("product MP4 video must be H.264 1920x1080")
    if audio.get("codec_name") != "aac" or sample_rate != _PRODUCT_SAMPLE_RATE or channels != _PRODUCT_CHANNELS:
        raise MediaBuildError("product MP4 audio must be mono 48 kHz AAC")
    if data.get("codec_name") != _DATA_CODEC or data.get("codec_tag_string") != _DATA_TAG:
        raise MediaBuildError("product MP4 data stream must be bin_data/gpmd")
    tags = data.get("tags")
    if type(tags) is not dict or tags.get("handler_name") != _DATA_HANDLER:
        raise MediaBuildError("product MP4 data stream handler is invalid")

    format_value = stream_probe.get("format")
    if type(format_value) is not dict:
        raise MediaBuildError("product MP4 ffprobe result is missing format data")
    media_duration = _finite_seconds(format_value.get("duration"), "duration")
    expected_media_duration = packet_count * interval_seconds
    if media_duration + _TIMING_TOLERANCE_SECONDS < expected_media_duration:
        raise MediaBuildError("product MP4 duration does not cover the final packet interval")

    packet_probe = _probe_json(path, capabilities, packets_only=True)
    packets = packet_probe.get("packets")
    if type(packets) is not list:
        raise MediaBuildError("product MP4 ffprobe result is missing data packets")
    if len(packets) != packet_count:
        raise MediaBuildError(
            "product MP4 data packet count mismatch: "
            f"expected={packet_count} actual={len(packets)} packets={_packet_summary(packets)}"
        )
    data_packets: list[ProductDataPacketProbe] = []
    for sequence, packet in enumerate(packets):
        if type(packet) is not dict:
            raise MediaBuildError("product MP4 data packet entry is invalid")
        try:
            size = int(packet.get("size"))
        except (TypeError, ValueError) as error:
            raise MediaBuildError("product MP4 data packet size is invalid") from error
        if size != product_data.DATA_SLOT_BYTES:
            raise MediaBuildError("product MP4 data packet must be exactly 1024 bytes")
        pts = _finite_seconds(packet.get("pts_time"), "data packet PTS")
        duration = _finite_seconds(packet.get("duration_time"), "data packet duration")
        expected_pts = sequence * interval_seconds
        if abs(pts - expected_pts) > _TIMING_TOLERANCE_SECONDS:
            raise MediaBuildError("product MP4 data packet PTS is outside tolerance")
        if abs(duration - interval_seconds) > _TIMING_TOLERANCE_SECONDS:
            raise MediaBuildError("product MP4 data packet duration is outside tolerance")
        data_packets.append(ProductDataPacketProbe(pts_seconds=pts, duration_seconds=duration, size=size))

    return ProductMP4Probe(
        video_codec="h264",
        width=width,
        height=height,
        audio_codec="aac",
        sample_rate=sample_rate,
        channels=channels,
        data_codec=_DATA_CODEC,
        data_tag=_DATA_TAG,
        data_handler=_DATA_HANDLER,
        data_packets=tuple(data_packets),
        duration_seconds=media_duration,
    )


def extract_product_data(
    path: Path,
    destination: Path,
    capabilities: MediaCapabilities,
) -> Path:
    """Demux the authoritative MP4 data stream to raw fixed-width slot bytes."""
    _require_capabilities(capabilities)
    source = _require_regular_file(path, "product MP4")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise MediaBuildError(f"product data extraction destination already exists: {target}")
    try:
        run_media_tool(
            [
                str(capabilities.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-map",
                "0:d:0",
                "-c",
                "copy",
                "-copy_unknown",
                "-f",
                "data",
                "-y",
                str(target),
            ],
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
        )
        _require_regular_file(target, "extracted product data")
    except BaseException:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _stage_probe_data(
    capabilities: MediaCapabilities,
    slot_path: Path,
    data_ts: Path,
) -> None:
    run_media_tool(
        [
            str(capabilities.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "data",
            "-raw_packet_size",
            str(product_data.DATA_SLOT_BYTES),
            "-i",
            str(slot_path),
            "-map",
            "0:0",
            "-c",
            "copy",
            "-bsf:0",
            "setts=pts=N*3000:dts=N*3000:duration=3000:time_base=1/1000",
            "-mpegts_copyts",
            "1",
            "-f",
            "mpegts",
            "-y",
            str(data_ts),
        ],
        timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
    )


def _mux_probe_mp4(
    capabilities: MediaCapabilities,
    data_ts: Path,
    destination: Path,
) -> None:
    args = [
        str(capabilities.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=1920x1080:r=30",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=mono",
        "-i",
        str(data_ts),
        "-t",
        "6.000000",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:d:0",
        "-c:v",
        capabilities.video_encoder,
    ]
    if capabilities.video_encoder == "libx264":
        args.extend(["-preset", "ultrafast"])
    args.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            capabilities.audio_encoder,
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:d",
            "copy",
            "-copy_unknown",
            "-tag:d:0",
            _DATA_TAG,
            "-metadata:s:d:0",
            f"handler_name={_DATA_HANDLER}",
            "-f",
            "mp4",
            "-y",
            str(destination),
        ]
    )
    run_media_tool(args, timeout_seconds=_FFMPEG_TIMEOUT_SECONDS)


def probe_product_mp4_capabilities(capabilities: MediaCapabilities) -> None:
    """Prove byte-exact/timed ``bin_data/gpmd`` MP4 support or reject it.

    The third all-zero slot is staging-only. The six-second final MP4 must
    contain exactly the first two slots at 0 and 3 seconds, each with a
    three-second duration. This proof is deliberately executable rather than
    inferred from FFmpeg version strings or static capability listings.
    """
    _require_capabilities(capabilities)
    slot_a = bytes((index % 251) + 1 for index in range(product_data.DATA_SLOT_BYTES))
    slot_b = bytes(((index * 17) % 251) + 1 for index in range(product_data.DATA_SLOT_BYTES))
    guard = bytes(product_data.DATA_SLOT_BYTES)

    try:
        with tempfile.TemporaryDirectory(prefix="ald-product-mp4-probe-") as temporary:
            root = Path(temporary)
            slot_path = root / "data-slots.bin"
            data_ts = root / "data.ts"
            product_path = root / "proof.mp4"
            extracted_path = root / "extracted.bin"
            slot_path.write_bytes(slot_a + slot_b + guard)

            _stage_probe_data(capabilities, slot_path, data_ts)
            staged_probe = _probe_json(data_ts, capabilities, packets_only=True)
            staged_packets = staged_probe.get("packets")
            if type(staged_packets) is not list:
                raise MediaBuildError("staged MPEG-TS ffprobe result is missing data packets")
            if len(staged_packets) != 3:
                raise MediaBuildError(
                    "staged MPEG-TS data packet count mismatch: "
                    f"expected=3 actual={len(staged_packets)} packets={_packet_summary(staged_packets)}"
                )

            _mux_probe_mp4(capabilities, data_ts, product_path)
            try:
                probe_product_mp4(
                    product_path,
                    capabilities,
                    packet_count=2,
                    interval_seconds=3.0,
                )
            except MediaBuildError as error:
                final_probe = _probe_json(product_path, capabilities, packets_only=True)
                final_packets = final_probe.get("packets")
                final_summary = (
                    _packet_summary(final_packets)
                    if type(final_packets) is list
                    else f"invalid:{type(final_packets).__name__}"
                )
                raise MediaBuildError(
                    f"{error}; staged_ts_packets={_packet_summary(staged_packets)}; "
                    f"final_mp4_packets={final_summary}"
                ) from error

            extract_product_data(product_path, extracted_path, capabilities)
            extracted = extracted_path.read_bytes()
            if extracted != slot_a + slot_b:
                raise MediaBuildError("product MP4 data track is not byte-exact or retained the guard slot")
    except core.DependencyError:
        raise
    except (MediaBuildError, OSError, ValueError, TypeError) as error:
        raise core.DependencyError(
            f"ffmpeg lacks the required timed bin_data/gpmd product-MP4 profile: {error}"
        ) from error
