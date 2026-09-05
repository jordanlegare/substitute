"""Fail-closed verification for product-MP4 bundles.

Executable packet objects are returned only after the canonical bundle index,
artifact digests, MP4 data stream, ALD1 hash chain, BFSK audio witness,
canonical recipe, and product JSON/SVG views agree. Video pixels are
presentation-only and are never used as an instruction source.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

import ald_hardened_core as core
import ald_hls_integration as hls
import ald_hls_signature as signatures
import ald_media_codecs as media
import ald_product_bundle as product_bundle
import ald_product_data as product_data
import ald_product_mp4 as product_mp4
import ald_product_scene as product_scene
import ald_product_svg as product_svg


_MANIFEST_PROTOCOL = "ALD-MEDIA/1"
_MEDIA_TYPE = "product-mp4"
_TOOL_VERSION = "0.1.0"
_ARTIFACT_KEYS = frozenset({"path", "sha256"})
_PACKET_KEYS = frozenset({"sequence", "digest", "pts_ms", "duration_ms"})
_FFMPEG_KEYS = frozenset({"version", "video_encoder", "audio_encoder", "data_codec", "data_tag"})
_VIEW_KEYS = frozenset({"top", "stack", "final"})
_MAX_AAC_TAIL_PADDING_SAMPLES = 1024
_FIXED_NAMES = {
    "product": "product.mp4",
    "recipe": "recipe.canonical.json",
    "scene": "product.json",
    "top": "product-top.svg",
    "stack": "product-stack.svg",
    "final": "product-final.svg",
}


class IntegrityError(core.ALDError):
    """Raised when any product-bundle trust invariant fails."""

    exit_code = core.ExitCode.INTEGRITY


@dataclass(frozen=True)
class VerifiedProductRecipe:
    packets: tuple[core.HashedPacket, ...]
    root_hash: bytes
    profile: media.MediaProfile
    signature_status: signatures.SignatureStatus
    recipe_bytes: bytes
    product_bytes: bytes
    render_seed: int


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise IntegrityError("product bundle object key must be a string")
        if key in result:
            raise IntegrityError(f"product bundle contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise IntegrityError(f"product bundle contains non-finite number: {value}")


def _canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise IntegrityError("product bundle cannot be canonicalized") from error
    return text.encode("utf-8")


def _parse_manifest(index_path: Path) -> tuple[dict[str, Any], bytes]:
    path = Path(index_path)
    if path.name != "bundle.json" or path.is_symlink() or not path.is_file():
        raise IntegrityError("product bundle index must be a regular bundle.json file")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise IntegrityError("product bundle root must be a real directory")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise IntegrityError(f"unable to read product bundle index: {error}") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except IntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise IntegrityError("product bundle index is not valid JSON") from error
    if type(value) is not dict or set(value) != product_bundle.PRODUCT_BUNDLE_KEYS:
        raise IntegrityError("product bundle index has unexpected or missing fields")
    if _canonical_json(value) != raw:
        raise IntegrityError("product bundle index is not canonical sorted compact JSON")
    return value, raw


def _digest_hex(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise IntegrityError(f"{label} SHA-256 is invalid")
    try:
        bytes.fromhex(value)
    except ValueError as error:
        raise IntegrityError(f"{label} SHA-256 is invalid") from error
    if value.lower() != value:
        raise IntegrityError(f"{label} SHA-256 must use lowercase hex")
    return value


def _read_bound_artifact(
    root: Path,
    entry: object,
    *,
    expected_name: str,
    label: str,
) -> tuple[Path, bytes]:
    if type(entry) is not dict or set(entry) != _ARTIFACT_KEYS:
        raise IntegrityError(f"{label} artifact record is invalid")
    if entry.get("path") != expected_name:
        raise IntegrityError(f"{label} artifact path is not the fixed bundle filename")
    expected_digest = _digest_hex(entry.get("sha256"), label)
    path = root / expected_name
    if path.is_symlink() or not path.is_file():
        raise IntegrityError(f"{label} artifact must be a regular non-symlink file")
    try:
        if path.resolve().parent != root.resolve():
            raise IntegrityError(f"{label} artifact escapes the product bundle root")
        raw = path.read_bytes()
    except OSError as error:
        raise IntegrityError(f"unable to read {label} artifact: {error}") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_digest:
        raise IntegrityError(f"{label} artifact SHA-256 does not match bundle index")
    return path, raw


def _profile_from_manifest(value: object) -> media.MediaProfile:
    if type(value) is not dict:
        raise IntegrityError("product media profile must be an object")
    expected = {
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
    if set(value) != expected:
        raise IntegrityError("product media profile has unexpected or missing fields")
    try:
        profile = media.MediaProfile(**value)
    except (TypeError, ValueError, core.ALDError) as error:
        raise IntegrityError(f"product media profile is invalid: {error}") from error
    if profile != media.DEFAULT_MEDIA_PROFILE:
        raise IntegrityError("product bundle does not use the fixed ALD media profile")
    return profile


def _plain_string(value: object, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise IntegrityError(f"{label} must be a non-empty plain string")
    return value


def _validate_ffmpeg(value: object) -> None:
    if type(value) is not dict or set(value) != _FFMPEG_KEYS:
        raise IntegrityError("product FFmpeg metadata has unexpected or missing fields")
    _plain_string(value["version"], "product FFmpeg version")
    _plain_string(value["video_encoder"], "product FFmpeg video encoder")
    _plain_string(value["audio_encoder"], "product FFmpeg audio encoder")
    if value["data_codec"] != "bin_data" or value["data_tag"] != "gpmd":
        raise IntegrityError("product FFmpeg data transport must be bin_data/gpmd")


def _manifest_packets(value: object, packet_count: int) -> tuple[dict[str, object], ...]:
    if type(value) is not list or len(value) != packet_count:
        raise IntegrityError("product packet index count does not match MP4 data packet count")
    records: list[dict[str, object]] = []
    for sequence, item in enumerate(value):
        if type(item) is not dict or set(item) != _PACKET_KEYS:
            raise IntegrityError("product packet index entry has unexpected or missing fields")
        if type(item["sequence"]) is not int or item["sequence"] != sequence:
            raise IntegrityError("product packet index sequence is not contiguous and zero-based")
        if type(item["pts_ms"]) is not int or item["pts_ms"] != sequence * 3000:
            raise IntegrityError("product packet index PTS is invalid")
        if type(item["duration_ms"]) is not int or item["duration_ms"] != 3000:
            raise IntegrityError("product packet index duration is invalid")
        _digest_hex(item["digest"], "product packet")
        records.append(item)
    return tuple(records)


def _decode_authoritative_packets(
    product_path: Path,
    capabilities: hls.MediaCapabilities,
    manifest_packets: tuple[dict[str, object], ...],
) -> tuple[core.HashedPacket, ...]:
    with tempfile.TemporaryDirectory(prefix="ald-product-verify-") as temporary:
        extracted_path = Path(temporary) / "product-data.bin"
        product_mp4.extract_product_data(product_path, extracted_path, capabilities)
        try:
            raw = extracted_path.read_bytes()
        except OSError as error:
            raise IntegrityError(f"unable to read extracted product data: {error}") from error

    expected_bytes = len(manifest_packets) * product_data.DATA_SLOT_BYTES
    if len(raw) != expected_bytes:
        raise IntegrityError("product MP4 authoritative data stream has invalid byte length")

    verified: list[core.HashedPacket] = []
    previous_digest = bytes(32)
    for sequence, manifest_record in enumerate(manifest_packets):
        offset = sequence * product_data.DATA_SLOT_BYTES
        slot = raw[offset : offset + product_data.DATA_SLOT_BYTES]
        try:
            record = product_data.decode_product_slot(slot)
        except core.ALDError as error:
            raise IntegrityError(f"product data slot {sequence} is invalid: {error}") from error
        if record.sequence != sequence:
            raise IntegrityError("product data sequence does not match packet index")
        if record.pts_ms != manifest_record["pts_ms"] or record.duration_ms != manifest_record["duration_ms"]:
            raise IntegrityError("product data timing does not match packet index")
        manifest_digest = bytes.fromhex(str(manifest_record["digest"]))
        calculated = core.hash_packet(previous_digest, record.canonical_bytes)
        if calculated != record.digest or record.digest != manifest_digest:
            raise IntegrityError("product data digest does not match ALD1 chain and packet index")
        item = core.HashedPacket(
            packet=record.packet,
            canonical_bytes=record.canonical_bytes,
            previous_digest=previous_digest,
            digest=record.digest,
        )
        try:
            media.validate_hashed_packet(item)
        except core.ALDError as error:
            raise IntegrityError(f"verified product packet {sequence} is invalid: {error}") from error
        verified.append(item)
        previous_digest = record.digest
    return tuple(verified)


def _verify_audio_witness(
    product_path: Path,
    capabilities: hls.MediaCapabilities,
    profile: media.MediaProfile,
    packets: tuple[core.HashedPacket, ...],
) -> None:
    samples_per_interval = int(round(profile.sample_rate * profile.interval_seconds))
    if samples_per_interval != 144_000:
        raise IntegrityError("product audio witness profile must use exact 3-second 48 kHz intervals")
    expected_samples = len(packets) * samples_per_interval

    with tempfile.TemporaryDirectory(prefix="ald-product-audio-verify-") as temporary:
        pcm_path = Path(temporary) / "product-audio.pcm"
        try:
            product_mp4.extract_product_audio(product_path, pcm_path, capabilities)
            raw = pcm_path.read_bytes()
        except core.DependencyError:
            raise
        except (core.ALDError, OSError) as error:
            raise IntegrityError(f"product audio witness extraction failed: {error}") from error

    if len(raw) % 2 != 0:
        raise IntegrityError("product audio witness PCM byte length must be even")
    actual_samples = len(raw) // 2
    if actual_samples < expected_samples:
        raise IntegrityError(
            "product audio witness sample count mismatch: "
            f"expected_at_least={expected_samples} actual={actual_samples}"
        )
    tail_padding_samples = actual_samples - expected_samples
    if tail_padding_samples > _MAX_AAC_TAIL_PADDING_SAMPLES:
        raise IntegrityError(
            "product audio witness exceeds bounded AAC tail padding: "
            f"expected={expected_samples} actual={actual_samples} "
            f"max_padding={_MAX_AAC_TAIL_PADDING_SAMPLES}"
        )
    authoritative_raw = raw[: expected_samples * 2]
    samples = np.frombuffer(authoritative_raw, dtype="<i2").astype(np.float64) / 32767.0
    if samples.shape != (expected_samples,):
        raise IntegrityError("product audio witness PCM shape is invalid")

    for sequence, item in enumerate(packets):
        start = sequence * samples_per_interval
        interval = samples[start : start + samples_per_interval]
        try:
            record = media.decode_checksum_audio(interval, profile)
        except media.AudioDecodeError as error:
            raise IntegrityError(f"product audio witness interval {sequence} is invalid: {error}") from error
        if record.sequence != sequence:
            raise IntegrityError(f"product audio witness interval {sequence} has wrong sequence")
        if record.digest != item.digest:
            raise IntegrityError(f"product audio witness interval {sequence} digest does not match packet")


def _canonical_recipe_bytes(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except IntegrityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise IntegrityError("canonical product recipe is not valid JSON") from error
    if type(value) is not dict or _canonical_json(value) != raw:
        raise IntegrityError("product recipe is not canonical sorted compact JSON")


def _verify_recipe(
    recipe_path: Path,
    recipe_bytes: bytes,
    packets: tuple[core.HashedPacket, ...],
    root_hash: bytes,
) -> core.CompiledRecipe:
    _canonical_recipe_bytes(recipe_bytes)
    try:
        recipe = core.validate_recipe(core.load_recipe(recipe_path))
        compiled = core.compile_recipe(recipe)
    except core.ALDError as error:
        raise IntegrityError(f"product recipe cannot be validated and compiled: {error}") from error
    if compiled.root_hash != root_hash or compiled.packets != packets:
        raise IntegrityError("product recipe recompilation does not match authoritative MP4 packet stream")
    return compiled


def _verify_product_document(
    raw: bytes,
    *,
    compiled: core.CompiledRecipe,
    recipe_bytes: bytes,
    root_hash: bytes,
    render_seed: int,
    views: dict[str, bytes],
    view_digests: dict[str, str],
) -> None:
    try:
        document = product_scene.parse_product_json(raw)
    except core.ALDError as error:
        raise IntegrityError(f"product JSON is invalid: {error}") from error
    scene = document.scene
    if scene.physical_fabrication_mapping is not False:
        raise IntegrityError("product JSON must keep physical_fabrication_mapping=false")
    if scene.recipe_id != compiled.recipe.recipe_id:
        raise IntegrityError("product JSON recipe id does not match canonical recipe")
    if document.recipe_sha256 != hashlib.sha256(recipe_bytes).digest():
        raise IntegrityError("product JSON recipe SHA-256 does not match canonical recipe")
    if document.root_hash != root_hash:
        raise IntegrityError("product JSON packet root does not match authoritative packet chain")
    if dict(document.view_sha256) != view_digests:
        raise IntegrityError("product JSON view digests do not match bundle SVG digests")
    if scene.stage != "final" or scene.overlay is None or scene.overlay.seed != render_seed:
        raise IntegrityError("product JSON final scene/render seed binding is invalid")

    regenerated = {
        "top": product_svg.render_top_svg(scene),
        "stack": product_svg.render_stack_svg(scene),
        "final": product_svg.render_final_svg(scene),
    }
    for key in sorted(_VIEW_KEYS):
        if regenerated[key] != views[key]:
            raise IntegrityError(f"product {key} SVG is not the deterministic rendering of product JSON")


def _signature_status(
    manifest: dict[str, Any],
    manifest_bytes: bytes,
    *,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> signatures.SignatureStatus:
    if type(require_signature) is not bool:
        raise IntegrityError("require_signature must be a boolean")
    signature = manifest["signature"]
    if signature is None:
        if require_signature:
            raise IntegrityError("product bundle signature is required")
        return signatures.SignatureStatus.UNSIGNED
    if trusted_public_key is None:
        raise IntegrityError("signed product bundle requires a trusted public key")
    try:
        return signatures.verify_bundle_signature_bytes(
            manifest_bytes,
            Path(trusted_public_key),
            expected_keys=product_bundle.PRODUCT_BUNDLE_KEYS,
        )
    except core.DependencyError:
        raise
    except core.ALDError as error:
        raise IntegrityError(f"product bundle signature verification failed: {error}") from error


def verify_product_bundle(
    index_path: Path,
    *,
    require_signature: bool = False,
    trusted_public_key: Path | None = None,
) -> VerifiedProductRecipe:
    """Verify a complete product bundle and return only trusted packet objects."""
    manifest, manifest_bytes = _parse_manifest(Path(index_path))
    if manifest["protocol"] != _MANIFEST_PROTOCOL or manifest["media_type"] != _MEDIA_TYPE:
        raise IntegrityError("product bundle protocol/media type is invalid")
    if manifest["creation_tool_version"] != _TOOL_VERSION:
        raise IntegrityError("product bundle creation tool version is unsupported")
    if type(manifest["render_seed"]) is not int:
        raise IntegrityError("product bundle render seed must be an integer")
    render_seed = manifest["render_seed"]
    profile = _profile_from_manifest(manifest["media_profile"])
    _validate_ffmpeg(manifest["ffmpeg"])

    root = Path(index_path).parent
    product_path, _ = _read_bound_artifact(
        root, manifest["product"], expected_name=_FIXED_NAMES["product"], label="product MP4"
    )
    recipe_path, recipe_bytes = _read_bound_artifact(
        root, manifest["recipe"], expected_name=_FIXED_NAMES["recipe"], label="canonical recipe"
    )
    _, product_bytes = _read_bound_artifact(
        root, manifest["scene"], expected_name=_FIXED_NAMES["scene"], label="product JSON"
    )
    view_manifest = manifest["views"]
    if type(view_manifest) is not dict or set(view_manifest) != _VIEW_KEYS:
        raise IntegrityError("product SVG view index has unexpected or missing fields")
    views: dict[str, bytes] = {}
    view_digests: dict[str, str] = {}
    for key in sorted(_VIEW_KEYS):
        _, view_bytes = _read_bound_artifact(
            root,
            view_manifest[key],
            expected_name=_FIXED_NAMES[key],
            label=f"product {key} SVG",
        )
        views[key] = view_bytes
        view_digests[key] = _digest_hex(view_manifest[key]["sha256"], f"product {key} SVG")

    root_hex = _digest_hex(manifest["root_hash"], "product packet root")
    root_hash = bytes.fromhex(root_hex)
    packet_index_raw = manifest["packets"]
    if type(packet_index_raw) is not list or not packet_index_raw:
        raise IntegrityError("product packet index must be a non-empty array")
    packet_index = _manifest_packets(packet_index_raw, len(packet_index_raw))

    try:
        capabilities = hls.probe_media_capabilities()
        product_mp4.probe_product_mp4(
            product_path,
            capabilities,
            packet_count=len(packet_index),
            interval_seconds=profile.interval_seconds,
        )
    except core.DependencyError:
        raise
    except core.ALDError as error:
        raise IntegrityError(f"product MP4 profile verification failed: {error}") from error

    packets = _decode_authoritative_packets(product_path, capabilities, packet_index)
    if not packets or packets[-1].digest != root_hash:
        raise IntegrityError("product MP4 ALD1 packet root does not match bundle index")
    _verify_audio_witness(product_path, capabilities, profile, packets)
    compiled = _verify_recipe(recipe_path, recipe_bytes, packets, root_hash)
    _verify_product_document(
        product_bytes,
        compiled=compiled,
        recipe_bytes=recipe_bytes,
        root_hash=root_hash,
        render_seed=render_seed,
        views=views,
        view_digests=view_digests,
    )
    signature_status = _signature_status(
        manifest,
        manifest_bytes,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    return VerifiedProductRecipe(
        packets=packets,
        root_hash=root_hash,
        profile=profile,
        signature_status=signature_status,
        recipe_bytes=recipe_bytes,
        product_bytes=product_bytes,
        render_seed=render_seed,
    )