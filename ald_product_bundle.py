"""Canonical bundle metadata for verified product-MP4 artifacts.

The product bundle binds one display MP4, the canonical recipe, deterministic
product JSON/SVG views, and the compiled ALD packet chain.  This module only
writes inert metadata; it does not verify or execute instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import ald_hardened_core as core
import ald_media_codecs as media


PRODUCT_BUNDLE_KEYS = frozenset(
    {
        "protocol",
        "media_type",
        "media_profile",
        "ffmpeg",
        "product",
        "recipe",
        "scene",
        "views",
        "packets",
        "root_hash",
        "render_seed",
        "signature",
        "creation_tool_version",
    }
)

_PROTOCOL = "ALD-MEDIA/1"
_MEDIA_TYPE = "product-mp4"
_TOOL_VERSION = "0.1.0"
_BUNDLE_FILENAME = "bundle.json"
_FIXED_ARTIFACTS = {
    "product": "product.mp4",
    "recipe": "recipe.canonical.json",
    "scene": "product.json",
    "top": "product-top.svg",
    "stack": "product-stack.svg",
    "final": "product-final.svg",
}


class ProductBundleError(core.ALDError):
    """Raised when canonical product-bundle metadata cannot be produced."""

    exit_code = core.ExitCode.MEDIA


def _plain_string(value: object, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise ProductBundleError(f"{label} must be a non-empty plain string")
    return value


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


def _bound_artifact(path: Path, root: Path, expected_name: str, label: str) -> dict[str, str]:
    source = Path(path)
    if source.name != expected_name:
        raise ProductBundleError(f"{label} must be named {expected_name}")
    if source.is_symlink() or not source.is_file():
        raise ProductBundleError(f"{label} must be a real regular file")
    try:
        if source.resolve().parent != root.resolve():
            raise ProductBundleError(f"{label} must remain in the bundle root")
        content = source.read_bytes()
    except OSError as error:
        raise ProductBundleError(f"unable to read {label}: {error}") from error
    return {
        "path": expected_name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise ProductBundleError("product bundle index cannot be canonicalized") from error
    return text.encode("utf-8")


def _atomic_write_new(path: Path, content: bytes) -> None:
    target = Path(path)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() or target.is_symlink():
            raise ProductBundleError(f"product bundle index destination already exists: {target}")
        os.replace(temporary_name, target)
        temporary_name = None
    except ProductBundleError:
        raise
    except OSError as error:
        raise ProductBundleError(f"unable to publish product bundle index: {error}") from error
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def write_product_bundle_index(
    compiled: core.CompiledRecipe,
    *,
    product_path: Path,
    recipe_path: Path,
    scene_path: Path,
    top_svg_path: Path,
    stack_svg_path: Path,
    final_svg_path: Path,
    destination: Path,
    profile: media.MediaProfile,
    render_seed: int,
    ffmpeg_version: str,
    video_encoder: str,
    audio_encoder: str,
) -> Path:
    """Write one canonical, digest-bound product bundle index atomically."""
    if type(compiled) is not core.CompiledRecipe or type(compiled.packets) is not tuple:
        raise ProductBundleError("product bundle requires an exact CompiledRecipe")
    if type(profile) is not media.MediaProfile:
        raise ProductBundleError("product bundle requires an exact MediaProfile")
    if profile != media.DEFAULT_MEDIA_PROFILE:
        raise ProductBundleError("product bundle requires the fixed ALD media profile")
    if type(render_seed) is not int:
        raise ProductBundleError("product render seed must be an integer")
    if not compiled.packets:
        raise ProductBundleError("product bundle requires at least one compiled packet")
    if type(compiled.root_hash) is not bytes or len(compiled.root_hash) != 32:
        raise ProductBundleError("compiled product root hash must be 32 bytes")

    target = Path(destination)
    if target.name != _BUNDLE_FILENAME:
        raise ProductBundleError(f"product bundle index must be named {_BUNDLE_FILENAME}")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ProductBundleError("product bundle root must be a real directory")
    if target.exists() or target.is_symlink():
        raise ProductBundleError(f"product bundle index destination already exists: {target}")
    root = target.parent

    product = _bound_artifact(product_path, root, _FIXED_ARTIFACTS["product"], "product MP4")
    recipe = _bound_artifact(recipe_path, root, _FIXED_ARTIFACTS["recipe"], "canonical recipe")
    scene = _bound_artifact(scene_path, root, _FIXED_ARTIFACTS["scene"], "product JSON")
    views = {
        "final": _bound_artifact(final_svg_path, root, _FIXED_ARTIFACTS["final"], "final product SVG"),
        "stack": _bound_artifact(stack_svg_path, root, _FIXED_ARTIFACTS["stack"], "stack product SVG"),
        "top": _bound_artifact(top_svg_path, root, _FIXED_ARTIFACTS["top"], "top product SVG"),
    }

    interval_ms = int(round(profile.interval_seconds * 1000.0))
    if interval_ms != 3000 or abs(profile.interval_seconds - 3.0) > 1.0e-12:
        raise ProductBundleError("product bundle requires exact 3.0-second packet intervals")

    packets: list[dict[str, object]] = []
    previous_digest = bytes(32)
    for sequence, item in enumerate(compiled.packets):
        if type(item) is not core.HashedPacket:
            raise ProductBundleError("product bundle contains an invalid compiled packet")
        if item.packet.sequence != sequence:
            raise ProductBundleError("product packet sequence is not contiguous and zero-based")
        if type(item.digest) is not bytes or len(item.digest) != 32:
            raise ProductBundleError("product packet digest must be 32 bytes")
        if item.previous_digest != previous_digest:
            raise ProductBundleError("product packet previous-digest chain is invalid")
        recalculated = core.hash_packet(item.previous_digest, item.canonical_bytes)
        if recalculated != item.digest:
            raise ProductBundleError("product packet digest does not match canonical bytes")
        packets.append(
            {
                "sequence": sequence,
                "digest": item.digest.hex(),
                "pts_ms": sequence * interval_ms,
                "duration_ms": interval_ms,
            }
        )
        previous_digest = item.digest
    if previous_digest != compiled.root_hash:
        raise ProductBundleError("compiled product root hash does not match packet chain")

    payload: dict[str, Any] = {
        "protocol": _PROTOCOL,
        "media_type": _MEDIA_TYPE,
        "media_profile": _profile_dict(profile),
        "ffmpeg": {
            "version": _plain_string(ffmpeg_version, "FFmpeg version"),
            "video_encoder": _plain_string(video_encoder, "video encoder"),
            "audio_encoder": _plain_string(audio_encoder, "audio encoder"),
            "data_codec": "bin_data",
            "data_tag": "gpmd",
        },
        "product": product,
        "recipe": recipe,
        "scene": scene,
        "views": views,
        "packets": packets,
        "root_hash": compiled.root_hash.hex(),
        "render_seed": render_seed,
        "signature": None,
        "creation_tool_version": _TOOL_VERSION,
    }
    if set(payload) != PRODUCT_BUNDLE_KEYS:  # defensive schema invariant
        raise ProductBundleError("internal product bundle schema mismatch")

    _atomic_write_new(target, _canonical_bytes(payload))
    return target
