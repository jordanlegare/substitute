from pathlib import Path
import hashlib
import json

import pytest

import ald_hardened_core as core
import ald_product_bundle as product_bundle
import ald_product_scene as product_scene
import ald_product_svg as product_svg
import ald_product_verify as product_verify


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def _canonical_json(value) -> bytes:
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


def _manifest_skeleton() -> dict[str, object]:
    value = {
        "protocol": "ALD-MEDIA/1",
        "media_type": "product-mp4",
        "media_profile": {},
        "ffmpeg": {},
        "product": {},
        "recipe": {},
        "scene": {},
        "views": {},
        "packets": [],
        "root_hash": "00" * 32,
        "render_seed": 42,
        "signature": None,
        "creation_tool_version": "0.1.0",
    }
    assert set(value) == product_bundle.PRODUCT_BUNDLE_KEYS
    return value


def _compiled_majorana() -> core.CompiledRecipe:
    return core.compile_recipe(core.validate_recipe(core.load_recipe(RECIPE)))


def test_product_manifest_rejects_noncanonical_json(tmp_path):
    index_path = tmp_path / "bundle.json"
    index_path.write_text(json.dumps(_manifest_skeleton(), indent=2) + "\n", encoding="utf-8")

    with pytest.raises(product_verify.IntegrityError, match="not canonical"):
        product_verify._parse_manifest(index_path)


def test_bound_product_artifact_rejects_digest_tamper(tmp_path):
    product_path = tmp_path / "product.mp4"
    original = b"original-product-media"
    product_path.write_bytes(original)
    entry = {
        "path": "product.mp4",
        "sha256": hashlib.sha256(original).hexdigest(),
    }
    product_path.write_bytes(b"tampered-product-media")

    with pytest.raises(product_verify.IntegrityError, match="SHA-256 does not match"):
        product_verify._read_bound_artifact(
            tmp_path,
            entry,
            expected_name="product.mp4",
            label="product MP4",
        )


def test_bound_product_artifact_rejects_symlink(tmp_path):
    real_path = tmp_path / "real.mp4"
    real_path.write_bytes(b"media")
    product_path = tmp_path / "product.mp4"
    product_path.symlink_to(real_path.name)
    entry = {
        "path": "product.mp4",
        "sha256": hashlib.sha256(real_path.read_bytes()).hexdigest(),
    }

    with pytest.raises(product_verify.IntegrityError, match="non-symlink"):
        product_verify._read_bound_artifact(
            tmp_path,
            entry,
            expected_name="product.mp4",
            label="product MP4",
        )


def test_recipe_tamper_with_updated_digest_still_cannot_match_authoritative_packets(tmp_path):
    compiled = _compiled_majorana()
    value = json.loads(RECIPE.read_text(encoding="utf-8"))
    value["instructions"][1]["arguments"]["target_c"] = 81.0
    raw = _canonical_json(value)
    recipe_path = tmp_path / "recipe.canonical.json"
    recipe_path.write_bytes(raw)

    with pytest.raises(product_verify.IntegrityError, match="recompilation does not match"):
        product_verify._verify_recipe(
            recipe_path,
            raw,
            compiled.packets,
            compiled.root_hash,
        )


def test_svg_tamper_with_updated_outer_digest_still_fails_deterministic_scene_binding():
    compiled = _compiled_majorana()
    simulation = core.SimulatedALDController().execute(compiled, seed=42)
    assert simulation.fault is None
    scene = product_scene.build_product_scene(
        compiled.recipe,
        stage="final",
        simulation=simulation,
    )
    views = {
        "top": product_svg.render_top_svg(scene),
        "stack": product_svg.render_stack_svg(scene),
        "final": product_svg.render_final_svg(scene),
    }
    view_digests = {
        key: hashlib.sha256(raw).hexdigest()
        for key, raw in views.items()
    }
    recipe_bytes = _canonical_json(json.loads(RECIPE.read_text(encoding="utf-8")))
    document = product_scene.build_product_document(
        scene,
        recipe_sha256=hashlib.sha256(recipe_bytes).digest(),
        root_hash=compiled.root_hash,
        view_sha256=view_digests,
    )
    product_bytes = product_scene.canonical_product_json(document)
    tampered_views = dict(views)
    tampered_views["top"] = views["top"] + b"<!-- tamper -->\n"

    with pytest.raises(product_verify.IntegrityError, match="not the deterministic rendering"):
        product_verify._verify_product_document(
            product_bytes,
            compiled=compiled,
            recipe_bytes=recipe_bytes,
            root_hash=compiled.root_hash,
            render_seed=42,
            views=tampered_views,
            view_digests=view_digests,
        )
