import dataclasses
import hashlib

import numpy as np
from PIL import Image
import pytest
import qrcode
from qrcode.constants import ERROR_CORRECT_Q

from ald_media_controller import (
    AUDIO_PREAMBLE,
    AUDIO_RECORD_BYTES,
    AudioDecodeError,
    AudioRecord,
    DEFAULT_MEDIA_PROFILE,
    FrameDecodeError,
    build_audio_record,
    compile_recipe,
    decode_checksum_audio,
    decode_instruction_frame,
    decode_qr_payload,
    encode_checksum_audio,
    encode_qr_payload,
    manchester_decode,
    manchester_encode,
    parse_audio_record,
    read_checksum_wav,
    render_instruction_frame,
    stage_packet_media,
    validate_recipe,
    write_checksum_wav,
)


@pytest.fixture
def compiled_recipe():
    raw = {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": "media-codec-test",
        "metadata": {"material": "generic"},
        "precursors": {
            "A": {"label": "A"},
            "B": {"label": "B"},
        },
        "initial_conditions": {
            "temperature_c": 25.0,
            "pressure_pa": 101325.0,
        },
        "limits": {
            "min_purge_ms": 1000,
            "max_temperature_c": 300.0,
            "max_pressure_pa": 200000.0,
            "max_cycles": 10,
            "max_runtime_ms": 600000,
            "max_residual_fraction": 0.01,
            "max_packet_bytes": 800,
        },
        "surface": {
            "model_version": "site-binomial/1",
            "regions": 1,
        },
        "instructions": [
            {"opcode": "CONFIGURE", "arguments": {}},
            {
                "opcode": "SET_TEMPERATURE",
                "arguments": {
                    "target_c": 150.0,
                    "ramp_c_per_min": 20.0,
                    "tolerance_c": 1.0,
                },
            },
            {
                "opcode": "EVACUATE",
                "arguments": {"target_pa": 100.0, "timeout_ms": 120000},
            },
            {"opcode": "STABILIZE", "arguments": {"duration_ms": 1000}},
            {
                "opcode": "ALD_CYCLE",
                "arguments": {
                    "precursor_a": "A",
                    "pulse_a_ms": 100,
                    "flow_a_sccm": 10.0,
                    "purge_a_ms": 5000,
                    "precursor_b": "B",
                    "pulse_b_ms": 100,
                    "flow_b_sccm": 10.0,
                    "purge_b_ms": 5000,
                    "repeat": 1,
                },
            },
            {
                "opcode": "SHUTDOWN",
                "arguments": {
                    "heater_ramp_c_per_min": 20.0,
                    "vent_target_pa": 101325.0,
                },
            },
        ],
    }
    return compile_recipe(validate_recipe(raw))


def _make_ambiguous_two_code_frame(items, path):
    canvas = Image.new("RGB", (DEFAULT_MEDIA_PROFILE.width, DEFAULT_MEDIA_PROFILE.height), "white")
    x = 24
    for item in items:
        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_Q,
            box_size=DEFAULT_MEDIA_PROFILE.qr_box_size,
            border=DEFAULT_MEDIA_PROFILE.qr_border_modules,
        )
        qr.add_data(encode_qr_payload(item), optimize=0)
        qr.make(fit=True)
        symbol = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        canvas.paste(symbol, (x, 24))
        x += symbol.width + 48
    assert x <= DEFAULT_MEDIA_PROFILE.width
    canvas.save(path, format="PNG", optimize=False, compress_level=9)
    return path


def _corrupt_audio_copy(samples, copy_index):
    profile = DEFAULT_MEDIA_PROFILE
    samples_per_symbol = profile.sample_rate // profile.symbol_rate
    guard = profile.sample_rate // 10
    record_samples = AUDIO_RECORD_BYTES * 8 * 2 * samples_per_symbol
    start = guard + copy_index * (record_samples + guard)
    end = start + record_samples
    corrupted = np.array(samples, dtype=np.float64, copy=True)
    corrupted[start:end] = 0.0
    return corrupted


def test_qr_payload_round_trip(compiled_recipe):
    item = compiled_recipe.packets[0]
    decoded = decode_qr_payload(encode_qr_payload(item))
    assert decoded.canonical_bytes == item.canonical_bytes
    assert decoded.digest == item.digest
    assert decoded.sequence == item.packet.sequence


def test_qr_payload_rejects_oversized_packet(compiled_recipe):
    item = dataclasses.replace(compiled_recipe.packets[0], canonical_bytes=b"x" * 801)
    with pytest.raises(FrameDecodeError, match="800"):
        encode_qr_payload(item)


def test_qr_payload_rejects_trailing_bytes(compiled_recipe):
    encoded = encode_qr_payload(compiled_recipe.packets[0])
    with pytest.raises(FrameDecodeError, match="length"):
        decode_qr_payload(encoded + b"x")


def test_qr_payload_rejects_noncanonical_packet_bytes(compiled_recipe):
    item = compiled_recipe.packets[0]
    noncanonical = item.canonical_bytes.replace(b'"arguments":{}', b'"arguments": { }')
    assert noncanonical != item.canonical_bytes
    forged = dataclasses.replace(item, canonical_bytes=noncanonical)
    with pytest.raises(FrameDecodeError, match="canonical"):
        decode_qr_payload(encode_qr_payload(forged))


def test_rendered_frame_decodes_exact_packet(compiled_recipe, tmp_path):
    item = compiled_recipe.packets[0]
    path = render_instruction_frame(item, DEFAULT_MEDIA_PROFILE, tmp_path / "frame.png")
    decoded = decode_instruction_frame(path, DEFAULT_MEDIA_PROFILE)
    assert path.is_file()
    assert Image.open(path).size == (1920, 1080)
    assert decoded.canonical_bytes == item.canonical_bytes
    assert decoded.digest == item.digest
    assert decoded.sequence == item.packet.sequence


def test_frame_with_two_qr_codes_is_rejected(compiled_recipe, tmp_path):
    path = _make_ambiguous_two_code_frame(compiled_recipe.packets[:2], tmp_path / "ambiguous.png")
    with pytest.raises(FrameDecodeError, match="exactly one"):
        decode_instruction_frame(path, DEFAULT_MEDIA_PROFILE)


def test_frame_with_wrong_dimensions_is_rejected(compiled_recipe, tmp_path):
    path = render_instruction_frame(compiled_recipe.packets[0], DEFAULT_MEDIA_PROFILE, tmp_path / "frame.png")
    image = Image.open(path).crop((0, 0, 1280, 720))
    image.save(path, format="PNG")
    with pytest.raises(FrameDecodeError, match="dimensions"):
        decode_instruction_frame(path, DEFAULT_MEDIA_PROFILE)


def test_audio_record_layout_and_crc():
    digest = bytes(range(32))
    record = build_audio_record(0x01020304, digest)
    assert len(record) == 49
    assert record[:8] == AUDIO_PREAMBLE == b"\xAA" * 8
    assert record[8] == 1
    assert record[9:13] == b"\x01\x02\x03\x04"
    assert parse_audio_record(record) == AudioRecord(1, 0x01020304, digest)


def test_audio_record_rejects_crc_corruption():
    record = bytearray(build_audio_record(7, b"d" * 32))
    record[20] ^= 0x01
    with pytest.raises(AudioDecodeError, match="CRC"):
        parse_audio_record(bytes(record))


def test_audio_record_rejects_trailing_bytes():
    record = build_audio_record(7, b"d" * 32)
    with pytest.raises(AudioDecodeError, match="49"):
        parse_audio_record(record + b"x")


def test_manchester_round_trip():
    data = b"\x00\xA5\xFF"
    symbols = manchester_encode(data)
    assert len(symbols) == len(data) * 16
    assert manchester_decode(symbols) == data


def test_manchester_rejects_invalid_pair():
    with pytest.raises(AudioDecodeError, match="Manchester"):
        manchester_decode([0, 0])


def test_bfsk_wav_round_trip(tmp_path):
    digest = hashlib.sha256(b"packet").digest()
    path = write_checksum_wav(7, digest, DEFAULT_MEDIA_PROFILE, tmp_path / "checksum.wav")
    samples = read_checksum_wav(path, DEFAULT_MEDIA_PROFILE)
    decoded = decode_checksum_audio(samples, DEFAULT_MEDIA_PROFILE)
    assert len(samples) == 144000
    assert decoded == AudioRecord(1, 7, digest)


def test_bfsk_waveform_is_three_seconds_and_bounded():
    samples = encode_checksum_audio(7, b"d" * 32, DEFAULT_MEDIA_PROFILE)
    assert samples.dtype == np.float64
    assert samples.shape == (144000,)
    assert np.max(np.abs(samples)) <= 0.7000001
    assert np.max(np.abs(samples)) >= 0.69


def test_one_corrupt_copy_still_decodes_but_two_do_not():
    samples = encode_checksum_audio(7, b"d" * 32, DEFAULT_MEDIA_PROFILE)
    one_bad = _corrupt_audio_copy(samples, copy_index=0)
    assert decode_checksum_audio(one_bad, DEFAULT_MEDIA_PROFILE).sequence == 7
    two_bad = _corrupt_audio_copy(one_bad, copy_index=1)
    with pytest.raises(AudioDecodeError, match="two matching"):
        decode_checksum_audio(two_bad, DEFAULT_MEDIA_PROFILE)


def test_staged_artifacts_round_trip_all_packets(compiled_recipe, tmp_path):
    directory = tmp_path / "packet-media"
    artifacts = stage_packet_media(compiled_recipe, directory, DEFAULT_MEDIA_PROFILE)

    assert len(artifacts) == len(compiled_recipe.packets)
    assert len(list(directory.iterdir())) == 2 * len(compiled_recipe.packets)

    for expected, artifact in zip(compiled_recipe.packets, artifacts, strict=True):
        assert artifact.sequence == expected.packet.sequence
        assert artifact.digest == expected.digest
        assert artifact.frame_path.name == f"packet-{expected.packet.sequence:06d}.png"
        assert artifact.audio_path.name == f"packet-{expected.packet.sequence:06d}.wav"

        frame = decode_instruction_frame(artifact.frame_path, DEFAULT_MEDIA_PROFILE)
        audio = decode_checksum_audio(read_checksum_wav(artifact.audio_path, DEFAULT_MEDIA_PROFILE), DEFAULT_MEDIA_PROFILE)
        assert (frame.sequence, frame.digest, frame.canonical_bytes) == (
            expected.packet.sequence,
            expected.digest,
            expected.canonical_bytes,
        )
        assert (audio.sequence, audio.digest) == (expected.packet.sequence, expected.digest)
