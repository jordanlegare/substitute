"""Optional Ed25519 signing and trusted-key verification for ALD bundle indexes."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import tempfile
from typing import Any

import ald_hardened_core as core


_SIGNATURE_DOMAIN = b"ALD-BUNDLE-SIGNATURE\x00"
_SIGNATURE_KEYS = frozenset({"algorithm", "public_key_fingerprint", "signature"})
_BUNDLE_KEYS = frozenset(
    {
        "protocol",
        "media_profile",
        "ffmpeg",
        "manifest",
        "initialization",
        "recipe",
        "packets",
        "root_hash",
        "signature",
        "creation_tool_version",
    }
)


class SignatureError(core.ALDError):
    """Raised for malformed or untrusted bundle signatures."""

    exit_code = core.ExitCode.INTEGRITY


class SignatureStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class BundleSignature:
    algorithm: str
    public_key_fingerprint: str
    signature: str


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as error:
        raise core.DependencyError(
            "Ed25519 bundle signatures require the optional signature dependency; "
            "install with: pip install -e '.[signature]'"
        ) from error
    return InvalidSignature, serialization, Ed25519PrivateKey, Ed25519PublicKey


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise SignatureError("bundle index object key must be a string")
        if key in result:
            raise SignatureError(f"bundle index contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise SignatureError(f"bundle index contains non-finite number: {value}")


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
        raise SignatureError("bundle index cannot be canonicalized") from error
    return text.encode("utf-8")


def _load_bundle(path: Path) -> tuple[dict[str, Any], bytes]:
    source = Path(path)
    if not source.is_file():
        raise SignatureError(f"bundle index is not a regular file: {source}")
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SignatureError(f"unable to read bundle index: {error}") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except SignatureError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SignatureError("bundle index is not valid JSON") from error
    if type(value) is not dict or set(value) != _BUNDLE_KEYS:
        raise SignatureError("bundle index has unexpected or missing fields")
    if _canonical_json(value) != raw:
        raise SignatureError("bundle index is not canonical sorted compact JSON")
    return value, raw


def _unsigned_bytes(bundle: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in bundle.items() if key != "signature"}
    return _SIGNATURE_DOMAIN + _canonical_json(unsigned)


def _fingerprint(public_key, serialization) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
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
        os.replace(temporary_name, target)
        temporary_name = None
    except OSError as error:
        raise SignatureError(f"unable to publish signed bundle index: {error}") from error
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def sign_bundle_index(index_path: Path, private_key_path: Path) -> BundleSignature:
    """Sign one canonical unsigned bundle index with an Ed25519 private key."""
    _, serialization, Ed25519PrivateKey, _ = _crypto()
    bundle, _ = _load_bundle(Path(index_path))
    if bundle["signature"] is not None:
        raise SignatureError("bundle index is already signed")

    try:
        private_bytes = Path(private_key_path).read_bytes()
    except OSError as error:
        raise SignatureError(f"unable to read signing key: {error}") from error
    try:
        private_key = serialization.load_pem_private_key(private_bytes, password=None)
    except (TypeError, ValueError) as error:
        raise SignatureError("signing key is not a valid unencrypted PEM private key") from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SignatureError("signing key must be an Ed25519 private key")

    public_key = private_key.public_key()
    fingerprint = _fingerprint(public_key, serialization)
    signature_bytes = private_key.sign(_unsigned_bytes(bundle))
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")
    record = BundleSignature(
        algorithm="Ed25519",
        public_key_fingerprint=fingerprint,
        signature=signature_b64,
    )
    bundle["signature"] = {
        "algorithm": record.algorithm,
        "public_key_fingerprint": record.public_key_fingerprint,
        "signature": record.signature,
    }
    _atomic_write(Path(index_path), _canonical_json(bundle))
    return record


def verify_bundle_signature(index_path: Path, trusted_public_key: Path) -> SignatureStatus:
    """Verify a signed canonical bundle index against a caller-supplied Ed25519 key."""
    InvalidSignature, serialization, _, Ed25519PublicKey = _crypto()
    bundle, _ = _load_bundle(Path(index_path))
    signature = bundle["signature"]
    if signature is None:
        return SignatureStatus.UNSIGNED
    if type(signature) is not dict or set(signature) != _SIGNATURE_KEYS:
        raise SignatureError("bundle signature has unexpected or missing fields")
    if signature.get("algorithm") != "Ed25519":
        raise SignatureError("bundle signature algorithm must be Ed25519")

    fingerprint = signature.get("public_key_fingerprint")
    encoded_signature = signature.get("signature")
    if type(fingerprint) is not str or len(fingerprint) != 64:
        raise SignatureError("bundle public-key fingerprint is invalid")
    try:
        bytes.fromhex(fingerprint)
    except ValueError as error:
        raise SignatureError("bundle public-key fingerprint is invalid") from error
    if type(encoded_signature) is not str:
        raise SignatureError("bundle signature encoding is invalid")
    try:
        signature_bytes = base64.b64decode(encoded_signature, validate=True)
    except (ValueError, binascii.Error) as error:
        raise SignatureError("bundle signature is not valid base64") from error
    if len(signature_bytes) != 64:
        raise SignatureError("bundle Ed25519 signature must be 64 bytes")

    try:
        public_bytes = Path(trusted_public_key).read_bytes()
    except OSError as error:
        raise SignatureError(f"unable to read trusted public key: {error}") from error
    try:
        public_key = serialization.load_pem_public_key(public_bytes)
    except (TypeError, ValueError) as error:
        raise SignatureError("trusted public key is not a valid PEM public key") from error
    if not isinstance(public_key, Ed25519PublicKey):
        raise SignatureError("trusted public key must be an Ed25519 public key")

    trusted_fingerprint = _fingerprint(public_key, serialization)
    if not hmac.compare_digest(fingerprint, trusted_fingerprint):
        raise SignatureError("trusted public key fingerprint does not match bundle signature")

    try:
        public_key.verify(signature_bytes, _unsigned_bytes(bundle))
    except InvalidSignature as error:
        raise SignatureError("bundle signature verification failed") from error
    return SignatureStatus.VERIFIED