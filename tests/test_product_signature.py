from pathlib import Path
import json

import pytest

import ald_hls_signature as signatures
import ald_product_bundle as product_bundle
import ald_product_verify as product_verify


_TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIDAYOmNdn8RZURscAMx3yLlZudv3epR/EGrgIUIz5qGC
-----END PRIVATE KEY-----
"""
_TEST_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA3adrEKJiQTNtvfeUoVSGQfmLlftJBfWiW3CCaDJskt8=
-----END PUBLIC KEY-----
"""


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


def _unsigned_product_manifest() -> dict[str, object]:
    payload = {
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
    assert set(payload) == product_bundle.PRODUCT_BUNDLE_KEYS
    return payload


def _write_keys(root: Path) -> tuple[Path, Path]:
    private_path = root / "private.pem"
    public_path = root / "public.pem"
    private_path.write_text(_TEST_PRIVATE_KEY_PEM, encoding="ascii")
    public_path.write_text(_TEST_PUBLIC_KEY_PEM, encoding="ascii")
    return private_path, public_path


def test_product_signature_required_rejects_unsigned_manifest():
    manifest = _unsigned_product_manifest()
    raw = _canonical_json(manifest)

    with pytest.raises(product_verify.IntegrityError, match="signature is required"):
        product_verify._signature_status(
            manifest,
            raw,
            require_signature=True,
            trusted_public_key=None,
        )


def test_signed_product_manifest_verifies_exact_schema_and_bytes(tmp_path):
    index_path = tmp_path / "bundle.json"
    index_path.write_bytes(_canonical_json(_unsigned_product_manifest()))
    private_path, public_path = _write_keys(tmp_path)

    signatures.sign_bundle_index(
        index_path,
        private_path,
        expected_keys=product_bundle.PRODUCT_BUNDLE_KEYS,
    )
    signed_bytes = index_path.read_bytes()
    signed_manifest = json.loads(signed_bytes.decode("utf-8"))

    assert product_verify._signature_status(
        signed_manifest,
        signed_bytes,
        require_signature=True,
        trusted_public_key=public_path,
    ) is signatures.SignatureStatus.VERIFIED

    tampered = dict(signed_manifest)
    tampered["render_seed"] = 43
    tampered_bytes = _canonical_json(tampered)
    with pytest.raises(product_verify.IntegrityError, match="signature verification failed"):
        product_verify._signature_status(
            tampered,
            tampered_bytes,
            require_signature=True,
            trusted_public_key=public_path,
        )
