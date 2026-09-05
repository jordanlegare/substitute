"""Product-MP4 CLI orchestration layered over the existing ALD media CLI.

The product path remains simulation-only. Display pixels are never executable;
only a fully verified ALDP data track plus matching BFSK witness can be bound
back into a deterministic compiled recipe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from typing import Sequence

import ald_hardened_core as core
import ald_hls_integration as hls
import ald_hls_signature as signatures
import ald_media_cli as legacy
import ald_media_codecs as media
import ald_product_bundle as product_bundle
import ald_product_mp4 as product_mp4
import ald_product_render as product_render
import ald_product_scene as product_scene
import ald_product_svg as product_svg
import ald_product_verify as product_verify


_PRODUCT_COMMANDS = frozenset({"compile-product", "verify-product", "simulate-product"})
_PRODUCT_RENDER_SEED = 42
_PRODUCT_PROFILE = media.DEFAULT_MEDIA_PROFILE


def _commands_action(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) and action.dest == "command":
            return action
    raise RuntimeError("legacy CLI parser is missing its command subparser")


def build_parser():
    """Return the existing CLI parser extended with product-MP4 commands."""
    parser = legacy.build_parser()
    commands = _commands_action(parser)

    compile_product = commands.add_parser(
        "compile-product",
        help="compile a recipe into a verified product-stage MP4 bundle",
    )
    compile_product.add_argument("recipe", type=Path)
    compile_product.add_argument("--seed", type=int, default=_PRODUCT_RENDER_SEED)
    compile_product.add_argument("--output", type=Path, required=True)
    compile_product.add_argument("--overwrite", action="store_true")
    compile_product.add_argument("--signing-key", type=Path)
    core._add_log_level(compile_product)

    verify_product = commands.add_parser(
        "verify-product",
        help="verify a completed product-MP4 bundle",
    )
    verify_product.add_argument("bundle", type=Path)
    verify_product.add_argument("--require-signature", action="store_true")
    verify_product.add_argument("--trusted-public-key", type=Path)
    core._add_log_level(verify_product)

    simulate_product = commands.add_parser(
        "simulate-product",
        help="verify a product-MP4 bundle and run its trusted packet stream",
    )
    simulate_product.add_argument("bundle", type=Path)
    simulate_product.add_argument("--seed", type=int, required=True)
    simulate_product.add_argument("--output", type=Path, required=True)
    simulate_product.add_argument("--overwrite", action="store_true")
    simulate_product.add_argument("--require-signature", action="store_true")
    simulate_product.add_argument("--trusted-public-key", type=Path)
    core._add_log_level(simulate_product)
    return parser


def _write_product_document(
    scene: product_scene.ProductScene,
    *,
    recipe_path: Path,
    compiled: core.CompiledRecipe,
    views: dict[str, Path],
    destination: Path,
) -> bytes:
    try:
        recipe_bytes = recipe_path.read_bytes()
        view_sha256 = {
            key: hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in views.items()
        }
    except OSError as error:
        raise core.OutputError(f"unable to read staged product artifact: {error}") from error
    document = product_scene.build_product_document(
        scene,
        recipe_sha256=hashlib.sha256(recipe_bytes).digest(),
        root_hash=compiled.root_hash,
        view_sha256=view_sha256,
    )
    raw = product_scene.canonical_product_json(document)
    try:
        destination.write_bytes(raw)
    except OSError as error:
        raise core.OutputError(f"unable to write canonical product JSON: {error}") from error
    return raw


def _run_compile_product(
    recipe_path: Path,
    seed: int,
    output: Path,
    overwrite: bool,
    signing_key: Path | None,
) -> int:
    target = legacy._require_publishable_output(output, overwrite)
    core._reject_recipe_output_overlap(recipe_path, target)
    recipe = core.validate_recipe(core.load_recipe(recipe_path))
    compiled = core.compile_recipe(recipe)
    simulation = core.SimulatedALDController().execute(compiled, seed)
    if simulation.fault is not None:
        raise core.ALDError(f"product render simulation faulted: {simulation.fault}")

    capabilities = hls.probe_media_capabilities()
    product_mp4.probe_product_mp4_capabilities(capabilities)

    try:
        work_root = Path(tempfile.mkdtemp(prefix=f".{target.name}.product-build-", dir=target.parent))
    except OSError as error:
        raise core.OutputError(f"unable to create product build directory: {error}") from error

    candidate: Path | None = None
    try:
        candidate = work_root / "bundle"
        candidate.mkdir(mode=0o700)

        final_scene = product_scene.build_product_scene(
            recipe,
            stage="final",
            simulation=simulation,
        )
        views = dict(product_svg.write_product_svgs(final_scene, candidate))

        tracks = product_render.stage_product_tracks(
            compiled,
            simulation,
            work_root / "source-media",
            _PRODUCT_PROFILE,
        )
        product_path = product_mp4.mux_product_mp4(
            tracks,
            candidate / "product.mp4",
            capabilities,
            _PRODUCT_PROFILE,
        )

        canonical_recipe_path = candidate / "recipe.canonical.json"
        legacy._write_recipe_file(recipe, canonical_recipe_path)
        product_bytes = _write_product_document(
            final_scene,
            recipe_path=canonical_recipe_path,
            compiled=compiled,
            views=views,
            destination=candidate / "product.json",
        )

        index_path = product_bundle.write_product_bundle_index(
            compiled,
            product_path=product_path,
            recipe_path=canonical_recipe_path,
            scene_path=candidate / "product.json",
            top_svg_path=views["top"],
            stack_svg_path=views["stack"],
            final_svg_path=views["final"],
            destination=candidate / "bundle.json",
            profile=_PRODUCT_PROFILE,
            render_seed=seed,
            ffmpeg_version=legacy._ffmpeg_version(capabilities),
            video_encoder=capabilities.video_encoder,
            audio_encoder=capabilities.audio_encoder,
        )

        trusted_key: Path | None = None
        require_signature = False
        if signing_key is not None:
            signatures.sign_bundle_index(
                index_path,
                signing_key,
                expected_keys=product_bundle.PRODUCT_BUNDLE_KEYS,
            )
            trusted_key = legacy._derive_public_key(
                signing_key,
                work_root / "trusted-product-build-key.pem",
            )
            require_signature = True

        verified = product_verify.verify_product_bundle(
            index_path,
            require_signature=require_signature,
            trusted_public_key=trusted_key,
        )
        recipe_bytes = canonical_recipe_path.read_bytes()
        if (
            verified.root_hash != compiled.root_hash
            or verified.packets != compiled.packets
            or verified.recipe_bytes != recipe_bytes
            or verified.product_bytes != product_bytes
            or verified.render_seed != seed
        ):
            raise product_verify.IntegrityError(
                "completed product media does not reproduce the compiled recipe and product document"
            )

        legacy._publish_verified_bundle(candidate, target, overwrite=overwrite)
        candidate = None
        return int(core.ExitCode.OK)
    finally:
        if candidate is not None:
            legacy._safe_remove_tree(candidate)
        legacy._safe_remove_tree(work_root)


def _run_verify_product(
    bundle: Path,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> int:
    verified = product_verify.verify_product_bundle(
        bundle,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    payload = {
        "protocol": "ALD-MEDIA/1",
        "media_type": "product-mp4",
        "packet_count": len(verified.packets),
        "root_hash": verified.root_hash.hex(),
        "media_profile": legacy._profile_payload(verified.profile),
        "signature_status": verified.signature_status.value,
        "render_seed": verified.render_seed,
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


def _run_simulate_product(
    bundle: Path,
    seed: int,
    output: Path,
    overwrite: bool,
    require_signature: bool,
    trusted_public_key: Path | None,
) -> int:
    verified = product_verify.verify_product_bundle(
        bundle,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
    )
    compiled = legacy._bind_verified_recipe(verified)
    legacy._reject_media_output_overlap(bundle, output)
    result = core.SimulatedALDController().execute(compiled, seed)
    core.publish_reports(result, output, overwrite=overwrite)
    return int(core.ExitCode.CONTROLLER if result.fault is not None else core.ExitCode.OK)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else int(core.ExitCode.USAGE)
    except core.ALDError as error:
        return legacy._emit_cli_error(error, error.exit_code)

    if arguments.command not in _PRODUCT_COMMANDS:
        return legacy.main(argv)

    log_level = getattr(arguments, "log_level", getattr(arguments, "global_log_level", "INFO"))
    try:
        if arguments.command == "compile-product":
            return _run_compile_product(
                arguments.recipe,
                arguments.seed,
                arguments.output,
                arguments.overwrite,
                arguments.signing_key,
            )
        if arguments.command == "verify-product":
            return _run_verify_product(
                arguments.bundle,
                arguments.require_signature,
                arguments.trusted_public_key,
            )
        if arguments.command == "simulate-product":
            return _run_simulate_product(
                arguments.bundle,
                arguments.seed,
                arguments.output,
                arguments.overwrite,
                arguments.require_signature,
                arguments.trusted_public_key,
            )
        raise core.ALDError(f"unsupported product command: {arguments.command}")
    except core.ALDError as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        return legacy._emit_cli_error(error, error.exit_code)
    except Exception as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        fallback = {
            "compile-product": core.ExitCode.MEDIA,
            "verify-product": core.ExitCode.INTEGRITY,
            "simulate-product": core.ExitCode.CONTROLLER,
        }.get(arguments.command, core.ExitCode.USAGE)
        return legacy._emit_cli_error(error, fallback)
