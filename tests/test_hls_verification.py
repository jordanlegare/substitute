from copy import deepcopy
from pathlib import Path
import hashlib
import json
import shutil

import pytest

import ald_hls_verify as verify_module
from ald_media_controller import (
    DEFAULT_MEDIA_PROFILE,
    CompiledRecipe,
    DependencyError,
    IntegrityError,
    OutputError,
    PacketMediaArtifact,
    SignatureStatus,
    compile_recipe,
    load_recipe,
    measure_hls_bundle_bytes,
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


def _write_canonical_recipe(directory: Path) -> Path:
    source = json.loads(Path("recipes/generic_al2o3.json").read_text(encoding="utf-8"))
    path = directory / "recipe.canonical.json"
    path.write_text(
        json.dumps(
            source,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path


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
    recipe_path = _write_canonical_recipe(manifest.parent)
    write_bundle_index(
        compiled_two_packets,
        playlist,
        DEFAULT_MEDIA_PROFILE,
        manifest.parent / "bundle.json",
        recipe_path=recipe_path,
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
    assert verified.recipe_bytes == (manifest.parent / "recipe.canonical.json").read_bytes()


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
    recipe_path = _write_canonical_recipe(manifest.parent)
    write_bundle_index(
        expected,
        playlist,
        DEFAULT_MEDIA_PROFILE,
        manifest.parent / "bundle.json",
        recipe_path=recipe_path,
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
def test_signed_verification_authenticates_exact_index_bytes(encoded_bundle, tmp_path, monkeypatch):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "signed-index-race")
    private_path, public_path, _ = _write_test_keys(tmp_path)
    index_path = manifest.parent / "bundle.json"
    recipe_path = manifest.parent / "recipe.canonical.json"

    sign_bundle_index(index_path, private_path)
    valid_signed_index = index_path.read_bytes()

    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["surface"]["sites_per_region"] += 1
    malicious_recipe = (
        json.dumps(
            recipe,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    recipe_path.write_bytes(malicious_recipe)

    attacker_index = json.loads(valid_signed_index.decode("utf-8"))
    attacker_index["recipe"]["sha256"] = hashlib.sha256(malicious_recipe).hexdigest()
    attacker_bytes = (
        json.dumps(
            attacker_index,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    index_path.write_bytes(attacker_bytes)

    original_verify = verify_module.verify_bundle_signature

    def race_signature_verification(path, trusted_key):
        target = Path(path)
        target.write_bytes(valid_signed_index)
        try:
            return original_verify(target, trusted_key)
        finally:
            target.write_bytes(attacker_bytes)

    monkeypatch.setattr(verify_module, "verify_bundle_signature", race_signature_verification)

    with pytest.raises(IntegrityError, match="signature"):
        verify_media_bundle(
            manifest,
            require_signature=True,
            trusted_public_key=public_path,
        )


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


@pytest.mark.requires_ffmpeg
def test_extra_unindexed_segment_fails_closed(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "extra-segment")
    shutil.copy2(
        manifest.parent / "packet-000000.m4s",
        manifest.parent / "packet-999999.m4s",
    )

    with pytest.raises(IntegrityError, match="extra|segment set"):
        verify_media_bundle(manifest)


@pytest.mark.requires_ffmpeg
def test_segment_timeline_drift_fails_closed(encoded_bundle, monkeypatch):
    _, manifest, _, _ = encoded_bundle
    original_probe = verify_module.probe_media_json

    def drifted_probe(path, capabilities):
        probe = deepcopy(original_probe(path, capabilities))
        if Path(path).name == "segment-000001.mp4":
            for stream in probe["streams"]:
                if stream.get("codec_type") in {"video", "audio"}:
                    stream["start_time"] = "9.000000"
        return probe

    monkeypatch.setattr(verify_module, "probe_media_json", drifted_probe)

    with pytest.raises(IntegrityError, match="timestamp|timeline"):
        verify_media_bundle(manifest)


@pytest.mark.requires_ffmpeg
def test_hls_bundle_byte_measurement_counts_regular_files(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "measured")
    expected = sum(
        path.stat().st_size
        for path in manifest.parent.iterdir()
        if path.is_file() and not path.is_symlink()
    )

    assert measure_hls_bundle_bytes(manifest.parent) == expected


@pytest.mark.requires_ffmpeg
def test_hls_bundle_byte_measurement_rejects_symlinks(encoded_bundle, tmp_path):
    manifest = _copy_bundle(encoded_bundle, tmp_path / "linked")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (manifest.parent / "outside-link.bin").symlink_to(outside)

    with pytest.raises(OutputError, match="symlink"):
        measure_hls_bundle_bytes(manifest.parent)
