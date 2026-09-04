from pathlib import Path
import hashlib
import json

import pytest

import ald_hardened_core as core
import ald_hls_signature as signatures
import ald_media_codecs as media
import ald_product_bundle as product_bundle


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
    recipe = core.validate_recipe(
        core.load_recipe(Path("recipes/majorana2_public_specs_reference_sim.json"))
    )
    return core.compile_recipe(recipe)


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
