from pathlib import Path

import pytest

from ald_media_controller import (
    DEFAULT_MEDIA_PROFILE,
    CompiledRecipe,
    DependencyError,
    IntegrityError,
    PacketMediaArtifact,
    compile_recipe,
    load_recipe,
    mux_packet_mp4,
    package_hls,
    parse_local_playlist,
    probe_media_capabilities,
    stage_packet_media,
    validate_recipe,
    verify_media_bundle,
    write_bundle_index,
    write_checksum_wav,
)


@pytest.fixture(scope="module")
def media_capabilities():
    try:
        return probe_media_capabilities()
    except DependencyError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def compiled_two_packets():
    full = compile_recipe(validate_recipe(load_recipe(Path("recipes/generic_al2o3.json"))))
    packets = full.packets[:2]
    return CompiledRecipe(recipe=full.recipe, packets=packets, root_hash=packets[-1].digest)


@pytest.fixture(scope="module")
def encoded_bundle(compiled_two_packets, media_capabilities, tmp_path_factory):
    root = tmp_path_factory.mktemp("verified-hls")
    artifacts = stage_packet_media(
        compiled_two_packets,
        root / "source-media",
        DEFAULT_MEDIA_PROFILE,
    )
    mp4_dir = root / "packet-mp4s"
    mp4_dir.mkdir()
    packet_mp4s = tuple(
        mux_packet_mp4(
            artifact,
            mp4_dir / f"packet-{artifact.sequence:06d}.mp4",
            media_capabilities,
            DEFAULT_MEDIA_PROFILE,
        )
        for artifact in artifacts
    )
    manifest = package_hls(
        packet_mp4s,
        root / "bundle",
        media_capabilities,
        DEFAULT_MEDIA_PROFILE,
    )
    playlist = parse_local_playlist(manifest)
    write_bundle_index(
        compiled_two_packets,
        playlist,
        DEFAULT_MEDIA_PROFILE,
        manifest.parent / "bundle.json",
        ffmpeg_version="test-ffmpeg",
        video_encoder=media_capabilities.video_encoder,
        audio_encoder=media_capabilities.audio_encoder,
    )
    return compiled_two_packets, manifest, artifacts, packet_mp4s


@pytest.mark.requires_ffmpeg
def test_encoded_bundle_recovers_exact_packets(encoded_bundle):
    expected, manifest, _, _ = encoded_bundle

    verified = verify_media_bundle(manifest)

    assert tuple(packet.canonical_bytes for packet in verified.packets) == tuple(
        packet.canonical_bytes for packet in expected.packets
    )
    assert tuple(packet.digest for packet in verified.packets) == tuple(
        packet.digest for packet in expected.packets
    )
    assert verified.root_hash == expected.root_hash
    assert verified.profile == DEFAULT_MEDIA_PROFILE


@pytest.mark.requires_ffmpeg
def test_audio_hash_mismatch_fails_complete_bundle(
    encoded_bundle,
    media_capabilities,
    tmp_path,
):
    expected, _, artifacts, packet_mp4s = encoded_bundle
    wrong_audio = tmp_path / "wrong.wav"
    write_checksum_wav(
        artifacts[1].sequence,
        b"x" * 32,
        DEFAULT_MEDIA_PROFILE,
        wrong_audio,
    )
    wrong_artifact = PacketMediaArtifact(
        sequence=artifacts[1].sequence,
        frame_path=artifacts[1].frame_path,
        audio_path=wrong_audio,
        digest=artifacts[1].digest,
    )
    wrong_mp4 = mux_packet_mp4(
        wrong_artifact,
        tmp_path / "packet-wrong.mp4",
        media_capabilities,
        DEFAULT_MEDIA_PROFILE,
    )
    manifest = package_hls(
        (packet_mp4s[0], wrong_mp4),
        tmp_path / "bundle",
        media_capabilities,
        DEFAULT_MEDIA_PROFILE,
    )
    playlist = parse_local_playlist(manifest)
    write_bundle_index(
        expected,
        playlist,
        DEFAULT_MEDIA_PROFILE,
        manifest.parent / "bundle.json",
        ffmpeg_version="test-ffmpeg",
        video_encoder=media_capabilities.video_encoder,
        audio_encoder=media_capabilities.audio_encoder,
    )

    with pytest.raises(IntegrityError, match="frame/audio"):
        verify_media_bundle(manifest)
