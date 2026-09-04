from pathlib import Path
import wave

from PIL import Image
import pytest

import ald_hardened_core as core
import ald_hls_integration as hls
import ald_media_codecs as media
import ald_product_data as product_data
import ald_product_mp4 as product_mp4
import ald_product_render as product_render


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compiled_and_simulation(seed: int = 42) -> tuple[core.CompiledRecipe, core.SimulationResult]:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    compiled = core.compile_recipe(recipe)
    simulation = core.SimulatedALDController().execute(compiled, seed)
    assert simulation.fault is None
    return compiled, simulation


def test_product_track_staging_writes_one_full_hd_frame_per_packet(tmp_path):
    compiled, simulation = compiled_and_simulation()

    sources = product_render.stage_product_tracks(
        compiled,
        simulation,
        tmp_path / "tracks",
        media.DEFAULT_MEDIA_PROFILE,
    )

    assert len(sources.frame_paths) == len(compiled.packets)
    assert sources.duration_seconds == len(compiled.packets) * 3.0
    for sequence, path in enumerate(sources.frame_paths):
        assert path.name == f"frame-{sequence:06d}.png"
        with Image.open(path) as image:
            assert image.size == (1920, 1080)
            assert image.mode == "RGB"


def test_product_track_staging_has_no_qr_renderer_dependency(tmp_path, monkeypatch):
    compiled, simulation = compiled_and_simulation()

    def reject_qr(*args, **kwargs):
        raise AssertionError("QR renderer must not be used by product staging")

    monkeypatch.setattr(media, "render_instruction_frame", reject_qr)

    sources = product_render.stage_product_tracks(
        compiled,
        simulation,
        tmp_path / "tracks",
        media.DEFAULT_MEDIA_PROFILE,
    )

    assert len(sources.frame_paths) == len(compiled.packets)


def test_product_track_staging_writes_full_bfsk_wav_and_guarded_data(tmp_path):
    compiled, simulation = compiled_and_simulation()
    profile = media.DEFAULT_MEDIA_PROFILE

    sources = product_render.stage_product_tracks(
        compiled,
        simulation,
        tmp_path / "tracks",
        profile,
    )

    with wave.open(str(sources.audio_path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == profile.sample_rate
        assert audio.getnframes() == len(compiled.packets) * int(
            profile.sample_rate * profile.interval_seconds
        )

    raw = sources.data_path.read_bytes()
    assert len(raw) == (len(compiled.packets) + 1) * product_data.DATA_SLOT_BYTES
    for sequence, item in enumerate(compiled.packets):
        start = sequence * product_data.DATA_SLOT_BYTES
        record = product_data.decode_product_slot(
            raw[start : start + product_data.DATA_SLOT_BYTES]
        )
        assert record.sequence == sequence
        assert record.canonical_bytes == item.canonical_bytes
        assert record.digest == item.digest
    assert raw[-product_data.DATA_SLOT_BYTES :] == bytes(product_data.DATA_SLOT_BYTES)


@pytest.mark.requires_ffmpeg
def test_product_mp4_capability_probe_round_trips_gpmd_data_track():
    capabilities = hls.probe_media_capabilities()

    product_mp4.probe_product_mp4_capabilities(capabilities)


@pytest.mark.requires_ffmpeg
def test_majorana_product_mp4_mux_round_trips_authoritative_slots(tmp_path):
    compiled, simulation = compiled_and_simulation()
    profile = media.DEFAULT_MEDIA_PROFILE
    capabilities = hls.probe_media_capabilities()
    product_mp4.probe_product_mp4_capabilities(capabilities)
    sources = product_render.stage_product_tracks(
        compiled,
        simulation,
        tmp_path / "tracks",
        profile,
    )
    product_path = product_mp4.mux_product_mp4(
        sources,
        tmp_path / "product.mp4",
        capabilities,
        profile,
    )

    probe = product_mp4.probe_product_mp4(
        product_path,
        capabilities,
        packet_count=len(compiled.packets),
        interval_seconds=profile.interval_seconds,
    )
    assert len(probe.data_packets) == len(compiled.packets)

    extracted_path = product_mp4.extract_product_data(
        product_path,
        tmp_path / "product-data.bin",
        capabilities,
    )
    raw = extracted_path.read_bytes()
    assert len(raw) == len(compiled.packets) * product_data.DATA_SLOT_BYTES
    for sequence, item in enumerate(compiled.packets):
        start = sequence * product_data.DATA_SLOT_BYTES
        record = product_data.decode_product_slot(
            raw[start : start + product_data.DATA_SLOT_BYTES]
        )
        assert record.sequence == sequence
        assert record.pts_ms == sequence * 3000
        assert record.duration_ms == 3000
        assert record.canonical_bytes == item.canonical_bytes
        assert record.digest == item.digest
