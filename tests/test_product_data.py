from pathlib import Path

import ald_hardened_core as core
import ald_media_codecs as media


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compiled_recipe() -> core.CompiledRecipe:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    return core.compile_recipe(recipe)


def test_public_packet_helpers_accept_compiled_packet():
    item = compiled_recipe().packets[0]

    media.validate_hashed_packet(item)
    packet = media.decode_canonical_packet_bytes(item.canonical_bytes)

    assert core.canonical_packet_bytes(packet) == item.canonical_bytes
