"""Fail-closed verification of completed local ALD HLS/fMP4 bundles.

The verifier never passes the HLS manifest to FFmpeg. It first parses the
restricted local playlist, resolves every path under one bundle directory,
then constructs one temporary playable fMP4 from the verified initialization
segment plus one media fragment. Executable ``HashedPacket`` values are not
constructed until the complete frame/audio/index/hash-chain/root verification
has succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any

import ald_hardened_core as core
import ald_media_codecs as media
from ald_hls_bundle import LocalPlaylist, MediaVerificationError, parse_local_playlist
from ald_hls_integration import (
    MediaBuildError,
    MediaCapabilities,
    probe_media_capabilities,
    run_media_tool,
)
from ald_hls_packaging import probe_media_json
from ald_hls_signature import SignatureError, SignatureStatus, verify_bundle_signature


_VERIFY_TIMEOUT_SECONDS = 60.0
_TIMELINE_TOLERANCE_SECONDS = 0.05
_BUNDLE_KEYS = frozenset(
    {
        "protocol",
        "media_profile",
        "ffmpeg",
        "manifest",
        "initialization",
        "packets",
        "root_hash",
        "signature",
        "creation_tool_version",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "width",
        "height",
        "interval_seconds",
        "qr_error_correction",
        "qr_box_size",
        "qr_border_modules",
        "sample_rate",
        "symbol_rate",
        "mark_hz",
        "space_hz",
        "copies",
        "required_matching_copies",
    }
)
_PACKET_KEYS = frozenset({"sequence", "segment", "digest", "duration_seconds"})
_FFMPEG_KEYS = frozenset({"version", "video_encoder", "audio_encoder"})


class IntegrityError(core.ALDError):
    """Raised when independently encoded bundle records do not all agree."""

    exit_code = core.ExitCode.INTEGRITY


@dataclass(frozen=True)
class VerifiedMediaRecipe:
    packets: tuple[core.HashedPacket, ...]
    root_hash: bytes
    profile: media.MediaProfile
    signature_status: SignatureStatus


@dataclass(frozen=True)
class _IndexPacket:
    sequence: int
    segment: str
    digest: bytes
    duration_seconds: float


@dataclass(frozen=True)
class _LoadedIndex:
    packets: tuple[_IndexPacket, ...]
    root_hash: bytes
    profile: media.MediaProfile
    signature_status: SignatureStatus


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise IntegrityError("bundle index object key must be a string")
        if key in result:
            raise IntegrityError(f"bundle index contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise IntegrityError(f"bundle index contains non-finite number: {value}")


def _require_exact_dict(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise IntegrityError(f"{label} must be an object")
    if set(value) != keys:
        raise IntegrityError(f"{label} has unexpected or missing fields")
    return value


def _require_plain_string(value: Any, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise IntegrityError(f"{label} must be a non-empty plain string")
    return value


def _decode_digest(value: Any, label: str) -> bytes:
    if type(value) is not str or len(value) != 64:
        raise IntegrityError(f"{label} must be a 64-character hexadecimal digest")
    try:
        digest = bytes.fromhex(value)
    except ValueError as error:
        raise IntegrityError(f"{label} must be hexadecimal") from error
    if len(digest) != 32:
        raise IntegrityError(f"{label} must decode to 32 bytes")
    return digest


def _load_bundle_index(
    playlist: LocalPlaylist,
    *,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> _LoadedIndex:
    index_path = playlist.path.parent / "bundle.json"
    if not index_path.is_file():
        raise IntegrityError("bundle.json is missing")
    try:
        raw_text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise IntegrityError(f"unable to read bundle.json: {error}") from error
    try:
        value = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except IntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise IntegrityError("bundle.json is not valid JSON") from error

    root = _require_exact_dict(value, _BUNDLE_KEYS, "bundle index")
    try:
        canonical = json.dumps(
            root,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise IntegrityError("bundle index cannot be canonicalized") from error
    if canonical != raw_text:
        raise IntegrityError("bundle.json is not canonical sorted compact JSON")
    if root["protocol"] != "ALD-MEDIA/1":
        raise IntegrityError("bundle protocol must be ALD-MEDIA/1")

    manifest = _require_plain_string(root["manifest"], "bundle manifest")
    if manifest != playlist.path.name:
        raise IntegrityError("bundle manifest does not match verified playlist path")
    try:
        expected_init = playlist.initialization_path.relative_to(playlist.path.parent).as_posix()
    except ValueError as error:
        raise IntegrityError("playlist initialization path escapes bundle directory") from error
    initialization = _require_plain_string(root["initialization"], "bundle initialization")
    if initialization != expected_init:
        raise IntegrityError("bundle initialization does not match verified playlist")

    profile_raw = _require_exact_dict(root["media_profile"], _PROFILE_KEYS, "media profile")
    try:
        profile = media.MediaProfile(**profile_raw)
    except (core.ALDError, TypeError, ValueError) as error:
        raise IntegrityError(f"bundle media profile is invalid: {error}") from error
    if profile != media.DEFAULT_MEDIA_PROFILE:
        raise IntegrityError("bundle media profile is not the fixed ALD media profile")

    ffmpeg_raw = _require_exact_dict(root["ffmpeg"], _FFMPEG_KEYS, "FFmpeg metadata")
    for key in _FFMPEG_KEYS:
        _require_plain_string(ffmpeg_raw[key], f"FFmpeg metadata {key}")
    _require_plain_string(root["creation_tool_version"], "creation tool version")

    signature = root["signature"]
    if signature is None:
        if require_signature:
            raise IntegrityError("signature required but bundle is unsigned")
        signature_status = SignatureStatus.UNSIGNED
    else:
        if trusted_public_key is None:
            raise IntegrityError("signed bundle requires a trusted public key")
        try:
            signature_status = verify_bundle_signature(index_path, trusted_public_key)
        except core.DependencyError:
            raise
        except SignatureError as error:
            raise IntegrityError(str(error)) from error
        if signature_status is not SignatureStatus.VERIFIED:
            raise IntegrityError("signed bundle signature did not verify")

    packet_values = root["packets"]
    if type(packet_values) is not list or not packet_values:
        raise IntegrityError("bundle packet index must be a non-empty array")
    if len(packet_values) != len(playlist.segments):
        raise IntegrityError("bundle packet count does not match playlist segment count")

    packets: list[_IndexPacket] = []
    for expected_sequence, (raw_packet, playlist_segment) in enumerate(
        zip(packet_values, playlist.segments, strict=True)
    ):
        packet = _require_exact_dict(raw_packet, _PACKET_KEYS, "bundle packet")
        sequence = packet["sequence"]
        if type(sequence) is not int or sequence != expected_sequence:
            raise IntegrityError("bundle packet sequence is not contiguous and zero-based")
        segment = _require_plain_string(packet["segment"], "bundle packet segment")
        expected_segment = f"packet-{expected_sequence:06d}.m4s"
        if segment != playlist_segment.uri:
            raise IntegrityError("bundle packet segment does not match playlist order")
        if segment != expected_segment:
            raise IntegrityError("bundle packet filenames are not contiguous and zero-based")
        digest = _decode_digest(packet["digest"], "bundle packet digest")
        duration = packet["duration_seconds"]
        if type(duration) not in (int, float) or isinstance(duration, bool):
            raise IntegrityError("bundle packet duration must be numeric")
        duration = float(duration)
        if not math.isfinite(duration) or abs(duration - playlist_segment.duration) > 1.0e-6:
            raise IntegrityError("bundle packet duration does not match playlist")
        packets.append(
            _IndexPacket(
                sequence=sequence,
                segment=segment,
                digest=digest,
                duration_seconds=duration,
            )
        )

    return _LoadedIndex(
        packets=tuple(packets),
        root_hash=_decode_digest(root["root_hash"], "bundle root hash"),
        profile=profile,
        signature_status=signature_status,
    )


def _validate_segment_file_set(playlist: LocalPlaylist) -> None:
    root = playlist.path.parent
    expected = {segment.uri for segment in playlist.segments}
    try:
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("packet-*.m4s")
        }
    except (OSError, ValueError) as error:
        raise IntegrityError(f"unable to enumerate bundle media segments: {error}") from error
    if actual != expected:
        extras = sorted(actual - expected)
        missing = sorted(expected - actual)
        details = []
        if extras:
            details.append(f"extra={extras}")
        if missing:
            details.append(f"missing={missing}")
        suffix = "; ".join(details) if details else "mismatch"
        raise IntegrityError(f"bundle segment set does not match index: {suffix}")


def _copy_playable_fragment(initialization: Path, segment: Path, destination: Path) -> None:
    try:
        with destination.open("xb") as target:
            for source_path in (initialization, segment):
                with source_path.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except OSError as error:
        raise IntegrityError(f"unable to construct local playable media fragment: {error}") from error


def _validate_encoded_streams(
    probe: dict[str, Any],
    profile: media.MediaProfile,
    sequence: int,
) -> tuple[float, float]:
    streams = probe.get("streams")
    if type(streams) is not list or len(streams) != 2:
        raise IntegrityError(f"segment {sequence} must contain exactly one video and one audio stream")
    by_type: dict[str, dict[str, Any]] = {}
    for stream in streams:
        if type(stream) is not dict:
            raise IntegrityError(f"segment {sequence} contains invalid stream metadata")
        stream_type = stream.get("codec_type")
        if stream_type not in ("video", "audio") or stream_type in by_type:
            raise IntegrityError(f"segment {sequence} contains unexpected or duplicate streams")
        by_type[stream_type] = stream
    if set(by_type) != {"video", "audio"}:
        raise IntegrityError(f"segment {sequence} must contain video and audio")

    video = by_type["video"]
    audio = by_type["audio"]
    format_data = probe.get("format")
    if type(format_data) is not dict:
        raise IntegrityError(f"segment {sequence} format metadata is missing")
    try:
        if video.get("codec_name") != "h264":
            raise IntegrityError(f"segment {sequence} video is not H.264")
        if int(video.get("width")) != profile.width or int(video.get("height")) != profile.height:
            raise IntegrityError(f"segment {sequence} video dimensions do not match media profile")
        if audio.get("codec_name") != "aac":
            raise IntegrityError(f"segment {sequence} audio is not AAC")
        if int(audio.get("sample_rate")) != profile.sample_rate or int(audio.get("channels")) != 1:
            raise IntegrityError(f"segment {sequence} audio format does not match media profile")
        video_start = float(video.get("start_time"))
        audio_start = float(audio.get("start_time"))
        format_duration = float(format_data.get("duration"))
    except (TypeError, ValueError) as error:
        raise IntegrityError(f"segment {sequence} stream metadata is incomplete") from error
    if (
        not math.isfinite(video_start)
        or not math.isfinite(audio_start)
        or not math.isfinite(format_duration)
    ):
        raise IntegrityError(f"segment {sequence} stream timestamps are missing or non-finite")

    minimum_start = min(video_start, audio_start)
    duration_candidates = (format_duration, format_duration - minimum_start)
    if not any(
        candidate > 0.0
        and math.isfinite(candidate)
        and abs(candidate - profile.interval_seconds) <= _TIMELINE_TOLERANCE_SECONDS
        for candidate in duration_candidates
    ):
        raise IntegrityError(
            f"segment {sequence} timeline duration does not match expected media interval"
        )
    return video_start, audio_start


def _extract_encoded_records(
    playlist: LocalPlaylist,
    loaded: _LoadedIndex,
    capabilities: MediaCapabilities,
) -> tuple[tuple[bytes, bytes, int], ...]:
    """Return inert canonical-bytes/digest/sequence records after media decode."""
    decoded: list[tuple[bytes, bytes, int]] = []
    timeline_origin: tuple[float, float] | None = None
    try:
        temporary_root = tempfile.TemporaryDirectory(prefix="ald-media-verify-")
    except OSError as error:
        raise IntegrityError(f"unable to create verification scratch directory: {error}") from error

    with temporary_root as temp_name:
        temp = Path(temp_name)
        for sequence, (segment, index_packet) in enumerate(
            zip(playlist.segments, loaded.packets, strict=True)
        ):
            playable = temp / f"segment-{sequence:06d}.mp4"
            frame_path = temp / f"segment-{sequence:06d}.png"
            audio_path = temp / f"segment-{sequence:06d}.wav"
            _copy_playable_fragment(playlist.initialization_path, segment.path, playable)
            try:
                probe = probe_media_json(playable, capabilities)
                video_start, audio_start = _validate_encoded_streams(
                    probe, loaded.profile, sequence
                )
                if timeline_origin is None:
                    timeline_origin = (video_start, audio_start)
                else:
                    expected_delta = sequence * loaded.profile.interval_seconds
                    if (
                        abs((video_start - timeline_origin[0]) - expected_delta)
                        > _TIMELINE_TOLERANCE_SECONDS
                        or abs((audio_start - timeline_origin[1]) - expected_delta)
                        > _TIMELINE_TOLERANCE_SECONDS
                    ):
                        raise IntegrityError(
                            f"segment {sequence} timeline timestamp does not match expected media interval"
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
                        str(playable),
                        "-map",
                        "0:v:0",
                        "-frames:v",
                        "1",
                        str(frame_path),
                    ],
                    timeout_seconds=_VERIFY_TIMEOUT_SECONDS,
                )
                total_samples = int(
                    round(loaded.profile.sample_rate * loaded.profile.interval_seconds)
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
                        str(playable),
                        "-map",
                        "0:a:0",
                        "-af",
                        f"apad=whole_len={total_samples},atrim=end_sample={total_samples},asetpts=N/SR/TB",
                        "-ar",
                        str(loaded.profile.sample_rate),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        "-f",
                        "wav",
                        str(audio_path),
                    ],
                    timeout_seconds=_VERIFY_TIMEOUT_SECONDS,
                )
                frame = media.decode_instruction_frame(frame_path, loaded.profile)
                audio_samples = media.read_checksum_wav(audio_path, loaded.profile)
                audio = media.decode_checksum_audio(audio_samples, loaded.profile)
            except core.DependencyError:
                raise
            except (MediaBuildError, media.FrameDecodeError, media.AudioDecodeError) as error:
                raise IntegrityError(
                    f"encoded segment {sequence} could not be verified: {error}"
                ) from error

            if (
                frame.sequence != sequence
                or audio.sequence != sequence
                or index_packet.sequence != sequence
            ):
                raise IntegrityError(f"segment {sequence} frame/audio/index sequence mismatch")
            if not hmac.compare_digest(frame.digest, audio.digest):
                raise IntegrityError(f"segment {sequence} frame/audio digest mismatch")
            if not hmac.compare_digest(frame.digest, index_packet.digest):
                raise IntegrityError(f"segment {sequence} media/index digest mismatch")
            decoded.append((frame.canonical_bytes, frame.digest, sequence))
    return tuple(decoded)


def verify_media_bundle(
    manifest: Path,
    require_signature: bool = False,
    trusted_public_key: Path | None = None,
) -> VerifiedMediaRecipe:
    """Recover and verify a complete local media bundle before exposing packets."""
    if type(require_signature) is not bool:
        raise IntegrityError("require_signature must be a boolean")
    if trusted_public_key is not None and not isinstance(trusted_public_key, Path):
        trusted_public_key = Path(trusted_public_key)

    try:
        playlist = parse_local_playlist(Path(manifest))
    except MediaVerificationError as error:
        raise IntegrityError(f"playlist verification failed: {error}") from error
    loaded = _load_bundle_index(
        playlist,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    _validate_segment_file_set(playlist)
    capabilities = probe_media_capabilities()
    inert_records = _extract_encoded_records(playlist, loaded, capabilities)

    previous = bytes(32)
    chain: list[tuple[bytes, bytes, bytes]] = []
    for expected_sequence, (canonical_bytes, frame_digest, sequence) in enumerate(inert_records):
        if sequence != expected_sequence:
            raise IntegrityError("decoded packet sequence is not contiguous and zero-based")
        computed = core.hash_packet(previous, canonical_bytes)
        if not hmac.compare_digest(computed, frame_digest):
            raise IntegrityError(
                f"segment {sequence} digest does not match recomputed ALD1 hash chain"
            )
        chain.append((canonical_bytes, previous, computed))
        previous = computed
    if not hmac.compare_digest(previous, loaded.root_hash):
        raise IntegrityError("decoded media root hash does not match bundle root hash")

    verified_packets: list[core.HashedPacket] = []
    for canonical_bytes, previous_digest, digest in chain:
        try:
            packet = media._decode_canonical_packet(canonical_bytes)
        except media.FrameDecodeError as error:
            raise IntegrityError(
                f"verified canonical packet could not be promoted: {error}"
            ) from error
        verified_packets.append(
            core.HashedPacket(
                packet=packet,
                canonical_bytes=canonical_bytes,
                previous_digest=previous_digest,
                digest=digest,
            )
        )

    return VerifiedMediaRecipe(
        packets=tuple(verified_packets),
        root_hash=loaded.root_hash,
        profile=loaded.profile,
        signature_status=loaded.signature_status,
    )