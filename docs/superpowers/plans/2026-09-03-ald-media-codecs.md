# ALD QR Frame and BFSK Audio Codecs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encode every verified ALD packet into an executable QR video frame and a synchronized, redundant BFSK checksum waveform, then recover both records deterministically.

**Architecture:** Extend the standalone module with a fixed `MediaProfile`, pure QR payload/frame functions, pure BFSK framing/signal functions, and a `PacketMediaArtifact` staging interface. This phase verifies PNG/WAV artifacts without HLS or FFmpeg; the integration plan later muxes these tested artifacts.

**Tech Stack:** Python 3.10+, NumPy, Pillow, qrcode, zxing-cpp, wave, pytest

**Spec:** `docs/specs/2026-09-03-ald-media-controller-design.md`

## Global Constraints

- Complete the core compiler/simulator plan first.
- Limit canonical packet bytes to 800 bytes.
- Use QR error-correction level Q, a 1920x1080 RGB frame, and at least eight rendered pixels per QR module.
- Use a three-second media interval independent of simulated process duration.
- Use 1200 Hz and 2400 Hz BFSK carriers, 1200 symbols/second, Manchester coding, mono 48 kHz audio, and three record copies.
- Encode a 64-bit alternating preamble, 8-bit protocol version, 32-bit big-endian sequence, 256-bit packet hash, and 32-bit CRC.
- Require at least two matching, valid audio copies.
- Decode executable data from QR bytes, never OCR or human-readable text.
- Keep all codec functions local and deterministic; no network or hardware access.

---

## File Map

- Modify `pyproject.toml`: add bounded image and QR dependencies.
- Modify `ald_media_controller.py`: profile, QR payload/frame codec, BFSK codec, and artifact staging.
- Create `tests/test_media_codecs.py`: QR, frame, binary record, waveform, corruption, and staging tests.

### Task 1: Media profile and QR binary payload

**Files:**
- Modify: `pyproject.toml`
- Modify: `ald_media_controller.py`
- Create: `tests/test_media_codecs.py`

**Interfaces:**
- Consumes: `HashedPacket`.
- Produces: `MediaProfile`, `encode_qr_payload(packet: HashedPacket) -> bytes`, and `decode_qr_payload(data: bytes) -> DecodedFrameRecord`.

- [ ] **Step 1: Write failing QR payload tests**

```python
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
```

- [ ] **Step 2: Run payload tests and verify RED**

Run: `python -m pytest tests/test_media_codecs.py -k qr_payload -v`

Expected: import fails because codec interfaces are absent.

- [ ] **Step 3: Add dependencies and the immutable media profile**

Add runtime dependencies `Pillow>=10,<13`, `qrcode>=7.4,<9`, and `zxing-cpp>=2.2,<3`.

```python
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


@dataclass(frozen=True)
class DecodedFrameRecord:
    sequence: int
    digest: bytes
    canonical_bytes: bytes
```

- [ ] **Step 4: Implement a length-delimited QR envelope**

```python
QR_MAGIC = b"ALDQ\x01"


def encode_qr_payload(item: HashedPacket) -> bytes:
    payload = item.canonical_bytes
    if len(payload) > 800:
        raise FrameDecodeError("canonical packet exceeds 800 bytes")
    return QR_MAGIC + struct.pack(">IH", item.packet.sequence, len(payload)) + item.digest + payload
```

`decode_qr_payload()` checks magic, exact total length, sequence equality between envelope and parsed canonical packet, digest length, canonical reserialization, and the packet digest supplied by the caller during chain verification. Reject trailing bytes.

- [ ] **Step 5: Run payload tests and verify GREEN**

Run: `python -m pytest tests/test_media_codecs.py -k qr_payload -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit QR payload support**

```bash
git add pyproject.toml ald_media_controller.py tests/test_media_codecs.py
git commit -m "feat: define ALD packet media profile"
```

### Task 2: Human-readable executable instruction frames

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_media_codecs.py`

**Interfaces:**
- Consumes: `HashedPacket`, `MediaProfile`, and destination path.
- Produces: `render_instruction_frame(...) -> Path` and `decode_instruction_frame(path: Path, profile: MediaProfile) -> DecodedFrameRecord`.

- [ ] **Step 1: Write failing encoded-frame round-trip tests**

```python
def test_rendered_frame_decodes_exact_packet(compiled_recipe, tmp_path):
    item = compiled_recipe.packets[0]
    path = render_instruction_frame(item, DEFAULT_MEDIA_PROFILE, tmp_path / "frame.png")
    decoded = decode_instruction_frame(path, DEFAULT_MEDIA_PROFILE)
    assert decoded.canonical_bytes == item.canonical_bytes
    assert decoded.digest == item.digest


def test_frame_with_two_qr_codes_is_rejected(compiled_recipe, tmp_path):
    path = make_ambiguous_two_code_frame(compiled_recipe.packets[:2], tmp_path / "ambiguous.png")
    with pytest.raises(FrameDecodeError, match="exactly one"):
        decode_instruction_frame(path, DEFAULT_MEDIA_PROFILE)
```

- [ ] **Step 2: Run frame tests and verify RED**

Run: `python -m pytest tests/test_media_codecs.py -k frame -v`

Expected: tests fail because frame functions are missing.

- [ ] **Step 3: Render a deterministic QR and text layout**

Use a white 1920x1080 RGB canvas. Render a black QR symbol on the left with Q correction, eight-pixel modules, and four-module quiet zone. Render protocol, recipe ID, sequence, opcode, canonical argument JSON, and full hexadecimal digest on the right using `ImageFont.load_default(size=24)` from Pillow; do not search system fonts dynamically. Reject layouts whose text or QR bounds exceed the canvas.

- [ ] **Step 4: Decode exactly one QR result and return raw bytes**

```python
def decode_instruction_frame(path: Path, profile: MediaProfile) -> DecodedFrameRecord:
    image = Image.open(path).convert("RGB")
    if image.size != (profile.width, profile.height):
        raise FrameDecodeError("unexpected frame dimensions")
    results = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    if len(results) != 1:
        raise FrameDecodeError(f"expected exactly one QR code, found {len(results)}")
    return decode_qr_payload(bytes(results[0].bytes))
```

- [ ] **Step 5: Run frame tests and verify GREEN**

Run: `python -m pytest tests/test_media_codecs.py -k frame -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit instruction-frame support**

```bash
git add ald_media_controller.py tests/test_media_codecs.py
git commit -m "feat: render executable ALD instruction frames"
```

### Task 3: Binary checksum record and Manchester codec

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_media_codecs.py`

**Interfaces:**
- Consumes: sequence and 32-byte digest.
- Produces: `build_audio_record(sequence: int, digest: bytes) -> bytes`, `parse_audio_record(record: bytes) -> AudioRecord`, `manchester_encode(data: bytes) -> tuple[int, ...]`, and `manchester_decode(symbols: Sequence[int]) -> bytes`.

- [ ] **Step 1: Write failing binary-framing tests**

```python
def test_audio_record_layout_and_crc():
    digest = bytes(range(32))
    record = build_audio_record(0x01020304, digest)
    assert record[:8] == b"\xAA" * 8
    assert record[8] == 1
    assert record[9:13] == b"\x01\x02\x03\x04"
    assert parse_audio_record(record) == AudioRecord(1, 0x01020304, digest)


def test_manchester_rejects_invalid_pair():
    with pytest.raises(AudioDecodeError, match="Manchester"):
        manchester_decode([0, 0])
```

- [ ] **Step 2: Run binary-framing tests and verify RED**

Run: `python -m pytest tests/test_media_codecs.py -k 'audio_record or manchester' -v`

Expected: tests fail because framing functions are missing.

- [ ] **Step 3: Implement the exact record layout and CRC scope**

```python
AUDIO_PREAMBLE = b"\xAA" * 8
AUDIO_VERSION = 1
AUDIO_BODY = struct.Struct(">BI32s")


@dataclass(frozen=True)
class AudioRecord:
    version: int
    sequence: int
    digest: bytes


def build_audio_record(sequence: int, digest: bytes) -> bytes:
    if not 0 <= sequence <= 0xFFFFFFFF or len(digest) != 32:
        raise AudioDecodeError("invalid sequence or digest")
    body = AUDIO_BODY.pack(AUDIO_VERSION, sequence, digest)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return AUDIO_PREAMBLE + body + struct.pack(">I", crc)
```

Define Manchester mapping bit 0 as symbols `(0, 1)` and bit 1 as `(1, 0)`. Parse exactly 53 bytes, validate preamble/version/CRC, and reject trailing or truncated records.

- [ ] **Step 4: Run binary-framing tests and verify GREEN**

Run: `python -m pytest tests/test_media_codecs.py -k 'audio_record or manchester' -v`

Expected: all selected tests pass.

- [ ] **Step 5: Commit checksum-record support**

```bash
git add ald_media_controller.py tests/test_media_codecs.py
git commit -m "feat: frame ALD audio checksum records"
```

### Task 4: BFSK waveform encoder and tolerant decoder

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_media_codecs.py`

**Interfaces:**
- Consumes: `AudioRecord`, `MediaProfile`, WAV paths, and PCM samples.
- Produces: `encode_checksum_audio(...) -> np.ndarray`, `write_checksum_wav(...) -> Path`, `read_checksum_wav(...) -> np.ndarray`, and `decode_checksum_audio(...) -> AudioRecord`.

- [ ] **Step 1: Write failing waveform and corruption tests**

```python
def test_bfsk_wav_round_trip(tmp_path):
    digest = hashlib.sha256(b"packet").digest()
    path = write_checksum_wav(7, digest, DEFAULT_MEDIA_PROFILE, tmp_path / "checksum.wav")
    assert decode_checksum_audio(read_checksum_wav(path), DEFAULT_MEDIA_PROFILE) == AudioRecord(1, 7, digest)


def test_one_corrupt_copy_still_decodes_but_two_do_not():
    samples = encode_checksum_audio(7, b"d" * 32, DEFAULT_MEDIA_PROFILE)
    one_bad = corrupt_audio_copy(samples, copy_index=0)
    assert decode_checksum_audio(one_bad, DEFAULT_MEDIA_PROFILE).sequence == 7
    two_bad = corrupt_audio_copy(one_bad, copy_index=1)
    with pytest.raises(AudioDecodeError, match="two matching"):
        decode_checksum_audio(two_bad, DEFAULT_MEDIA_PROFILE)
```

- [ ] **Step 2: Run waveform tests and verify RED**

Run: `python -m pytest tests/test_media_codecs.py -k 'bfsk or corrupt_copy' -v`

Expected: tests fail because waveform functions are missing.

- [ ] **Step 3: Implement phase-continuous BFSK generation**

Use exactly 40 samples per symbol. Generate one or two complete carrier cycles per symbol for 1200/2400 Hz, maintain phase across non-silent symbols, apply a four-sample cosine ramp at each record boundary, use 100 ms silence guards, repeat the Manchester record three times, and zero-pad to exactly 144000 samples. Normalize peak amplitude to 0.7 and write signed 16-bit little-endian mono PCM WAV.

- [ ] **Step 4: Implement correlation decoding and copy voting**

For each 40-sample symbol window, subtract its mean and compare dot products against normalized 1200 Hz and 2400 Hz sine/cosine reference pairs. Convert the greater energy to symbol 0 or 1. Search for the Manchester-encoded 64-bit preamble, parse non-overlapping candidate records, validate Manchester pairs and CRC, group valid records by `(version, sequence, digest)`, and require a group count of at least two. Reject ties and conflicting groups.

- [ ] **Step 5: Run waveform tests and verify GREEN**

Run: `python -m pytest tests/test_media_codecs.py -k 'audio or bfsk or manchester or corrupt_copy' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit BFSK waveform support**

```bash
git add ald_media_controller.py tests/test_media_codecs.py
git commit -m "feat: encode ALD checksums as BFSK audio"
```

### Task 5: Packet-media artifact staging and codec acceptance

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_media_codecs.py`

**Interfaces:**
- Consumes: `CompiledRecipe`, output directory, and `MediaProfile`.
- Produces: `PacketMediaArtifact(sequence: int, frame_path: Path, audio_path: Path, digest: bytes)` and `stage_packet_media(compiled, directory, profile) -> tuple[PacketMediaArtifact, ...]`.

- [ ] **Step 1: Write a failing multi-packet staging test**

```python
def test_staged_artifacts_round_trip_all_packets(compiled_recipe, tmp_path):
    artifacts = stage_packet_media(compiled_recipe, tmp_path, DEFAULT_MEDIA_PROFILE)
    assert len(artifacts) == len(compiled_recipe.packets)
    for expected, artifact in zip(compiled_recipe.packets, artifacts, strict=True):
        frame = decode_instruction_frame(artifact.frame_path, DEFAULT_MEDIA_PROFILE)
        audio = decode_checksum_audio(read_checksum_wav(artifact.audio_path), DEFAULT_MEDIA_PROFILE)
        assert (frame.sequence, frame.digest) == (expected.packet.sequence, expected.digest)
        assert (audio.sequence, audio.digest) == (expected.packet.sequence, expected.digest)
```

- [ ] **Step 2: Run staging test and verify RED**

Run: `python -m pytest tests/test_media_codecs.py::test_staged_artifacts_round_trip_all_packets -v`

Expected: FAIL because staging is missing.

- [ ] **Step 3: Implement deterministic names and post-write verification**

Define `PacketMediaArtifact(sequence: int, frame_path: Path, audio_path: Path, digest: bytes)` as an immutable dataclass. Write `packet-000000.png` and `packet-000000.wav` for sequence zero, then increment with six digits. After writing each pair, decode both files and compare sequence and digest to the source `HashedPacket`. On mismatch, remove the staging directory and raise the precise `FrameDecodeError` or `AudioDecodeError`; never return a partial tuple.

- [ ] **Step 4: Run the complete codec suite and verify GREEN**

Run: `python -m pytest tests/test_media_codecs.py -v`

Expected: all codec tests pass with zero failures.

- [ ] **Step 5: Run core regression tests**

Run: `python -m pytest tests/test_ald_media_controller.py -v`

Expected: all core tests still pass.

- [ ] **Step 6: Commit the phase-two acceptance state**

```bash
git add ald_media_controller.py tests/test_media_codecs.py
git commit -m "feat: stage verified ALD packet media"
```
