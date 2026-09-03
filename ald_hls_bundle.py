"""Strict local-only HLS playlist parsing and deterministic ALD bundle indexes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import ald_hardened_core as core
import ald_media_codecs as media


_BUNDLE_PROTOCOL = "ALD-MEDIA/1"
_TOOL_VERSION = "0.1.0"
_RECIPE_FILENAME = "recipe.canonical.json"
_MAP_RE = re.compile(r'^#EXT-X-MAP:URI="([^"]+)"$')
_DURATION_MIN_SECONDS = 2.95
_DURATION_MAX_SECONDS = 3.05


class MediaVerificationError(core.ALDError):
    """Raised when local media metadata is unsafe, malformed, or inconsistent."""

    exit_code = core.ExitCode.MEDIA


@dataclass(frozen=True)
class PlaylistSegment:
    uri: str
    path: Path
    duration: float
    index: int


@dataclass(frozen=True)
class LocalPlaylist:
    path: Path
    initialization_path: Path
    segments: tuple[PlaylistSegment, ...]


@dataclass(frozen=True)
class BundlePacket:
    sequence: int
    segment: str
    digest: bytes
    duration_seconds: float


@dataclass(frozen=True)
class BundleIndex:
    protocol: str
    manifest: str
    initialization: str
    recipe: Mapping[str, str]
    packets: tuple[BundlePacket, ...]
    root_hash: bytes
    media_profile: Mapping[str, Any]
    ffmpeg: Mapping[str, str]
    signature: Mapping[str, str] | None
    creation_tool_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe", MappingProxyType(dict(self.recipe)))
        object.__setattr__(self, "media_profile", MappingProxyType(dict(self.media_profile)))
        object.__setattr__(self, "ffmpeg", MappingProxyType(dict(self.ffmpeg)))
        if self.signature is not None:
            object.__setattr__(self, "signature", MappingProxyType(dict(self.signature)))


def _read_playlist_text(path: Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise MediaVerificationError(f"playlist is not a regular file: {source}")
    try:
        return source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise MediaVerificationError(f"unable to read UTF-8 playlist: {error}") from error


def _resolve_local_relative_uri(root: Path, uri: str, label: str) -> Path:
    if type(uri) is not str or not uri:
        raise MediaVerificationError(f"{label} URI must be a local relative path")
    if "\\" in uri or "\x00" in uri:
        raise MediaVerificationError(f"{label} URI must be a local relative path")

    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise MediaVerificationError(f"{label} URI must be a local relative path")

    pure = PurePosixPath(uri)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise MediaVerificationError(f"{label} URI must be a local relative path")

    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise MediaVerificationError(f"{label} URI must be a local relative path") from error
    if not candidate.is_file():
        raise MediaVerificationError(f"{label} target is missing: {uri}")
    return candidate


def _parse_duration(line: str) -> float:
    payload = line.removeprefix("#EXTINF:")
    if not payload.endswith(","):
        raise MediaVerificationError("playlist segment duration is malformed")
    try:
        duration = float(payload[:-1])
    except ValueError as error:
        raise MediaVerificationError("playlist segment duration is malformed") from error
    if (
        not math.isfinite(duration)
        or duration < _DURATION_MIN_SECONDS
        or duration > _DURATION_MAX_SECONDS
    ):
        raise MediaVerificationError("playlist segment duration is outside the allowed media interval")
    return duration


def _validate_playlist_segment_set(root: Path, expected_uris: set[str]) -> None:
    try:
        actual_uris = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*.m4s")
        }
    except (OSError, ValueError) as error:
        raise MediaVerificationError(f"unable to enumerate playlist media segments: {error}") from error
    if actual_uris != expected_uris:
        extras = sorted(actual_uris - expected_uris)
        missing = sorted(expected_uris - actual_uris)
        details: list[str] = []
        if extras:
            details.append(f"extra={extras}")
        if missing:
            details.append(f"missing={missing}")
        suffix = "; ".join(details) if details else "mismatch"
        raise MediaVerificationError(f"playlist media segment set does not match references: {suffix}")


def parse_local_playlist(path: Path) -> LocalPlaylist:
    """Parse the intentionally small, local-only HLS VOD subset emitted by this project."""
    source = Path(path).resolve()
    text = _read_playlist_text(source)
    raw_lines = text.splitlines()
    if not raw_lines or raw_lines[0] != "#EXTM3U":
        raise MediaVerificationError("playlist must begin with #EXTM3U")
    if any(not line.strip() for line in raw_lines):
        raise MediaVerificationError("playlist contains an empty line")
    lines = [line.strip() for line in raw_lines]
    if lines.count("#EXT-X-ENDLIST") != 1 or lines[-1] != "#EXT-X-ENDLIST":
        raise MediaVerificationError("playlist must contain one terminal #EXT-X-ENDLIST")

    singleton_prefixes = {
        "#EXT-X-VERSION:": "version",
        "#EXT-X-TARGETDURATION:": "target duration",
        "#EXT-X-MEDIA-SEQUENCE:": "media sequence",
        "#EXT-X-PLAYLIST-TYPE:": "playlist type",
        "#EXT-X-INDEPENDENT-SEGMENTS": "independent segments",
        "#EXT-X-MAP:": "initialization map",
    }
    seen: set[str] = set()
    initialization_path: Path | None = None
    pending_duration: float | None = None
    segments: list[PlaylistSegment] = []
    seen_uris: set[str] = set()

    for line in lines[1:-1]:
        if pending_duration is not None:
            if line.startswith("#"):
                raise MediaVerificationError("playlist EXTINF must be followed immediately by a segment URI")
            target = _resolve_local_relative_uri(source.parent, line, "segment")
            if line in seen_uris:
                raise MediaVerificationError("playlist contains a duplicate segment URI")
            seen_uris.add(line)
            segments.append(
                PlaylistSegment(
                    uri=line,
                    path=target,
                    duration=pending_duration,
                    index=len(segments),
                )
            )
            pending_duration = None
            continue

        if not line.startswith("#"):
            raise MediaVerificationError("playlist segment URI is missing its EXTINF duration")
        if line == "#EXT-X-DISCONTINUITY":
            raise MediaVerificationError("playlist discontinuity is not permitted")
        if line.startswith(("#EXT-X-BYTERANGE", "#EXT-X-KEY", "#EXT-X-SESSION-KEY")):
            raise MediaVerificationError("playlist byte ranges and encryption keys are not permitted")
        if line.startswith(("#EXT-X-STREAM-INF", "#EXT-X-I-FRAME-STREAM-INF", "#EXT-X-MEDIA:")):
            raise MediaVerificationError("master playlists are not permitted")
        if line.startswith("#EXTINF:"):
            if initialization_path is None:
                raise MediaVerificationError("playlist segment appears before initialization map")
            pending_duration = _parse_duration(line)
            continue

        matched_singleton = None
        for prefix, label in singleton_prefixes.items():
            if line == prefix or line.startswith(prefix):
                matched_singleton = (prefix, label)
                break
        if matched_singleton is None:
            raise MediaVerificationError(f"unsupported playlist tag: {line}")
        prefix, label = matched_singleton
        if label in seen:
            raise MediaVerificationError(f"playlist contains duplicate {label} tag")
        seen.add(label)

        if prefix == "#EXT-X-MAP:":
            match = _MAP_RE.fullmatch(line)
            if match is None:
                raise MediaVerificationError("playlist initialization map is malformed")
            initialization_path = _resolve_local_relative_uri(
                source.parent, match.group(1), "initialization"
            )
        elif prefix == "#EXT-X-VERSION:":
            try:
                version = int(line.split(":", 1)[1])
            except ValueError as error:
                raise MediaVerificationError("playlist version is invalid") from error
            if version < 7:
                raise MediaVerificationError("playlist version must support fMP4")
        elif prefix == "#EXT-X-TARGETDURATION:":
            try:
                target_duration = int(line.split(":", 1)[1])
            except ValueError as error:
                raise MediaVerificationError("playlist target duration is invalid") from error
            if target_duration <= 0:
                raise MediaVerificationError("playlist target duration is invalid")
        elif prefix == "#EXT-X-MEDIA-SEQUENCE:":
            if line != "#EXT-X-MEDIA-SEQUENCE:0":
                raise MediaVerificationError("playlist media sequence must begin at zero")
        elif prefix == "#EXT-X-PLAYLIST-TYPE:":
            if line != "#EXT-X-PLAYLIST-TYPE:VOD":
                raise MediaVerificationError("playlist type must be VOD")
        elif prefix == "#EXT-X-INDEPENDENT-SEGMENTS":
            if line != "#EXT-X-INDEPENDENT-SEGMENTS":
                raise MediaVerificationError("independent-segments tag is malformed")

    if pending_duration is not None:
        raise MediaVerificationError("playlist ends before segment URI")
    if initialization_path is None:
        raise MediaVerificationError("playlist initialization map is missing")
    if not segments:
        raise MediaVerificationError("playlist contains no media segments")
    _validate_playlist_segment_set(source.parent, seen_uris)

    return LocalPlaylist(
        path=source,
        initialization_path=initialization_path,
        segments=tuple(segments),
    )


def _profile_dict(profile: media.MediaProfile) -> dict[str, Any]:
    return {
        "width": profile.width,
        "height": profile.height,
        "interval_seconds": profile.interval_seconds,
        "qr_error_correction": profile.qr_error_correction,
        "qr_box_size": profile.qr_box_size,
        "qr_border_modules": profile.qr_border_modules,
        "sample_rate": profile.sample_rate,
        "symbol_rate": profile.symbol_rate,
        "mark_hz": profile.mark_hz,
        "space_hz": profile.space_hz,
        "copies": profile.copies,
        "required_matching_copies": profile.required_matching_copies,
    }


def _relative_bundle_path(path: Path, root: Path, label: str) -> str:
    resolved = Path(path).resolve()
    root_resolved = root.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError as error:
        raise MediaVerificationError(f"{label} must remain inside the bundle directory") from error
    value = relative.as_posix()
    if not value or value == ".":
        raise MediaVerificationError(f"{label} must name a bundle file")
    return value


def _require_plain_string(value: str, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise MediaVerificationError(f"{label} must be a non-empty plain string")
    return value


def _recipe_metadata(recipe_path: Path, root: Path) -> dict[str, str]:
    source = Path(recipe_path)
    if source.is_symlink() or not source.is_file():
        raise MediaVerificationError("canonical recipe must be a real regular file")
    relative = _relative_bundle_path(source, root, "canonical recipe")
    if relative != _RECIPE_FILENAME:
        raise MediaVerificationError(
            f"canonical recipe must be named {_RECIPE_FILENAME} in the bundle root"
        )
    try:
        recipe_bytes = source.read_bytes()
    except OSError as error:
        raise MediaVerificationError(f"unable to read canonical recipe: {error}") from error
    return {
        "path": relative,
        "sha256": hashlib.sha256(recipe_bytes).hexdigest(),
    }


def write_bundle_index(
    compiled_recipe: core.CompiledRecipe,
    playlist: LocalPlaylist,
    profile: media.MediaProfile,
    destination: Path,
    *,
    recipe_path: Path,
    ffmpeg_version: str,
    video_encoder: str,
    audio_encoder: str,
) -> Path:
    """Write canonical bundle metadata binding media and canonical recipe bytes."""
    if type(compiled_recipe) is not core.CompiledRecipe:
        raise MediaVerificationError("bundle index requires an exact CompiledRecipe")
    if type(playlist) is not LocalPlaylist:
        raise MediaVerificationError("bundle index requires an exact LocalPlaylist")
    if type(profile) is not media.MediaProfile:
        raise MediaVerificationError("bundle index requires an exact MediaProfile")

    target = Path(destination)
    if target.exists():
        raise MediaVerificationError(f"bundle index destination already exists: {target}")
    root = target.parent.resolve()
    if playlist.path.parent.resolve() != root:
        raise MediaVerificationError("playlist and bundle index must share one bundle directory")
    if len(playlist.segments) != len(compiled_recipe.packets):
        raise MediaVerificationError("bundle segment count does not match compiled packet count")

    ffmpeg_version = _require_plain_string(ffmpeg_version, "FFmpeg version")
    video_encoder = _require_plain_string(video_encoder, "video encoder")
    audio_encoder = _require_plain_string(audio_encoder, "audio encoder")

    manifest = _relative_bundle_path(playlist.path, root, "manifest")
    initialization = _relative_bundle_path(
        playlist.initialization_path, root, "initialization segment"
    )
    recipe = _recipe_metadata(recipe_path, root)
    packets: list[dict[str, Any]] = []
    bundle_packets: list[BundlePacket] = []
    for index, (hashed_packet, segment) in enumerate(
        zip(compiled_recipe.packets, playlist.segments, strict=True)
    ):
        if hashed_packet.packet.sequence != index or segment.index != index:
            raise MediaVerificationError("bundle packet sequence is not contiguous and zero-based")
        segment_name = _relative_bundle_path(segment.path, root, "media segment")
        if segment_name != segment.uri:
            raise MediaVerificationError("playlist segment URI does not match resolved bundle path")
        bundle_packet = BundlePacket(
            sequence=index,
            segment=segment.uri,
            digest=hashed_packet.digest,
            duration_seconds=segment.duration,
        )
        bundle_packets.append(bundle_packet)
        packets.append(
            {
                "sequence": index,
                "segment": segment.uri,
                "digest": hashed_packet.digest.hex(),
                "duration_seconds": segment.duration,
            }
        )

    ffmpeg = {
        "version": ffmpeg_version,
        "video_encoder": video_encoder,
        "audio_encoder": audio_encoder,
    }
    payload: dict[str, Any] = {
        "protocol": _BUNDLE_PROTOCOL,
        "media_profile": _profile_dict(profile),
        "ffmpeg": ffmpeg,
        "manifest": manifest,
        "initialization": initialization,
        "recipe": recipe,
        "packets": packets,
        "root_hash": compiled_recipe.root_hash.hex(),
        "signature": None,
        "creation_tool_version": _TOOL_VERSION,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise MediaVerificationError("bundle index is not canonical finite JSON") from error

    try:
        target.write_text(encoded, encoding="utf-8", newline="\n")
    except OSError as error:
        raise MediaVerificationError(f"unable to write bundle index: {error}") from error

    BundleIndex(
        protocol=_BUNDLE_PROTOCOL,
        manifest=manifest,
        initialization=initialization,
        recipe=recipe,
        packets=tuple(bundle_packets),
        root_hash=compiled_recipe.root_hash,
        media_profile=_profile_dict(profile),
        ffmpeg=ffmpeg,
        signature=None,
        creation_tool_version=_TOOL_VERSION,
    )
    return target