"""Deterministic local media codecs for ALD-MEDIA/1 packets.

This module is limited to inert data transformation. It performs no network
access and has no industrial-hardware control path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import struct
import textwrap
from typing import Any
import wave
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode.constants import ERROR_CORRECT_Q
import zxingcpp

import ald_core as core


QR_MAGIC = b"ALDQ\x01"
_QR_HEADER = struct.Struct(">IH")
_MAX_PACKET_BYTES = 800

AUDIO_PREAMBLE = b"\xAA" * 8
AUDIO_VERSION = 1
_AUDIO_BODY = struct.Struct(">BI32s")
_AUDIO_CRC = struct.Struct(">I")
AUDIO_RECORD_BYTES = len(AUDIO_PREAMBLE) + _AUDIO_BODY.size + _AUDIO_CRC.size
_AUDIO_GUARD_SECONDS = 0.1
_AUDIO_RAMP_SAMPLES = 4
_AUDIO_PEAK = 0.7


class FrameDecodeError(core.ALDError):
    exit_code = core.ExitCode.FRAME


class AudioDecodeError(core.ALDError):
    exit_code = core.ExitCode.AUDIO


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


@dataclass(frozen=True)
class AudioRecord:
    version: int
    sequence: int
    digest: bytes


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


def decode_canonical_packet_bytes(payload: bytes) -> core.Packet:
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
            protocol=raw["protocol"], recipe_id=raw["recipe_id"], sequence=raw["sequence"],
            opcode=raw["opcode"], arguments=raw["arguments"],
        )
        normalized = core.canonical_packet_bytes(packet)
    except core.ALDError as error:
        raise FrameDecodeError(f"canonical packet is invalid: {error}") from error
    except (TypeError, ValueError) as error:
        raise FrameDecodeError("canonical packet is invalid") from error
    if normalized != payload:
        raise FrameDecodeError("packet bytes are not canonical")
    return packet


def validate_hashed_packet(item: core.HashedPacket) -> None:
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
    validate_hashed_packet(item)
    payload = item.canonical_bytes
    return QR_MAGIC + _QR_HEADER.pack(item.packet.sequence, len(payload)) + item.digest + payload


def decode_qr_payload(data: bytes) -> DecodedFrameRecord:
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
    packet = decode_canonical_packet_bytes(canonical_bytes)
    if packet.sequence != sequence:
        raise FrameDecodeError("QR envelope sequence does not match canonical packet")
    return DecodedFrameRecord(sequence=sequence, digest=digest, canonical_bytes=canonical_bytes)


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _wrap_pixel_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    if max_width <= 0:
        raise FrameDecodeError("instruction frame has no text area")
    unit = max(draw.textlength("M", font=font), 1.0)
    width = max(int(max_width / unit), 1)
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or [""]


def render_instruction_frame(item: core.HashedPacket, profile: MediaProfile, destination: Path) -> Path:
    if type(profile) is not MediaProfile:
        raise FrameDecodeError("profile must be an exact MediaProfile")
    validate_hashed_packet(item)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=profile.qr_box_size, border=profile.qr_border_modules)
    qr.add_data(encode_qr_payload(item), optimize=0)
    try:
        qr.make(fit=True)
        symbol = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    except Exception as error:
        raise FrameDecodeError(f"unable to render QR symbol: {error}") from error
    margin, gutter = 32, 48
    if symbol.width + 2 * margin > profile.width or symbol.height + 2 * margin > profile.height:
        raise FrameDecodeError("QR symbol exceeds instruction frame bounds")
    text_x = margin + symbol.width + gutter
    text_width = profile.width - text_x - margin
    if text_width <= 0:
        raise FrameDecodeError("QR symbol leaves no room for instruction text")
    image = Image.new("RGB", (profile.width, profile.height), "white")
    image.paste(symbol, (margin, (profile.height - symbol.height) // 2))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    arguments = json.dumps(_plain_json(item.packet.arguments), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    lines = [item.packet.protocol, f"Recipe: {item.packet.recipe_id}", f"Sequence: {item.packet.sequence}", f"Opcode: {item.packet.opcode}", "Arguments:"]
    lines.extend(_wrap_pixel_text(draw, arguments, font, text_width))
    lines.append("Digest:")
    lines.extend(_wrap_pixel_text(draw, item.digest.hex(), font, text_width))
    text = "\n".join(lines)
    bbox = draw.multiline_textbbox((text_x, margin), text, font=font, spacing=8)
    if bbox[2] > profile.width - margin or bbox[3] > profile.height - margin:
        raise FrameDecodeError("instruction text exceeds frame bounds")
    draw.multiline_text((text_x, margin), text, fill="black", font=font, spacing=8)
    try:
        image.save(destination, format="PNG", optimize=False, compress_level=9)
    except OSError as error:
        raise FrameDecodeError(f"unable to write instruction frame: {error}") from error
    return destination


def decode_instruction_frame(path: Path, profile: MediaProfile) -> DecodedFrameRecord:
    if type(profile) is not MediaProfile:
        raise FrameDecodeError("profile must be an exact MediaProfile")
    try:
        with Image.open(Path(path)) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as error:
        raise FrameDecodeError(f"unable to read instruction frame: {error}") from error
    if image.size != (profile.width, profile.height):
        raise FrameDecodeError("unexpected frame dimensions")
    try:
        results = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    except Exception as error:
        raise FrameDecodeError(f"unable to decode QR frame: {error}") from error
    if len(results) != 1:
        raise FrameDecodeError(f"expected exactly one QR code, found {len(results)}")
    return decode_qr_payload(bytes(results[0].bytes))


def build_audio_record(sequence: int, digest: bytes) -> bytes:
    """Build the fixed 49-byte checksum record specified by the media profile."""
    if type(sequence) is not int or not 0 <= sequence <= 0xFFFFFFFF:
        raise AudioDecodeError("invalid audio sequence")
    if type(digest) is not bytes or len(digest) != 32:
        raise AudioDecodeError("audio digest must be exactly 32 bytes")
    body = _AUDIO_BODY.pack(AUDIO_VERSION, sequence, digest)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return AUDIO_PREAMBLE + body + _AUDIO_CRC.pack(crc)


def parse_audio_record(record: bytes) -> AudioRecord:
    if type(record) is not bytes:
        raise AudioDecodeError("audio record must be exact bytes")
    if len(record) != AUDIO_RECORD_BYTES:
        raise AudioDecodeError(f"audio record must be exactly {AUDIO_RECORD_BYTES} bytes")
    if record[: len(AUDIO_PREAMBLE)] != AUDIO_PREAMBLE:
        raise AudioDecodeError("audio preamble mismatch")
    body_start = len(AUDIO_PREAMBLE)
    body_end = body_start + _AUDIO_BODY.size
    body = record[body_start:body_end]
    version, sequence, digest = _AUDIO_BODY.unpack(body)
    if version != AUDIO_VERSION:
        raise AudioDecodeError("unsupported audio protocol version")
    expected_crc = zlib.crc32(body) & 0xFFFFFFFF
    (actual_crc,) = _AUDIO_CRC.unpack(record[body_end:])
    if actual_crc != expected_crc:
        raise AudioDecodeError("audio CRC mismatch")
    return AudioRecord(version=version, sequence=sequence, digest=digest)


def manchester_encode(data: bytes) -> tuple[int, ...]:
    if type(data) is not bytes:
        raise AudioDecodeError("Manchester input must be exact bytes")
    symbols: list[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bit = (byte >> shift) & 1
            symbols.extend((0, 1) if bit == 0 else (1, 0))
    return tuple(symbols)


def manchester_decode(symbols: Sequence[int]) -> bytes:
    if isinstance(symbols, (str, bytes, bytearray)):
        raise AudioDecodeError("Manchester symbols must be a numeric sequence")
    try:
        values = tuple(symbols)
    except TypeError as error:
        raise AudioDecodeError("Manchester symbols must be a sequence") from error
    if len(values) % 16 != 0:
        raise AudioDecodeError("Manchester symbol count must encode complete bytes")
    bits: list[int] = []
    for index in range(0, len(values), 2):
        left, right = values[index:index + 2]
        if type(left) is not int or type(right) is not int:
            raise AudioDecodeError("Manchester symbols must be integer 0/1 values")
        if (left, right) == (0, 1):
            bits.append(0)
        elif (left, right) == (1, 0):
            bits.append(1)
        else:
            raise AudioDecodeError("invalid Manchester symbol pair")
    output = bytearray()
    for index in range(0, len(bits), 8):
        value = 0
        for bit in bits[index:index + 8]:
            value = (value << 1) | bit
        output.append(value)
    return bytes(output)


def _audio_layout(profile: MediaProfile) -> tuple[int, int, int, int]:
    if type(profile) is not MediaProfile:
        raise AudioDecodeError("profile must be an exact MediaProfile")
    samples_per_symbol = profile.sample_rate // profile.symbol_rate
    guard_samples = int(round(_AUDIO_GUARD_SECONDS * profile.sample_rate))
    if guard_samples % samples_per_symbol != 0:
        raise AudioDecodeError("audio guard must align to a complete symbol boundary")
    record_samples = AUDIO_RECORD_BYTES * 8 * 2 * samples_per_symbol
    total_samples = int(round(profile.interval_seconds * profile.sample_rate))
    required = profile.copies * record_samples + (profile.copies + 1) * guard_samples
    if required > total_samples:
        raise AudioDecodeError("audio records do not fit inside the media interval")
    return samples_per_symbol, guard_samples, record_samples, total_samples


def _modulate_symbols(symbols: Sequence[int], profile: MediaProfile) -> np.ndarray:
    samples_per_symbol, _, _, _ = _audio_layout(profile)
    output = np.empty(len(symbols) * samples_per_symbol, dtype=np.float64)
    phase = 0.0
    cursor = 0
    sample_indexes = np.arange(samples_per_symbol, dtype=np.float64)
    for symbol in symbols:
        if symbol not in (0, 1):
            raise AudioDecodeError("BFSK symbols must be 0 or 1")
        frequency = profile.mark_hz if symbol == 1 else profile.space_hz
        step = 2.0 * math.pi * frequency / profile.sample_rate
        output[cursor:cursor + samples_per_symbol] = np.sin(phase + step * sample_indexes)
        phase = (phase + step * samples_per_symbol) % (2.0 * math.pi)
        cursor += samples_per_symbol
    if len(output) >= 2 * _AUDIO_RAMP_SAMPLES:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, math.pi, _AUDIO_RAMP_SAMPLES))
        output[:_AUDIO_RAMP_SAMPLES] *= ramp
        output[-_AUDIO_RAMP_SAMPLES:] *= ramp[::-1]
    return output


def encode_checksum_audio(sequence: int, digest: bytes, profile: MediaProfile) -> np.ndarray:
    """Encode three Manchester/BFSK checksum copies into one fixed interval."""
    _, guard_samples, record_samples, total_samples = _audio_layout(profile)
    record = build_audio_record(sequence, digest)
    symbols = manchester_encode(record)
    copy_wave = _modulate_symbols(symbols, profile)
    if len(copy_wave) != record_samples:
        raise AudioDecodeError("internal BFSK record length mismatch")
    output = np.zeros(total_samples, dtype=np.float64)
    for copy_index in range(profile.copies):
        start = guard_samples + copy_index * (record_samples + guard_samples)
        output[start:start + record_samples] = copy_wave
    peak = float(np.max(np.abs(output))) if len(output) else 0.0
    if peak <= 0.0 or not math.isfinite(peak):
        raise AudioDecodeError("BFSK waveform has no finite signal energy")
    output *= _AUDIO_PEAK / peak
    return output


def write_checksum_wav(sequence: int, digest: bytes, profile: MediaProfile, destination: Path) -> Path:
    samples = encode_checksum_audio(sequence, digest, profile)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    try:
        with wave.open(str(destination), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(profile.sample_rate)
            target.setcomptype("NONE", "not compressed")
            target.writeframes(pcm.tobytes(order="C"))
    except (OSError, wave.Error) as error:
        raise AudioDecodeError(f"unable to write checksum WAV: {error}") from error
    return destination


def read_checksum_wav(path: Path, profile: MediaProfile) -> np.ndarray:
    _, _, _, total_samples = _audio_layout(profile)
    try:
        with wave.open(str(Path(path)), "rb") as source:
            if source.getnchannels() != 1:
                raise AudioDecodeError("checksum WAV must be mono")
            if source.getsampwidth() != 2:
                raise AudioDecodeError("checksum WAV must use 16-bit PCM")
            if source.getframerate() != profile.sample_rate:
                raise AudioDecodeError("checksum WAV has unexpected sample rate")
            if source.getcomptype() != "NONE":
                raise AudioDecodeError("checksum WAV must be uncompressed PCM")
            if source.getnframes() != total_samples:
                raise AudioDecodeError("checksum WAV has unexpected duration")
            raw = source.readframes(total_samples)
    except AudioDecodeError:
        raise
    except (OSError, wave.Error, EOFError) as error:
        raise AudioDecodeError(f"unable to read checksum WAV: {error}") from error
    if len(raw) != total_samples * 2:
        raise AudioDecodeError("checksum WAV PCM data is truncated")
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32767.0


def _demodulate_symbols(samples: np.ndarray, profile: MediaProfile) -> tuple[int, ...]:
    samples_per_symbol, _, _, total_samples = _audio_layout(profile)
    if samples.shape != (total_samples,):
        raise AudioDecodeError("checksum audio has unexpected duration")
    windows = samples.reshape((-1, samples_per_symbol))
    centered = windows - np.mean(windows, axis=1, keepdims=True)
    time_indexes = np.arange(samples_per_symbol, dtype=np.float64) / profile.sample_rate

    def energy(frequency: int) -> np.ndarray:
        sine = np.sin(2.0 * math.pi * frequency * time_indexes)
        cosine = np.cos(2.0 * math.pi * frequency * time_indexes)
        sine_norm = float(np.dot(sine, sine))
        cosine_norm = float(np.dot(cosine, cosine))
        sine_dot = centered @ sine
        cosine_dot = centered @ cosine
        return (sine_dot * sine_dot) / sine_norm + (cosine_dot * cosine_dot) / cosine_norm

    space_energy = energy(profile.space_hz)
    mark_energy = energy(profile.mark_hz)
    strongest = np.maximum(space_energy, mark_energy)
    separation = np.abs(space_energy - mark_energy)
    valid = (strongest > 1.0e-6) & (separation > strongest * 0.10)
    symbols = np.full(len(windows), -1, dtype=np.int8)
    symbols[valid & (mark_energy > space_energy)] = 1
    symbols[valid & (space_energy > mark_energy)] = 0
    return tuple(int(value) for value in symbols)


def decode_checksum_audio(samples: Sequence[float] | np.ndarray, profile: MediaProfile) -> AudioRecord:
    """Recover CRC-valid BFSK copies and require one unambiguous 2-of-3 vote."""
    try:
        values = np.asarray(samples, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise AudioDecodeError("checksum audio samples must be numeric") from error
    if values.ndim != 1:
        raise AudioDecodeError("checksum audio samples must be one-dimensional")
    if not np.all(np.isfinite(values)):
        raise AudioDecodeError("checksum audio contains non-finite samples")
    symbols = _demodulate_symbols(values, profile)
    preamble_symbols = manchester_encode(AUDIO_PREAMBLE)
    record_symbol_count = AUDIO_RECORD_BYTES * 16
    valid_records: list[AudioRecord] = []
    cursor = 0
    last_start = len(symbols) - record_symbol_count
    while cursor <= last_start:
        if symbols[cursor:cursor + len(preamble_symbols)] != preamble_symbols:
            cursor += 1
            continue
        candidate = symbols[cursor:cursor + record_symbol_count]
        if -1 in candidate:
            cursor += 1
            continue
        try:
            record_bytes = manchester_decode(candidate)
            parsed = parse_audio_record(record_bytes)
        except AudioDecodeError:
            cursor += 1
            continue
        valid_records.append(parsed)
        cursor += record_symbol_count

    groups: dict[AudioRecord, int] = {}
    for record in valid_records:
        groups[record] = groups.get(record, 0) + 1
    if len(groups) > 1:
        raise AudioDecodeError("conflicting valid audio copies")
    if not groups:
        raise AudioDecodeError("expected at least two matching audio copies")
    record, count = next(iter(groups.items()))
    if count < profile.required_matching_copies:
        raise AudioDecodeError("expected at least two matching audio copies")
    return record
