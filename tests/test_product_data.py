from pathlib import Path

import ald_hardened_core as core
import ald_media_codecs as media
import ald_product_data as product_data


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compiled_recipe() -> core.CompiledRecipe:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    return core.compile_recipe(recipe)


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
