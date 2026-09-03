"""Deterministic local media codecs for ALD-MEDIA/1 packets.

This module is limited to inert data transformation. It performs no network
access and has no industrial-hardware control path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import struct
from typing import Any

import ald_core as core


QR_MAGIC = b"ALDQ\x01"
_QR_HEADER = struct.Struct(">IH")
_MAX_PACKET_BYTES = 800


class FrameDecodeError(core.ALDError):
    exit_code = core.ExitCode.FRAME


@dataclass(frozen=True)
class MediaProfile:
    width: int = 1920
    height: int = 1080
    interval_seconds: float = 3.0
    qr_error_correction: str = "Q"
    qr_box_size: int = 8
    qr_border_modules: int = 4
    sample_rate: int = 48_000
    symbol_rate: int = 1_200
    mark_hz: int = 2_400
    space_hz: int = 1_200
    copies: int = 3
    required_matching_copies: int = 2

    def __post_init__(self) -> None:
        for name in (
            "width", "height", "qr_box_size", "qr_border_modules", "sample_rate",
            "symbol_rate", "mark_hz", "space_hz", "copies", "required_matching_copies",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise FrameDecodeError(f"media profile {name} must be a positive integer")
        if type(self.interval_seconds) is not float or not math.isfinite(self.interval_seconds) or self.interval_seconds <= 0:
            raise FrameDecodeError("media profile interval_seconds must be a positive finite float")
        if type(self.qr_error_correction) is not str or self.qr_error_correction != "Q":
            raise FrameDecodeError("media profile QR error correction must be Q")
        if self.qr_box_size < 8:
            raise FrameDecodeError("media profile QR box size must be at least 8 pixels")
        if self.sample_rate % self.symbol_rate != 0:
            raise FrameDecodeError("media profile sample rate must be divisible by symbol rate")
        if self.mark_hz >= self.sample_rate // 2 or self.space_hz >= self.sample_rate // 2:
            raise FrameDecodeError("media profile BFSK carriers must be below Nyquist")
        if self.required_matching_copies > self.copies:
            raise FrameDecodeError("required matching copies cannot exceed total copies")


DEFAULT_MEDIA_PROFILE = MediaProfile()


@dataclass(frozen=True)
class DecodedFrameRecord:
    sequence: int
    digest: bytes
    canonical_bytes: bytes


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise FrameDecodeError("canonical packet object key must be a string")
        if key in result:
            raise FrameDecodeError(f"duplicate canonical packet key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise FrameDecodeError(f"non-finite JSON constant is not allowed: {value}")


def _decode_canonical_packet(payload: bytes) -> core.Packet:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise FrameDecodeError("canonical packet is not valid UTF-8") from error
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_nonfinite_constant)
    except FrameDecodeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise FrameDecodeError("canonical packet is not valid JSON") from error
    if type(raw) is not dict:
        raise FrameDecodeError("canonical packet must be a JSON object")
    if set(raw) != {"arguments", "opcode", "protocol", "recipe_id", "sequence"}:
        raise FrameDecodeError("canonical packet has unexpected fields")
    try:
        packet = core.Packet(
            protocol=raw["protocol"],
            recipe_id=raw["recipe_id"],
            sequence=raw["sequence"],
            opcode=raw["opcode"],
            arguments=raw["arguments"],
        )
        normalized = core.canonical_packet_bytes(packet)
    except core.ALDError as error:
        raise FrameDecodeError(f"canonical packet is invalid: {error}") from error
    except (TypeError, ValueError) as error:
        raise FrameDecodeError("canonical packet is invalid") from error
    if normalized != payload:
        raise FrameDecodeError("packet bytes are not canonical")
    return packet


def _validate_hashed_packet(item: core.HashedPacket) -> None:
    if type(item) is not core.HashedPacket or type(item.packet) is not core.Packet:
        raise FrameDecodeError("media input must be an exact HashedPacket")
    if type(item.canonical_bytes) is not bytes:
        raise FrameDecodeError("canonical packet bytes must be exact bytes")
    if len(item.canonical_bytes) > _MAX_PACKET_BYTES:
        raise FrameDecodeError("canonical packet exceeds 800 bytes")
    if type(item.previous_digest) is not bytes or len(item.previous_digest) != 32:
        raise FrameDecodeError("previous packet digest must be 32 bytes")
    if type(item.digest) is not bytes or len(item.digest) != 32:
        raise FrameDecodeError("packet digest must be 32 bytes")
    if type(item.packet.sequence) is not int or not 0 <= item.packet.sequence <= 0xFFFFFFFF:
        raise FrameDecodeError("packet sequence does not fit the QR envelope")
    try:
        normalized = core.canonical_packet_bytes(item.packet)
    except core.ALDError as error:
        raise FrameDecodeError(f"packet cannot be canonicalized: {error}") from error
    if normalized != item.canonical_bytes:
        raise FrameDecodeError("packet bytes are not canonical")
    expected = hashlib.sha256(b"ALD1" + item.previous_digest + item.canonical_bytes).digest()
    if not hmac.compare_digest(expected, item.digest):
        raise FrameDecodeError("packet digest does not match canonical packet chain input")


def encode_qr_payload(item: core.HashedPacket) -> bytes:
    _validate_hashed_packet(item)
    payload = item.canonical_bytes
    return QR_MAGIC + _QR_HEADER.pack(item.packet.sequence, len(payload)) + item.digest + payload


def decode_qr_payload(data: bytes) -> DecodedFrameRecord:
    """Decode a strict QR envelope and verify its canonical packet framing.

    The embedded digest is preserved verbatim. Its relationship to the prior
    packet digest is verified by the later ordered chain verifier, because an
    individual QR envelope intentionally does not carry the previous digest.
    """
    if type(data) is not bytes:
        raise FrameDecodeError("QR payload must be exact bytes")
    prefix_length = len(QR_MAGIC) + _QR_HEADER.size + 32
    if len(data) < prefix_length:
        raise FrameDecodeError("QR payload length is truncated")
    if data[: len(QR_MAGIC)] != QR_MAGIC:
        raise FrameDecodeError("QR payload magic/version mismatch")
    offset = len(QR_MAGIC)
    sequence, payload_length = _QR_HEADER.unpack_from(data, offset)
    offset += _QR_HEADER.size
    digest = data[offset : offset + 32]
    offset += 32
    if len(data) != offset + payload_length:
        raise FrameDecodeError("QR payload length does not match envelope")
    if payload_length > _MAX_PACKET_BYTES:
        raise FrameDecodeError("canonical packet exceeds 800 bytes")
    canonical_bytes = data[offset:]
    packet = _decode_canonical_packet(canonical_bytes)
    if packet.sequence != sequence:
        raise FrameDecodeError("QR envelope sequence does not match canonical packet")
    return DecodedFrameRecord(sequence=sequence, digest=digest, canonical_bytes=canonical_bytes)
