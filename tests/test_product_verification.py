from pathlib import Path
import hashlib
import json

import pytest

import ald_hardened_core as core
import ald_hls_integration as hls
import ald_hls_signature as signatures
import ald_media_codecs as media
import ald_product_bundle as product_bundle
import ald_product_mp4 as product_mp4
import ald_product_render as product_render
import ald_product_scene as product_scene
import ald_product_svg as product_svg
import ald_product_verify as product_verify


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")
_TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIDAYOmNdn8RZURscAMx3yLlZudv3epR/EGrgIUIz5qGC
-----END PRIVATE KEY-----
"""
_TEST_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA3adrEKJiQTNtvfeUoVSGQfmLlftJBfWiW3CCaDJskt8=
-----END PUBLIC KEY-----
"""


def _write_test_keys(directory: Path) -> tuple[Path, Path]:
    private_path = directory / "private.pem"
    public_path = directory / "public.pem"
    private_path.write_text(_TEST_PRIVATE_KEY_PEM, encoding="ascii")
    public_path.write_text(_TEST_PUBLIC_KEY_PEM, encoding="ascii")
    return private_path, public_path


def _compiled_majorana() -> core.CompiledRecipe:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    return core.compile_recipe(recipe)


def _canonical_recipe_bytes() -> bytes:
    value = json.loads(RECIPE.read_text(encoding="utf-8"))
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_stub_product_artifacts(root: Path) -> dict[str, Path]:
    root.mkdir()
    values = {
        "product": ("product.mp4", b"product-media"),
        "recipe": ("recipe.canonical.json", b"{}\n"),
        "scene": ("product.json", b"{}\n"),
        "top": ("product-top.svg", b"<svg>top</svg>\n"),
        "stack": ("product-stack.svg", b"<svg>stack</svg>\n"),
        "final": ("product-final.svg", b"<svg>final</svg>\n"),
    }
    paths: dict[str, Path] = {}
    for key, (name, content) in values.items():
        path = root / name
        path.write_bytes(content)
        paths[key] = path
    return paths


def _build_real_product_bundle(root: Path) -> tuple[Path, core.CompiledRecipe, bytes, bytes]:
    compiled = _compiled_majorana()
    simulation = core.SimulatedALDController().execute(compiled, seed=42)
    assert simulation.fault is None
    profile = media.DEFAULT_MEDIA_PROFILE
    capabilities = hls.probe_media_capabilities()

    bundle_root = root / "bundle"
    bundle_root.mkdir()
    tracks = product_render.stage_product_tracks(
        compiled,
        simulation,
        root / "tracks",
        profile,
    )
    product_path = product_mp4.mux_product_mp4(
        tracks,
        bundle_root / "product.mp4",
        capabilities,
        profile,
    )

    recipe_bytes = _canonical_recipe_bytes()
    recipe_path = bundle_root / "recipe.canonical.json"
    recipe_path.write_bytes(recipe_bytes)

    scene = product_scene.build_product_scene(
        compiled.recipe,
        stage="final",
        simulation=simulation,
    )
    views = product_svg.write_product_svgs(scene, bundle_root)
    view_sha256 = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in views.items()
    }
    document = product_scene.build_product_document(
        scene,
        recipe_sha256=hashlib.sha256(recipe_bytes).digest(),
        root_hash=compiled.root_hash,
        view_sha256=view_sha256,
    )
    product_bytes = product_scene.canonical_product_json(document)
    scene_path = bundle_root / "product.json"
    scene_path.write_bytes(product_bytes)

    index_path = product_bundle.write_product_bundle_index(
        compiled,
        product_path=product_path,
        recipe_path=recipe_path,
        scene_path=scene_path,
        top_svg_path=views["top"],
        stack_svg_path=views["stack"],
        final_svg_path=views["final"],
        destination=bundle_root / "bundle.json",
        profile=profile,
        render_seed=42,
        ffmpeg_version="test-runtime",
        video_encoder=capabilities.video_encoder,
        audio_encoder=capabilities.audio_encoder,
    )
    return index_path, compiled, recipe_bytes, product_bytes


def test_bundle_signature_accepts_explicit_exact_schema(tmp_path):
    expected_keys = frozenset({"protocol", "signature"})
    index_path = tmp_path / "bundle.json"
    index_path.write_text(
        json.dumps(
            {"protocol": "ALD-PRODUCT/1", "signature": None},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    private_path, public_path = _write_test_keys(tmp_path)

    record = signatures.sign_bundle_index(
        index_path,
        private_path,
        expected_keys=expected_keys,
    )

    assert record.algorithm == "Ed25519"
    assert signatures.verify_bundle_signature_bytes(
        index_path.read_bytes(),
        public_path,
        expected_keys=expected_keys,
    ) is signatures.SignatureStatus.VERIFIED


def test_product_bundle_index_binds_fixed_artifacts_and_packet_timeline(tmp_path):
    compiled = _compiled_majorana()
    paths = _write_stub_product_artifacts(tmp_path / "bundle")
    destination = paths["product"].parent / "bundle.json"

    result = product_bundle.write_product_bundle_index(
        compiled,
        product_path=paths["product"],
        recipe_path=paths["recipe"],
        scene_path=paths["scene"],
        top_svg_path=paths["top"],
        stack_svg_path=paths["stack"],
        final_svg_path=paths["final"],
        destination=destination,
        profile=media.DEFAULT_MEDIA_PROFILE,
        render_seed=42,
        ffmpeg_version="test-ffmpeg",
        video_encoder="libx264",
        audio_encoder="aac",
    )

    assert result == destination
    raw = destination.read_bytes()
    payload = json.loads(raw)
    assert raw == (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert set(payload) == product_bundle.PRODUCT_BUNDLE_KEYS
    assert payload["protocol"] == "ALD-MEDIA/1"
    assert payload["media_type"] == "product-mp4"
    assert payload["render_seed"] == 42
    assert payload["root_hash"] == compiled.root_hash.hex()
    assert payload["signature"] is None
    assert payload["ffmpeg"] == {
        "audio_encoder": "aac",
        "data_codec": "bin_data",
        "data_tag": "gpmd",
        "version": "test-ffmpeg",
        "video_encoder": "libx264",
    }
    for key, artifact_key, filename in (
        ("product", "product", "product.mp4"),
        ("recipe", "recipe", "recipe.canonical.json"),
        ("scene", "scene", "product.json"),
    ):
        assert payload[key] == {
            "path": filename,
            "sha256": hashlib.sha256(paths[artifact_key].read_bytes()).hexdigest(),
        }
    assert payload["views"] == {
        "final": {
            "path": "product-final.svg",
            "sha256": hashlib.sha256(paths["final"].read_bytes()).hexdigest(),
        },
        "stack": {
            "path": "product-stack.svg",
            "sha256": hashlib.sha256(paths["stack"].read_bytes()).hexdigest(),
        },
        "top": {
            "path": "product-top.svg",
            "sha256": hashlib.sha256(paths["top"].read_bytes()).hexdigest(),
        },
    }
    assert payload["packets"] == [
        {
            "digest": item.digest.hex(),
            "duration_ms": 3000,
            "pts_ms": sequence * 3000,
            "sequence": sequence,
        }
        for sequence, item in enumerate(compiled.packets)
    ]


@pytest.mark.requires_ffmpeg
def test_verify_product_bundle_recovers_exact_compiled_stream(tmp_path):
    index_path, compiled, recipe_bytes, product_bytes = _build_real_product_bundle(tmp_path)

    verified = product_verify.verify_product_bundle(index_path)

    assert verified.packets == compiled.packets
    assert verified.root_hash == compiled.root_hash
    assert verified.profile == media.DEFAULT_MEDIA_PROFILE
    assert verified.signature_status is signatures.SignatureStatus.UNSIGNED
    assert verified.recipe_bytes == recipe_bytes
    assert verified.product_bytes == product_bytes
    assert verified.render_seed == 42
