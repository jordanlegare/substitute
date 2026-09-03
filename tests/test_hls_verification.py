from pathlib import Path
import shutil

import pytest

from ald_media_controller import (
    DEFAULT_MEDIA_PROFILE,
    CompiledRecipe,
    DependencyError,
    IntegrityError,
    PacketMediaArtifact,
    SignatureStatus,
    compile_recipe,
    load_recipe,
    mux_packet_mp4,
    package_hls,
    parse_local_playlist,
    probe_media_capabilities,
    sign_bundle_index,
    stage_packet_media,
    validate_recipe,
    verify_bundle_signature,
    verify_media_bundle,
    write_bundle_index,
    write_checksum_wav,
)


_TEST_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIDAYOmNdn8RZURscAMx3yLlZudv3epR/EGrgIUIz5qGC
-----END PRIVATE KEY-----
"""
_TEST_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA3adrEKJiQTNtvfeUoVSGQfmLlftJBfWiW3CCaDJskt8=
-----END PUBLIC KEY-----
"""
_WRONG_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAO25oV4W5CYsUCuVC/GZkUFiAREPSG8wOR+YNxjDKkBA=
-----END PUBLIC KEY-----
"""


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


def _copy_bundle(encoded_bundle, destination: Path) -> Path:
    _, manifest, _, _ = encoded_bundle
    shutil.copytree(manifest.parent, destination)
    return destination / manifest.name


def _write_test_keys(directory: Path) -> tuple[Path, Path, Path]:
    private_path = directory / "private.pem"
    public_path = directory / "public.pem"
    wrong_public_path = directory / "wrong-public.pem"
    private_path.write_text(_TEST_PRIVATE_KEY_PEM, encoding="ascii")
    public_path.write_text(_TEST_PUBLIC_KEY_PEM, encoding="ascii")
    wrong_public_path.write_text(_WRONG_PUBLIC_KEY_PEM, encoding="ascii")
    return private_path, public_path, wrong_public_path


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


@pytest.mark.requires_ffmpeg
def test_require_signature_rejects_unsigned(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "unsigned")

    with pytest.raises(IntegrityError, match="signature required"):
        verify_media_bundle(manifest, require_signature=True)


@pytest.mark.requires_ffmpeg
def test_signed_index_verifies_with_matching_key(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "signed")
    private_path, public_path, _ = _write_test_keys(tmp_path)

    signature = sign_bundle_index(manifest.parent / "bundle.json", private_path)
    assert signature.algorithm == "Ed25519"
    assert verify_bundle_signature(manifest.parent / "bundle.json", public_path) is SignatureStatus.VERIFIED

    result = verify_media_bundle(
        manifest,
        require_signature=True,
        trusted_public_key=public_path,
    )
    assert result.signature_status is SignatureStatus.VERIFIED


@pytest.mark.requires_ffmpeg
def test_signed_bundle_requires_trusted_public_key(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "signed-no-key")
    private_path, _, _ = _write_test_keys(tmp_path)
    sign_bundle_index(manifest.parent / "bundle.json", private_path)

    with pytest.raises(IntegrityError, match="trusted public key"):
        verify_media_bundle(manifest)


@pytest.mark.requires_ffmpeg
def test_signed_bundle_rejects_wrong_trusted_public_key(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "signed-wrong-key")
    private_path, _, wrong_public_path = _write_test_keys(tmp_path)
    sign_bundle_index(manifest.parent / "bundle.json", private_path)

    with pytest.raises(IntegrityError, match="fingerprint|signature"):
        verify_media_bundle(
            manifest,
            require_signature=True,
            trusted_public_key=wrong_public_path,
        )
