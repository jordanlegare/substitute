# ALD HLS/fMP4 Bundle Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package verified QR/BFSK packet artifacts as an HLS fMP4 bundle, recover and verify all media records, and make direct and media simulation modes equivalent.

**Architecture:** A local-only FFmpeg adapter muxes each three-second packet into aligned H.264/AAC media, segments the concatenated stream at packet boundaries, and writes a deterministic `bundle.json`. A strict decoder resolves only local relative segment paths, extracts each packet's first encoded frame and complete audio interval, validates frame/audio/index/hash agreement, then returns canonical packets to the existing simulator.

**Tech Stack:** Python 3.10+, FFmpeg/ffprobe, NumPy, Pillow, qrcode, zxing-cpp, optional cryptography Ed25519 verification, pytest

**Spec:** `docs/specs/2026-09-03-ald-media-controller-design.md`

## Global Constraints

- Complete the core compiler/simulator and QR/BFSK codec plans first.
- Use H.264 video at 1920x1080 with one forced keyframe per three-second packet interval.
- Use AAC-LC mono audio at 48 kHz and 128 kbit/s.
- Use one packet per HLS fMP4 segment plus one shared initialization segment.
- Verify the completed encoded media, not source PNG/WAV files, before publication.
- Require frame, audio, bundle index, sequence, timing, packet digest, and root hash agreement.
- Reject absolute paths, parent traversal, URLs, unsupported schemes, missing segments, extra indexed segments, and playlist discontinuities.
- Publish compile output atomically and never replace an existing output without `--overwrite`.
- Keep all media inputs local; no code path may initiate a network request.
- Checksums provide integrity, not identity; unsigned bundles remain permitted unless `--require-signature` is used.

---

## File Map

- Modify `pyproject.toml`: add optional Ed25519 support for signed bundle verification.
- Modify `ald_media_controller.py`: dependency probe, FFmpeg runner, muxer, playlist/index parser, bundle writer, media decoder/verifier, signature policy, and CLI commands.
- Create `tests/test_hls_integration.py`: dependency, compilation, extraction, tampering, path safety, signature policy, and direct/media equivalence tests.
- Modify `README.md`: media installation, commands, bundle layout, integrity/security boundary, and troubleshooting.

### Task 1: FFmpeg capability probe and controlled subprocess boundary

**Files:**
- Modify: `pyproject.toml`
- Modify: `ald_media_controller.py`
- Create: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: executable names and `Sequence[str]` arguments.
- Produces: `MediaCapabilities`, `probe_media_capabilities() -> MediaCapabilities`, and `run_media_tool(args: Sequence[str], timeout_seconds: float) -> CompletedProcess[str]`.

- [ ] **Step 1: Write failing dependency-boundary tests**

```python
def test_missing_ffmpeg_maps_to_dependency_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(DependencyError, match="ffmpeg"):
        probe_media_capabilities()


def test_media_runner_uses_argument_vector_not_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)) or fake_success())
    run_media_tool(["ffprobe", "-version"], timeout_seconds=5)
    assert calls[0][1]["shell"] is False
```

- [ ] **Step 2: Run dependency tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k 'missing_ffmpeg or argument_vector' -v`

Expected: tests fail because the media boundary is missing.

- [ ] **Step 3: Implement executable and codec capability checks**

Require both `ffmpeg` and `ffprobe`. Query `ffmpeg -hide_banner -encoders` and require an available H.264 encoder selected in priority order `libx264`, then `h264`. Require encoder `aac`, muxers `mp4` and `hls`, and demuxers `mov,mp4,m4a,3gp,3g2,mj2` and `hls`. Return the selected executable paths and video encoder in `MediaCapabilities`.

Define immutable `MediaCapabilities(ffmpeg: Path, ffprobe: Path, video_encoder: str, audio_encoder: str = "aac")`.

Register `requires_ffmpeg` under `[tool.pytest.ini_options].markers` with description `requires local FFmpeg H.264/AAC/fMP4/HLS capabilities`. The fixture skips only after `probe_media_capabilities()` raises `DependencyError`.

- [ ] **Step 4: Implement the subprocess policy**

Always pass an argument vector with `shell=False`, `check=False`, `text=True`, UTF-8 replacement decoding, captured stdout/stderr, an explicit timeout, and no inherited stdin. On non-zero return or timeout, raise `MediaBuildError` with the tool name, exit status, and final 20 stderr lines; never include environment variables in diagnostics.

- [ ] **Step 5: Run dependency tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k 'ffmpeg or media_runner or capabilities' -v`

Expected: all selected tests pass; capability-dependent tests skip only when the host lacks required codecs.

- [ ] **Step 6: Commit the media process boundary**

```bash
git add ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: probe local FFmpeg capabilities"
```

### Task 2: Mux packet artifacts and create aligned fMP4 HLS

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: `PacketMediaArtifact` tuple, staging directory, and `MediaCapabilities`.
- Produces: `mux_packet_mp4(artifact, destination, capabilities, profile) -> Path` and `package_hls(packet_mp4s, directory, capabilities, profile) -> Path`.

- [ ] **Step 1: Write failing media-profile tests**

```python
@pytest.mark.requires_ffmpeg
def test_packet_mp4_has_expected_streams(packet_artifact, tmp_path):
    mp4 = mux_packet_mp4(packet_artifact, tmp_path / "packet.mp4", probe_media_capabilities(), DEFAULT_MEDIA_PROFILE)
    probe = probe_json(mp4)
    assert [(s["codec_type"], s["codec_name"]) for s in probe["streams"]] == [("video", "h264"), ("audio", "aac")]
    assert float(probe["format"]["duration"]) == pytest.approx(3.0, abs=0.05)


@pytest.mark.requires_ffmpeg
def test_hls_has_one_segment_per_packet(staged_artifacts, tmp_path):
    manifest = build_test_hls(staged_artifacts, tmp_path)
    playlist = parse_local_playlist(manifest)
    assert len(playlist.segments) == len(staged_artifacts)
    assert all(s.duration == pytest.approx(3.0, abs=0.05) for s in playlist.segments)
```

- [ ] **Step 2: Run mux tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k 'packet_mp4 or one_segment' -v`

Expected: tests fail because mux/package functions are missing.

- [ ] **Step 3: Implement one three-second packet MP4**

Run FFmpeg with `-loop 1` for PNG, the three-second WAV as audio, `-t 3`, 30 fps, `-pix_fmt yuv420p`, selected H.264 encoder, `-g 90`, `-keyint_min 90`, `-sc_threshold 0`, AAC at 128 kbit/s, mono 48 kHz, `-shortest`, and fragmented-MP4 flags. Probe the output and reject any dimension, stream type, sample-rate, channel-count, codec, or duration mismatch.

- [ ] **Step 4: Concatenate and segment without re-encoding**

Write an FFmpeg concat-demuxer list using normalized local staging paths. Concatenate packet MP4s with `-c copy`, then create HLS with `-hls_time 3`, `-hls_segment_type fmp4`, `-hls_flags independent_segments`, `-hls_fmp4_init_filename init.mp4`, and segment pattern `packet-%06d.m4s`. Require `#EXT-X-MAP`, `#EXT-X-INDEPENDENT-SEGMENTS`, exact packet count, and `#EXT-X-ENDLIST`.

- [ ] **Step 5: Run mux tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k 'packet_mp4 or hls or segment' -v`

Expected: all selected FFmpeg-capable tests pass.

- [ ] **Step 6: Commit HLS packaging**

```bash
git add ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: package ALD packets as fMP4 HLS"
```

### Task 3: Local-only playlist parser and deterministic bundle index

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: manifest path, compiled recipe, selected media profile, and FFmpeg metadata.
- Produces: `LocalPlaylist`, `BundleIndex`, `parse_local_playlist(path: Path) -> LocalPlaylist`, and `write_bundle_index(...) -> Path`.

- [ ] **Step 1: Write failing path-safety and index tests**

```python
@pytest.mark.parametrize("uri", ["https://example.test/x.m4s", "file:///tmp/x", "/tmp/x.m4s", "../x.m4s"])
def test_playlist_rejects_nonlocal_or_escaping_uri(uri, tmp_path):
    manifest = write_manifest(tmp_path, segment_uri=uri)
    with pytest.raises(MediaVerificationError, match="local relative"):
        parse_local_playlist(manifest)


def test_bundle_index_records_ordered_digests(compiled_recipe, playlist, tmp_path):
    path = write_bundle_index(compiled_recipe, playlist, DEFAULT_MEDIA_PROFILE, tmp_path / "bundle.json")
    data = json.loads(path.read_text())
    assert [p["sequence"] for p in data["packets"]] == list(range(len(compiled_recipe.packets)))
    assert data["root_hash"] == compiled_recipe.root_hash.hex()
```

- [ ] **Step 2: Run parser/index tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k 'playlist_rejects or bundle_index' -v`

Expected: tests fail because parser and index are missing.

- [ ] **Step 3: Implement a strict media-playlist subset parser**

Accept only UTF-8 text beginning `#EXTM3U`, one `#EXT-X-MAP` URI, ordered `#EXTINF` plus URI pairs, optional version/target-duration/media-sequence/independent-segments tags, and one terminal `#EXT-X-ENDLIST`. Reject master-playlist variants, discontinuities, byte ranges, encryption keys, duplicate tags, unknown URI-bearing tags, empty segments, and durations outside 2.95–3.05 seconds. Resolve with `Path.resolve()` and require each target to remain under the bundle directory.

Define immutable `PlaylistSegment(uri: str, path: Path, duration: float, index: int)`, `LocalPlaylist(path: Path, initialization_path: Path, segments: tuple[PlaylistSegment, ...])`, `BundlePacket(sequence: int, segment: str, digest: bytes, duration_seconds: float)`, and `BundleIndex(protocol: str, manifest: str, initialization: str, packets: tuple[BundlePacket, ...], root_hash: bytes, signature: Mapping[str, str] | None)`.

- [ ] **Step 4: Write canonical `bundle.json`**

Include protocol `ALD-MEDIA/1`, media profile constants, FFmpeg version and selected encoders, manifest filename, initialization filename, ordered `{sequence, segment, digest, duration_seconds}` entries, root hash, signature status, and creation tool version. Serialize with the same finite, sorted, compact JSON policy used by packets.

- [ ] **Step 5: Run parser/index tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k 'playlist or bundle_index or path' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit local playlist and bundle metadata**

```bash
git add ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: index ALD HLS bundles safely"
```

### Task 4: Decode and verify the completed media bundle

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: local `stream.m3u8` path and optional trusted public key.
- Produces: `verify_media_bundle(manifest: Path, require_signature: bool = False, trusted_public_key: Path | None = None) -> VerifiedMediaRecipe`.

- [ ] **Step 1: Write failing end-to-end verification tests**

```python
@pytest.mark.requires_ffmpeg
def test_encoded_bundle_recovers_exact_packets(compiled_bundle):
    expected, manifest = compiled_bundle
    verified = verify_media_bundle(manifest)
    assert tuple(p.canonical_bytes for p in verified.packets) == tuple(p.canonical_bytes for p in expected.packets)
    assert verified.root_hash == expected.root_hash


@pytest.mark.requires_ffmpeg
def test_audio_hash_mismatch_fails_complete_bundle(compiled_bundle, tmp_path):
    _, manifest = copy_bundle(compiled_bundle, tmp_path)
    replace_segment_audio_hash(manifest.parent, sequence=1, digest=b"x" * 32)
    with pytest.raises(IntegrityError, match="frame/audio"):
        verify_media_bundle(manifest)
```

- [ ] **Step 2: Run verification tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k 'recovers_exact or audio_hash_mismatch' -v`

Expected: tests fail because bundle verification is missing.

- [ ] **Step 3: Extract one encoded frame and audio interval per segment**

For each ordered segment, construct a temporary playable input from the verified `init.mp4` plus segment bytes using local files only. Use FFmpeg to extract the first full-resolution PNG at the segment start and mono 48 kHz signed-16-bit WAV for the whole segment. Decode with the phase-two QR/BFSK functions. Reject extra video/audio streams, missing timestamps, duration mismatches, decode failures, and any segment whose extracted record sequence differs from its index.

Define immutable `VerifiedMediaRecipe(packets: tuple[HashedPacket, ...], root_hash: bytes, profile: MediaProfile, signature_status: SignatureStatus)`; instantiate it only after all segments and the final root pass.

- [ ] **Step 4: Rebuild and validate the complete hash chain**

Parse each canonical QR packet through the strict packet schema. Starting from 32 zero bytes, recompute each digest using the decoded canonical bytes. Require contiguous zero-based sequences; frame digest equals computed digest; audio digest/sequence equals frame; bundle entry equals both; final digest equals `bundle.json` root. Accumulate no executable packets until every segment passes.

- [ ] **Step 5: Run verification tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k 'verify or recover or mismatch or hash' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit media verification**

```bash
git add ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: verify executable ALD media bundles"
```

### Task 5: Optional Ed25519 signature policy

**Files:**
- Modify: `pyproject.toml`
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: canonical unsigned bundle bytes, optional PEM private key, optional PEM public key, and `require_signature`.
- Produces: `sign_bundle_index(...) -> BundleSignature` and `verify_bundle_signature(...) -> SignatureStatus`.

- [ ] **Step 1: Write failing signature-policy tests**

```python
def test_require_signature_rejects_unsigned(unsigned_bundle):
    with pytest.raises(IntegrityError, match="signature required"):
        verify_media_bundle(unsigned_bundle, require_signature=True)


def test_signed_index_verifies_with_matching_key(ed25519_keys, unsigned_bundle):
    private_path, public_path = ed25519_keys
    sign_existing_bundle(unsigned_bundle.parent / "bundle.json", private_path)
    result = verify_media_bundle(unsigned_bundle, require_signature=True, trusted_public_key=public_path)
    assert result.signature_status is SignatureStatus.VERIFIED
```

- [ ] **Step 2: Run signature tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k signature -v`

Expected: tests fail because signature policy is missing.

- [ ] **Step 3: Add and isolate the optional cryptography dependency**

Add an optional dependency group `signature = ["cryptography>=42,<47"]`. Import Ed25519 classes only inside signing functions. When signing or required verification is requested without the extra installed, raise `DependencyError` with `pip install -e '.[signature]'`.

- [ ] **Step 4: Implement unambiguous signed bytes**

Sign `b"ALD-BUNDLE-SIGNATURE\x00" + canonical_unsigned_bundle_bytes`, where the unsigned object omits its `signature` member. Store algorithm `Ed25519`, public-key SHA-256 fingerprint, and base64 signature. Verification requires the user-supplied trusted public key, matches its fingerprint, and verifies the signature over reconstructed unsigned bytes. Never trust a public key embedded in the bundle.

- [ ] **Step 5: Run signature tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k signature -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit optional signature verification**

```bash
git add pyproject.toml ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: verify signed ALD bundle indexes"
```

### Task 6: Compile, verify, and media-simulate CLI commands

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`

**Interfaces:**
- Consumes: recipe path, manifest path, output path, overwrite flag, seed, signing options, and trusted key.
- Produces: `compile`, `verify`, and `simulate-media` commands plus atomic bundle publication.

- [ ] **Step 1: Write failing CLI equivalence and overwrite tests**

```python
@pytest.mark.requires_ffmpeg
def test_direct_and_media_simulation_are_equivalent(sample_recipe_path, tmp_path):
    bundle, direct, media = tmp_path / "bundle", tmp_path / "direct", tmp_path / "media"
    assert main(["compile", str(sample_recipe_path), "--output", str(bundle)]) == 0
    assert main(["simulate", str(sample_recipe_path), "--seed", "42", "--output", str(direct)]) == 0
    assert main(["simulate-media", str(bundle / "stream.m3u8"), "--seed", "42", "--output", str(media)]) == 0
    assert (direct / "surface-final.json").read_bytes() == (media / "surface-final.json").read_bytes()
    assert (direct / "cycles.csv").read_bytes() == (media / "cycles.csv").read_bytes()


def test_compile_refuses_existing_output(sample_recipe_path, tmp_path):
    out = tmp_path / "exists"
    out.mkdir()
    assert main(["compile", str(sample_recipe_path), "--output", str(out)]) == ExitCode.OUTPUT
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python -m pytest tests/test_hls_integration.py -k 'simulation_are_equivalent or refuses_existing' -v`

Expected: tests fail because media CLI commands are missing.

- [ ] **Step 3: Implement atomic `compile`**

Compile the recipe, create a sibling temporary directory, stage PNG/WAV artifacts, mux and segment HLS, write `recipe.canonical.json` and `bundle.json`, optionally sign, remove intermediate PNG/WAV/packet MP4 files, then call `verify_media_bundle()` against the final temporary layout. Only after success, atomically rename it to the output. With `--overwrite`, rename the old output to a sibling backup, rename the verified build into place, then delete the backup; restore the backup if publication fails.

- [ ] **Step 4: Implement `verify` and `simulate-media`**

`verify` emits one JSON result containing protocol, packet count, root hash, profile, and signature status. `simulate-media` calls `verify_media_bundle()` first and passes the returned canonical packets/root hash into the same `SimulatedALDController` and report writer used by direct mode. Add `--require-signature` and `--trusted-public-key` to both commands; add `--signing-key` to `compile`.

- [ ] **Step 5: Run CLI equivalence tests and verify GREEN**

Run: `python -m pytest tests/test_hls_integration.py -k 'compile or verify or simulate_media or equivalent or overwrite' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit media CLI behavior**

```bash
git add ald_media_controller.py tests/test_hls_integration.py
git commit -m "feat: add executable-media ALD CLI"
```

### Task 7: Tamper matrix, compression report, documentation, and final acceptance

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_hls_integration.py`
- Modify: `tests/test_ald_media_controller.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: complete public CLI and sample recipe.
- Produces: corruption-regression coverage, procedural compression metrics, and final operating documentation.

- [ ] **Step 1: Add parameterized tamper tests**

```python
@pytest.mark.requires_ffmpeg
@pytest.mark.parametrize("mutation", [
    "video_qr", "audio_hash", "bundle_digest", "root_hash", "segment_order",
    "segment_missing", "segment_extra", "timestamp", "playlist_truncated",
])
def test_each_media_mutation_fails_closed(clean_bundle, mutation, tmp_path):
    manifest = mutate_bundle_copy(clean_bundle, mutation, tmp_path)
    with pytest.raises((MediaVerificationError, FrameDecodeError, AudioDecodeError, IntegrityError)):
        verify_media_bundle(manifest)
```

- [ ] **Step 2: Run the tamper matrix and verify RED for unhandled mutations**

Run: `python -m pytest tests/test_hls_integration.py::test_each_media_mutation_fails_closed -v`

Expected: at least one new mutation case fails until every validation gate is implemented.

- [ ] **Step 3: Implement every tamper-matrix validation gate**

Implement the following exact ownership rules:

- `video_qr`: `decode_instruction_frame()` requires one readable QR envelope, canonical reserialization, and a digest equal to the recomputed chain position.
- `audio_hash`: `decode_checksum_audio()` requires two matching CRC-valid copies; `verify_media_bundle()` then requires audio sequence/digest equal to the frame.
- `bundle_digest`: require each bundle packet digest equal to the frame, audio, and recomputed digest.
- `root_hash`: require the final recomputed digest equal to the bundle root.
- `segment_order`: require playlist order, bundle order, filenames, and decoded zero-based sequences to match exactly.
- `segment_missing`: require every playlist and bundle segment path to exist before starting extraction.
- `segment_extra`: require the set of `packet-*.m4s` files under the bundle root to equal the indexed set exactly.
- `timestamp`: use ffprobe to require each packet segment start PTS within 50 ms of its expected three-second boundary and duration within 2.95–3.05 seconds.
- `playlist_truncated`: require a single terminal `#EXT-X-ENDLIST` after the final URI and the bundle-declared packet count.

Re-run each parameter by its pytest node ID after adding its owning check. Do not weaken tests, infer missing metadata, or continue after any failed segment.

- [ ] **Step 4: Add procedural compression measurement**

Implement `measure_procedural_compression(compiled, simulation) -> CompressionReport` with canonical instruction bytes, naïvely expanded per-cycle JSONL bytes, estimated fully expanded site-event JSONL bytes, ratios, and separately reported HLS bundle bytes. Add a test that the 100-cycle example has one `ALD_CYCLE` packet and an expanded-instruction ratio greater than 10 while making no claim that MP4 is smaller than canonical JSON.

- [ ] **Step 5: Document the complete media workflow and security boundary**

Add commands:

```bash
python -m pip install -e '.[test,signature]'
ald-media-controller compile recipes/generic_al2o3.json --output build/al2o3
ald-media-controller verify build/al2o3/stream.m3u8
ald-media-controller simulate-media build/al2o3/stream.m3u8 --seed 42 --output build/media-run
python -m pytest -v
```

Document FFmpeg requirements, generated files, the three-second media versus simulated-time distinction, QR/BFSK/hash-chain roles, signature trust, local-path restrictions, expected failure exit codes, and the explicit prohibition on live hardware control.

- [ ] **Step 6: Run final verification**

Run: `python -m pytest -v`

Expected: zero failures; media tests may skip only when their marker reports unavailable FFmpeg capabilities.

Run: `python ald_media_controller.py compile recipes/generic_al2o3.json --output /tmp/ald-final-bundle`

Expected: exit 0 and a bundle containing `stream.m3u8`, `init.mp4`, packet `.m4s` files, `recipe.canonical.json`, and `bundle.json`, with no intermediate PNG/WAV/packet MP4 files.

Run: `python ald_media_controller.py verify /tmp/ald-final-bundle/stream.m3u8`

Expected: exit 0 and JSON containing the same root hash as direct `validate`.

Run: `python ald_media_controller.py simulate-media /tmp/ald-final-bundle/stream.m3u8 --seed 42 --output /tmp/ald-final-media-run`

Expected: exit 0 and byte-identical `surface-final.json` and `cycles.csv` compared with a direct simulation using seed 42.

- [ ] **Step 7: Commit the completed simulator**

```bash
git add ald_media_controller.py tests/test_hls_integration.py tests/test_ald_media_controller.py README.md
git commit -m "test: verify ALD media integrity end to end"
```
