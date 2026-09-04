"""Fixed-width timed product-data records for the product-MP4 pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

import ald_hardened_core as core
import ald_media_codecs as media


DATA_MAGIC = b"ALDP"
DATA_VERSION = 1
DATA_SLOT_BYTES = 1024
MAX_CANONICAL_BYTES = 800
_HEADER = struct.Struct(">4sBIQIH32s")
_CRC = struct.Struct(">I")
_MAX_PTS_MS = (1 << 63) - 1
_MAX_DURATION_MS = (1 << 32) - 1


class ProductDataError(core.ALDError):
    """Raised when a timed product-data record is structurally invalid."""

    exit_code = core.ExitCode.INTEGRITY


@dataclass(frozen=True)
class ProductDataRecord:
    sequence: int
    pts_ms: int
    duration_ms: int
    digest: bytes
    canonical_bytes: bytes
    packet: core.Packet


def _require_pts_ms(value: int) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_PTS_MS:
        raise ProductDataError("product data PTS must be a nonnegative 63-bit integer")
    return value


def _require_duration_ms(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_DURATION_MS:
        raise ProductDataError("product data duration must be a positive 32-bit integer")
    return value


def encode_product_slot(
    item: core.HashedPacket,
    *,
    pts_ms: int,
    duration_ms: int,
) -> bytes:
    """Encode one verified hashed packet into an exact 1024-byte timed slot."""
    media.validate_hashed_packet(item)
    pts_ms = _require_pts_ms(pts_ms)
    duration_ms = _require_duration_ms(duration_ms)
    canonical_bytes = item.canonical_bytes
    if len(canonical_bytes) > MAX_CANONICAL_BYTES:
        raise ProductDataError("canonical packet exceeds product data payload limit")

    header = _HEADER.pack(
        DATA_MAGIC,
        DATA_VERSION,
        item.packet.sequence,
        pts_ms,
        duration_ms,
        len(canonical_bytes),
        item.digest,
    )
    body = header + canonical_bytes
    crc = _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
    encoded = body + crc
    if len(encoded) > DATA_SLOT_BYTES:
        raise ProductDataError("product data record exceeds fixed slot size")
    return encoded + bytes(DATA_SLOT_BYTES - len(encoded))


def decode_product_slot(slot: bytes) -> ProductDataRecord:
    """Decode one exact fixed-width product slot without trusting its digest yet."""
    if type(slot) is not bytes:
        raise ProductDataError("product data slot must be exact bytes")
    if len(slot) != DATA_SLOT_BYTES:
        raise ProductDataError("product data slot must be exactly 1024 bytes")

    try:
        magic, version, sequence, pts_ms, duration_ms, payload_length, digest = _HEADER.unpack_from(slot)
    except struct.error as error:  # defensive; exact slot length is already enforced
        raise ProductDataError("product data header is truncated") from error

    if magic != DATA_MAGIC:
        raise ProductDataError("product data magic is invalid")
    if version != DATA_VERSION:
        raise ProductDataError("product data version is unsupported")
    _require_pts_ms(pts_ms)
    _require_duration_ms(duration_ms)
    if payload_length > MAX_CANONICAL_BYTES:
        raise ProductDataError("product data canonical packet length exceeds limit")

    payload_start = _HEADER.size
    payload_end = payload_start + payload_length
    crc_end = payload_end + _CRC.size
    if crc_end > DATA_SLOT_BYTES:
        raise ProductDataError("product data payload exceeds fixed slot boundary")

    canonical_bytes = slot[payload_start:payload_end]
    expected_crc = _CRC.unpack(slot[payload_end:crc_end])[0]
    actual_crc = zlib.crc32(slot[:payload_end]) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        raise ProductDataError("product data CRC-32 does not match record bytes")
    if any(slot[crc_end:]):
        raise ProductDataError("product data padding must be zero")

    try:
        packet = media.decode_canonical_packet_bytes(canonical_bytes)
    except media.FrameDecodeError as error:
        raise ProductDataError(f"product data canonical packet is invalid: {error}") from error
    if packet.sequence != sequence:
        raise ProductDataError("product data envelope sequence does not match canonical packet")

    return ProductDataRecord(
        sequence=sequence,
        pts_ms=pts_ms,
        duration_ms=duration_ms,
        digest=digest,
        canonical_bytes=canonical_bytes,
        packet=packet,
    )


def build_product_slots(
    compiled: core.CompiledRecipe,
    *,
    interval_ms: int = 3000,
) -> tuple[bytes, ...]:
    """Build one real product-data slot per compiled packet with contiguous timing."""
    if type(compiled) is not core.CompiledRecipe:
        raise ProductDataError("product data source must be an exact CompiledRecipe")
    interval_ms = _require_duration_ms(interval_ms)
    if not compiled.packets:
        raise ProductDataError("compiled recipe must contain at least one packet")

    slots: list[bytes] = []
    for sequence, item in enumerate(compiled.packets):
        if item.packet.sequence != sequence:
            raise ProductDataError("compiled packet sequence is not contiguous and zero-based")
        pts_ms = sequence * interval_ms
        _require_pts_ms(pts_ms)
        slots.append(
            encode_product_slot(
                item,
                pts_ms=pts_ms,
                duration_ms=interval_ms,
            )
        )
    return tuple(slots)
