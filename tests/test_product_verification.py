from pathlib import Path
import json

import pytest

import ald_hls_signature as signatures


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
