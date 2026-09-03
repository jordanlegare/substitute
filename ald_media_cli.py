"""CLI orchestration for verified ALD HLS/fMP4 bundles.

This module is intentionally local and simulation-only.  It compiles recipes
into media bundles, verifies completed encoded media, and feeds only verified
packet streams back into the deterministic simulated controller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
from typing import Any

import ald_hardened_core as core
import ald_media_codecs as media
from ald_media_staging import stage_packet_media
from ald_hls_bundle import parse_local_playlist, write_bundle_index
from ald_hls_integration import probe_media_capabilities, run_media_tool
from ald_hls_packaging import mux_packet_mp4, package_hls
from ald_hls_signature import SignatureError, sign_bundle_index
from ald_hls_verify import IntegrityError, SignatureStatus, verify_media_bundle


_MEDIA_PROFILE = media.DEFAULT_MEDIA_PROFILE
_MEDIA_TOOL_VERSION_TIMEOUT_SECONDS = 15.0


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    return value


def _recipe_payload(recipe: core.Recipe) -> dict[str, Any]:
    limits = recipe.limits
    return {
        "protocol": recipe.protocol,
        "recipe_id": recipe.recipe_id,
        "metadata": _thaw_json(recipe.metadata),
        "precursors": _thaw_json(recipe.precursors),
        "initial_conditions": _thaw_json(recipe.initial_conditions),
        "limits": {
            "min_purge_ms": limits.min_purge_ms,
            "max_temperature_c": limits.max_temperature_c,
            "max_pressure_pa": limits.max_pressure_pa,
            "max_cycles": limits.max_cycles,
            "max_runtime_ms": limits.max_runtime_ms,
            "max_residual_fraction": limits.max_residual_fraction,
            "max_packet_bytes": limits.max_packet_bytes,
        },
        "surface": _thaw_json(recipe.surface),
        "instructions": _thaw_json(recipe.instructions),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise core.OutputError(f"unable to canonicalize media metadata: {error}") from error
    return encoded.encode("utf-8")


def _write_recipe_file(recipe: core.Recipe, path: Path) -> None:
    try:
        path.write_bytes(_canonical_json_bytes(_recipe_payload(recipe)))
    except core.ALDError:
        raise
    except OSError as error:
        raise core.OutputError(f"unable to write canonical recipe: {error}") from error


def _profile_payload(profile: media.MediaProfile) -> dict[str, Any]:
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


def _exists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _require_publishable_output(output: Path, overwrite: bool) -> Path:
    target = core._absolute_output_path(output)
    if _exists(target):
        if not overwrite:
            raise core.OutputError(f"output directory already exists: {target}")
        if target.is_symlink() or not target.is_dir():
            raise core.OutputError("overwrite target must be a real directory")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise core.OutputError(f"unable to create output parent: {error}") from error
    return target


def _safe_remove_tree(path: Path) -> None:
    if not _exists(path):
        return
    try:
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)
    except OSError:
        pass


def _publish_verified_bundle(candidate: Path, output: Path, *, overwrite: bool) -> None:
    if not candidate.is_dir() or candidate.is_symlink():
        raise core.OutputError("verified bundle candidate is not a safe directory")
    if not _exists(output):
        try:
            os.replace(candidate, output)
        except OSError as error:
            raise core.OutputError(f"unable to publish verified media bundle: {error}") from error
        return
    if not overwrite:
        raise core.OutputError(f"output directory already exists: {output}")

    backup = output.parent / f".{output.name}.backup-{next(tempfile._get_candidate_names())}"
    while _exists(backup):
        backup = output.parent / f".{output.name}.backup-{next(tempfile._get_candidate_names())}"
    moved_old = False
    try:
        os.replace(output, backup)
        moved_old = True
        os.replace(candidate, output)
    except OSError as error:
        if moved_old and _exists(backup) and not _exists(output):
            try:
                os.replace(backup, output)
            except OSError as restore_error:
                raise core.OutputError(
                    f"media publication failed and previous output could not be restored: "
                    f"{error}; restore error: {restore_error}"
                ) from error
        raise core.OutputError(f"unable to publish verified media bundle: {error}") from error
    else:
        _safe_remove_tree(backup)


def _ffmpeg_version(capabilities) -> str:
    result = run_media_tool(
        [str(capabilities.ffmpeg), "-version"],
        timeout_seconds=_MEDIA_TOOL_VERSION_TIMEOUT_SECONDS,
    )
    for line in result.stdout.splitlines():
        value = line.strip()
        if value:
            return value
    raise core.DependencyError("ffmpeg did not report a version")


def _derive_public_key(private_key_path: Path, destination: Path) -> Path:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise core.DependencyError(
            "Ed25519 bundle signatures require the optional signature dependency; "
            "install with: pip install -e '.[signature]'"
        ) from error
    try:
        private_key = serialization.load_pem_private_key(
            Path(private_key_path).read_bytes(), password=None
        )
    except OSError as error:
        raise SignatureError(f"unable to read signing key: {error}") from error
    except (TypeError, ValueError) as error:
        raise SignatureError("signing key is not a valid unencrypted PEM private key") from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SignatureError("signing key must be an Ed25519 private key")
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    try:
        destination.write_bytes(public_bytes)
    except OSError as error:
        raise core.OutputError(f"unable to stage signing public key: {error}") from error
    return destination


def _run_compile(
    recipe_path: Path,
    output: Path,
    overwrite: bool,
    signing_key: Path | None,
) -> int:
    target = _require_publishable_output(output, overwrite)
    core._reject_recipe_output_overlap(recipe_path, target)
    recipe = core.validate_recipe(core.load_recipe(recipe_path))
    compiled = core.compile_recipe(recipe)
    capabilities = probe_media_capabilities()

    try:
        work_root = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.build-", dir=target.parent)
        )
    except OSError as error:
        raise core.OutputError(f"unable to create media build directory: {error}") from error

    candidate: Path | None = None
    try:
        artifacts = stage_packet_media(compiled, work_root / "source-media", _MEDIA_PROFILE)
        packet_dir = work_root / "packet-mp4s"
        packet_dir.mkdir(mode=0o700)
        packet_mp4s = tuple(
            mux_packet_mp4(
                artifact,
                packet_dir / f"packet-{artifact.sequence:06d}.mp4",
                capabilities,
                _MEDIA_PROFILE,
            )
            for artifact in artifacts
        )
        candidate = work_root / "bundle"
        manifest = package_hls(packet_mp4s, candidate, capabilities, _MEDIA_PROFILE)
        playlist = parse_local_playlist(manifest)
        canonical_recipe_path = candidate / "recipe.canonical.json"
        _write_recipe_file(recipe, canonical_recipe_path)
        index_path = write_bundle_index(
            compiled,
            playlist,
            _MEDIA_PROFILE,
            candidate / "bundle.json",
            recipe_path=canonical_recipe_path,
            ffmpeg_version=_ffmpeg_version(capabilities),
            video_encoder=capabilities.video_encoder,
            audio_encoder=capabilities.audio_encoder,
        )

        trusted_key: Path | None = None
        require_signature = False
        if signing_key is not None:
            sign_bundle_index(index_path, signing_key)
            trusted_key = _derive_public_key(signing_key, work_root / "trusted-build-key.pem")
            require_signature = True

        verified = verify_media_bundle(
            manifest,
            require_signature=require_signature,
            trusted_public_key=trusted_key,
        )
        if (
            verified.root_hash != compiled.root_hash
            or len(verified.packets) != len(compiled.packets)
            or any(
                actual.canonical_bytes != expected.canonical_bytes
                or actual.digest != expected.digest
                for actual, expected in zip(verified.packets, compiled.packets, strict=True)
            )
            or verified.recipe_bytes != canonical_recipe_path.read_bytes()
        ):
            raise IntegrityError("completed media does not reproduce the compiled recipe")

        _publish_verified_bundle(candidate, target, overwrite=overwrite)
        candidate = None
        return int(core.ExitCode.OK)
    finally:
        if candidate is not None:
            _safe_remove_tree(candidate)
        _safe_remove_tree(work_root)


def _run_verify(
    manifest: Path,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> int:
    verified = verify_media_bundle(
        manifest,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    payload = {
        "protocol": "ALD-MEDIA/1",
        "packet_count": len(verified.packets),
        "root_hash": verified.root_hash.hex(),
        "media_profile": _profile_payload(verified.profile),
        "signature_status": verified.signature_status.value,
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return int(core.ExitCode.OK)


def _bind_verified_recipe(verified) -> core.CompiledRecipe:
    if type(verified.recipe_bytes) is not bytes or not verified.recipe_bytes:
        raise IntegrityError("verified media bundle has no canonical recipe bytes")
    try:
        temporary_root = tempfile.TemporaryDirectory(prefix="ald-verified-recipe-")
    except OSError as error:
        raise IntegrityError(f"unable to create verified-recipe scratch directory: {error}") from error
    with temporary_root as temporary_name:
        recipe_path = Path(temporary_name) / "recipe.canonical.json"
        try:
            recipe_path.write_bytes(verified.recipe_bytes)
        except OSError as error:
            raise IntegrityError(f"unable to stage verified canonical recipe bytes: {error}") from error
        recipe = core.validate_recipe(core.load_recipe(recipe_path))
    compiled = core.compile_recipe(recipe)
    if len(compiled.packets) != len(verified.packets):
        raise IntegrityError("canonical recipe packet count does not match verified media")
    if compiled.root_hash != verified.root_hash:
        raise IntegrityError("canonical recipe root hash does not match verified media")
    for expected, actual in zip(compiled.packets, verified.packets, strict=True):
        if (
            expected.canonical_bytes != actual.canonical_bytes
            or expected.previous_digest != actual.previous_digest
            or expected.digest != actual.digest
        ):
            raise IntegrityError("canonical recipe packet stream does not match verified media")
    return compiled


def _reject_media_output_overlap(manifest: Path, output: Path) -> None:
    try:
        bundle_root = Path(os.path.realpath(os.fspath(Path(manifest).parent)))
        output_root = Path(os.path.realpath(os.fspath(core._absolute_output_path(output))))
    except (OSError, TypeError, ValueError) as error:
        raise core.OutputError(f"unable to resolve media/output paths safely: {error}") from error
    if (
        bundle_root == output_root
        or bundle_root in output_root.parents
        or output_root in bundle_root.parents
    ):
        raise core.OutputError("simulation output overlaps the media bundle or its ancestors")


def _run_simulate_media(
    manifest: Path,
    seed: int,
    output: Path,
    overwrite: bool,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> int:
    verified = verify_media_bundle(
        manifest,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    compiled = _bind_verified_recipe(verified)
    _reject_media_output_overlap(manifest, output)
    result = core.SimulatedALDController().execute(compiled, seed)
    core.publish_reports(result, output, overwrite=overwrite)
    return int(core.ExitCode.CONTROLLER if result.fault is not None else core.ExitCode.OK)


def build_parser():
    parser = core._CLIArgumentParser(prog="ald-media-controller")
    core._add_log_level(parser, default="INFO")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate and compile a recipe")
    validate.add_argument("recipe", type=Path)
    core._add_log_level(validate)

    simulate = commands.add_parser("simulate", help="run a recipe in the deterministic simulator")
    simulate.add_argument("recipe", type=Path)
    simulate.add_argument("--seed", type=int, required=True)
    simulate.add_argument("--output", type=Path, required=True)
    simulate.add_argument("--overwrite", action="store_true")
    core._add_log_level(simulate)

    compile_media = commands.add_parser("compile", help="compile a recipe into verified local HLS/fMP4")
    compile_media.add_argument("recipe", type=Path)
    compile_media.add_argument("--output", type=Path, required=True)
    compile_media.add_argument("--overwrite", action="store_true")
    compile_media.add_argument("--signing-key", type=Path)
    core._add_log_level(compile_media)

    verify = commands.add_parser("verify", help="verify a completed local ALD media bundle")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--require-signature", action="store_true")
    verify.add_argument("--trusted-public-key", type=Path)
    core._add_log_level(verify)

    simulate_media = commands.add_parser(
        "simulate-media", help="verify media and run it in the deterministic simulator"
    )
    simulate_media.add_argument("manifest", type=Path)
    simulate_media.add_argument("--seed", type=int, required=True)
    simulate_media.add_argument("--output", type=Path, required=True)
    simulate_media.add_argument("--overwrite", action="store_true")
    simulate_media.add_argument("--require-signature", action="store_true")
    simulate_media.add_argument("--trusted-public-key", type=Path)
    core._add_log_level(simulate_media)
    return parser


def _emit_cli_error(error: BaseException, exit_code) -> int:
    payload = {
        "error": {
            "type": type(error).__name__,
            "code": exit_code.name,
            "exit_code": int(exit_code),
            "message": str(error),
        }
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
    return int(exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else int(core.ExitCode.USAGE)
    except core.ALDError as error:
        return _emit_cli_error(error, error.exit_code)

    log_level = getattr(arguments, "log_level", getattr(arguments, "global_log_level", "INFO"))
    try:
        if arguments.command == "validate":
            return core._run_validate(arguments.recipe)
        if arguments.command == "simulate":
            return core._run_simulate(
                arguments.recipe,
                arguments.seed,
                arguments.output,
                arguments.overwrite,
            )
        if arguments.command == "compile":
            return _run_compile(
                arguments.recipe,
                arguments.output,
                arguments.overwrite,
                arguments.signing_key,
            )
        if arguments.command == "verify":
            return _run_verify(
                arguments.manifest,
                arguments.require_signature,
                arguments.trusted_public_key,
            )
        if arguments.command == "simulate-media":
            return _run_simulate_media(
                arguments.manifest,
                arguments.seed,
                arguments.output,
                arguments.overwrite,
                arguments.require_signature,
                arguments.trusted_public_key,
            )
        raise core.ALDError(f"unsupported command: {arguments.command}")
    except core.ALDError as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        return _emit_cli_error(error, error.exit_code)
    except Exception as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        fallback = {
            "validate": core.ExitCode.RECIPE,
            "simulate": core.ExitCode.CONTROLLER,
            "compile": core.ExitCode.MEDIA,
            "verify": core.ExitCode.INTEGRITY,
            "simulate-media": core.ExitCode.CONTROLLER,
        }.get(arguments.command, core.ExitCode.USAGE)
        return _emit_cli_error(error, fallback)