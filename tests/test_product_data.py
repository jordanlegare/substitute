from pathlib import Path
import zlib

import pytest

import ald_hardened_core as core
import ald_media_codecs as media
import ald_product_data as product_data


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")
_HEADER_BYTES = 55
_SEQUENCE_OFFSET = 5
_DURATION_OFFSET = 17
_PAYLOAD_LENGTH_OFFSET = 21
_DIGEST_OFFSET = 23
_PAYLOAD_OFFSET = 55


def compiled_recipe() -> core.CompiledRecipe:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    return core.compile_recipe(recipe)


def _with_recomputed_crc(raw: bytearray) -> bytes:
    payload_length = int.from_bytes(
        raw[_PAYLOAD_LENGTH_OFFSET : _PAYLOAD_LENGTH_OFFSET + 2], "big"
    )
    crc_offset = _HEADER_BYTES + payload_length
    raw[crc_offset : crc_offset + 4] = (
        zlib.crc32(raw[:crc_offset]) & 0xFFFFFFFF
    ).to_bytes(4, "big")
    return bytes(raw)


def test_public_packet_helpers_accept_compiled_packet():
    item = compiled_recipe().packets[0]

    media.validate_hashed_packet(item)
    packet = media.decode_canonical_packet_bytes(item.canonical_bytes)

    assert core.canonical_packet_bytes(packet) == item.canonical_bytes


def test_product_slot_is_fixed_size_and_round_trips_packet():
    item = compiled_recipe().packets[0]

    slot = product_data.encode_product_slot(item, pts_ms=0, duration_ms=3000)
    record = product_data.decode_product_slot(slot)

    assert len(slot) == 1024
    assert record.sequence == 0
    assert record.pts_ms == 0
    assert record.duration_ms == 3000
    assert record.canonical_bytes == item.canonical_bytes
    assert record.digest == item.digest
    assert core.canonical_packet_bytes(record.packet) == item.canonical_bytes


def test_product_slots_have_contiguous_three_second_timestamps():
    compiled = compiled_recipe()

    slots = product_data.build_product_slots(compiled, interval_ms=3000)

    assert len(slots) == len(compiled.packets)
    for sequence, (slot, item) in enumerate(zip(slots, compiled.packets, strict=True)):
        record = product_data.decode_product_slot(slot)
        assert record.sequence == sequence
        assert record.pts_ms == sequence * 3000
        assert record.duration_ms == 3000
        assert record.canonical_bytes == item.canonical_bytes
        assert record.digest == item.digest


def test_product_slot_rejects_wrong_magic():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[0] ^= 0x01
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_unknown_version():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[4] = 2
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_envelope_sequence_mismatch():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[_SEQUENCE_OFFSET : _SEQUENCE_OFFSET + 4] = (1).to_bytes(4, "big")
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(_with_recomputed_crc(raw))


def test_product_slot_rejects_zero_duration():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[_DURATION_OFFSET : _DURATION_OFFSET + 4] = bytes(4)
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_oversized_declared_payload():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[_PAYLOAD_LENGTH_OFFSET : _PAYLOAD_LENGTH_OFFSET + 2] = (801).to_bytes(2, "big")
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_corrupted_payload():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[_PAYLOAD_OFFSET] ^= 0x01
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_corrupted_digest():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[_DIGEST_OFFSET] ^= 0x01
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_crc_failure():
    slot = product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000)
    raw = bytearray(slot)
    payload_length = int.from_bytes(
        raw[_PAYLOAD_LENGTH_OFFSET : _PAYLOAD_LENGTH_OFFSET + 2], "big"
    )
    crc_offset = _HEADER_BYTES + payload_length
    raw[crc_offset] ^= 0x01
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_nonzero_padding():
    raw = bytearray(product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000))
    raw[-1] = 1
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(bytes(raw))


def test_product_slot_rejects_truncation_and_trailing_bytes():
    slot = product_data.encode_product_slot(compiled_recipe().packets[0], pts_ms=0, duration_ms=3000)
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(slot[:-1])
    with pytest.raises(core.ALDError):
        product_data.decode_product_slot(slot + b"\x00")


def test_product_slot_stream_writes_real_slots_plus_zero_guard(tmp_path):
    compiled = compiled_recipe()
    destination = tmp_path / "product-data.bin"

    returned = product_data.write_product_slot_stream(
        compiled,
        destination,
        interval_ms=3000,
    )
    raw = returned.read_bytes()

    assert returned == destination
    assert len(raw) == (len(compiled.packets) + 1) * product_data.DATA_SLOT_BYTES
    for sequence in range(len(compiled.packets)):
        start = sequence * product_data.DATA_SLOT_BYTES
        record = product_data.decode_product_slot(
            raw[start : start + product_data.DATA_SLOT_BYTES]
        )
        assert record.sequence == sequence
        assert record.pts_ms == sequence * 3000
    assert raw[-product_data.DATA_SLOT_BYTES :] == bytes(product_data.DATA_SLOT_BYTES)


def test_product_slot_stream_can_omit_guard(tmp_path):
    compiled = compiled_recipe()
    destination = tmp_path / "product-data-no-guard.bin"

    product_data.write_product_slot_stream(
        compiled,
        destination,
        include_guard=False,
    )

    assert destination.stat().st_size == len(compiled.packets) * product_data.DATA_SLOT_BYTES
