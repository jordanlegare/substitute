# Majorana 2 Product-MP4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified `product.mp4` mode that renders a recognizable Majorana 2 public-reference product view, carries the existing canonical ALD packet stream in a synchronized MP4 `bin_data/gpmd` track, preserves BFSK checksum audio, and leaves the existing QR/HLS mode unchanged.

**Architecture:** Reuse the canonical recipe compiler, ALD1 hash chain, simulator, BFSK codec, local FFmpeg subprocess boundary, transactional publication, and simulator packet interface. Add deterministic product-scene/SVG/raster modules, a fixed 1024-byte timed packet-slot protocol, an FFmpeg bridge that timestamps raw slots with `setts`, stages them through MPEG-TS as `bin_data`, remuxes them into MP4 as `gpmd`, and a product-specific manifest/verifier that yields the same `HashedPacket` stream used by direct and QR-media simulation.

**Tech Stack:** Python 3.10+, stdlib `dataclasses`/`hashlib`/`json`/`struct`/`wave`/`zlib`, NumPy, Pillow, existing Manchester/BFSK codecs, FFmpeg/ffprobe, pytest, optional Ed25519 through `cryptography`.

**Spec:** `docs/specs/2026-09-04-majorana2-product-mp4-design.md`

## Global Constraints

- Keep `recipes/majorana2_public_specs_reference_sim.json` a public-reference simulation model with `physical_fabrication_mapping: false`.
- Do not invent precursor chemistry, lithography, etch, deposition, cryogenic, barrier, or equipment-specific process values.
- Preserve existing `compile`, `verify`, and `simulate-media` QR/HLS behavior.
- Product video pixels and OCR are never executable instruction sources.
- Product executable bytes come only from the verified MP4 data track.
- Existing Manchester/BFSK audio remains an independent sequence/hash witness.
- Canonical packet bytes and the ALD1 SHA-256 chain remain byte-identical across direct, QR-media, and product-MP4 modes.
- Product compilation remains local-only, simulation-only, and transactional.
- Python floor remains 3.10; current dependency bounds stay unchanged.
- Reuse the existing fixed media profile: 1920x1080, 3.0-second intervals, mono 48 kHz audio, 1200 symbols/s, 1200/2400 Hz carriers, three BFSK copies with two required matches.
- Product data slots are exactly 1024 bytes; canonical packet payloads remain bounded to 800 bytes.
- Product bundle protocol is `ALD-PRODUCT/1`; product scene protocol is `ALD-PRODUCT-SCENE/1`; product data version is 1.

## File Structure

Create:

- `ald_product_scene.py` — strict public-reference extraction, immutable scene/document model, canonical product JSON parser/serializer.
- `ald_product_svg.py` — deterministic top/stack/final SVG serialization.
- `ald_product_data.py` — fixed 1024-byte timed packet-slot codec.
- `ald_product_render.py` — deterministic Pillow frames and concatenated BFSK WAV.
- `ald_product_mp4.py` — FFmpeg capability proof, MPEG-TS data staging, final MP4 mux/probe/demux helpers.
- `ald_product_bundle.py` — canonical product `bundle.json` writer and artifact digests.
- `ald_product_verify.py` — fail-closed product bundle verification.
- `tests/test_product_scene.py`
- `tests/test_product_data.py`
- `tests/test_product_mp4.py`
- `tests/test_product_verification.py`
- `tests/test_product_cli.py`
- `.github/workflows/product-mp4.yml`

Modify:

- `ald_media_codecs.py` — expose canonical packet parsing and hashed-packet validation for reuse.
- `ald_hls_signature.py` — accept an explicit bundle-key schema while preserving the HLS default.
- `ald_media_cli.py` — add explicit product commands and orchestration.
- `ald_media_controller.py` — re-export product APIs through the existing facade pattern.
- `pyproject.toml` — package all new flat modules.
- `README.md`
- `docs/majorana2-public-spec-reference.md`

Do not restructure `ald_core.py`, `ald_hardened_core.py`, existing HLS packaging, or existing HLS verification.

---

### Task 1: Deterministic Product Scene, Product JSON, and SVG Views

**Files:**
- Create: `ald_product_scene.py`
- Create: `ald_product_svg.py`
- Create: `tests/test_product_scene.py`
- Modify: `pyproject.toml`

**Interfaces:**

```python
build_product_scene(
    recipe: core.Recipe,
    *,
    stage: str,
    simulation: core.SimulationResult | None = None,
) -> ProductScene

build_product_document(
    scene: ProductScene,
    *,
    recipe_sha256: bytes,
    root_hash: bytes,
    view_sha256: Mapping[str, str],
) -> ProductDocument

canonical_product_json(document: ProductDocument) -> bytes
parse_product_json(raw: bytes) -> ProductDocument
render_top_svg(scene: ProductScene) -> bytes
render_stack_svg(scene: ProductScene) -> bytes
render_final_svg(scene: ProductScene) -> bytes
write_product_svgs(scene: ProductScene, root: Path) -> Mapping[str, Path]
```

- [ ] **Step 1: Write RED public-reference extraction tests**

Create `tests/test_product_scene.py`:

```python
from pathlib import Path
import pytest
import ald_hardened_core as core
from ald_product_scene import build_product_scene

MAJORANA_RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def majorana_recipe() -> core.Recipe:
    return core.validate_recipe(core.load_recipe(MAJORANA_RECIPE))


def test_majorana_scene_preserves_reference_geometry_without_fabrication_mapping():
    scene = build_product_scene(majorana_recipe(), stage="final")
    assert scene.protocol == "ALD-PRODUCT-SCENE/1"
    assert scene.physical_fabrication_mapping is False
    assert scene.tetron.shape == "H-shaped superconducting island"
    assert scene.tetron.horizontal_nanowires == 2
    assert scene.tetron.horizontal_nanowire_length_um == 3.5
    assert scene.tetron.horizontal_nanowire_width_nm == 35.0
    assert scene.tetron.backbone_length_um == 1.0
    assert scene.tetron.backbone_width_nm == 20.0
    assert len(scene.gate_layers) == 3
    assert len(scene.quantum_dots) == 5
    assert sum(dot.shared_with_vertical_neighbor for dot in scene.quantum_dots) == 3


def test_unknown_stack_fields_remain_unspecified():
    scene = build_product_scene(majorana_recipe(), stage="reference-stack")
    layers = {layer.role: layer for layer in scene.layers}
    assert layers["substrate"].material == "GaSb"
    assert layers["substrate"].thickness_nm is None
    assert layers["bottom_barrier"].material is None
    assert layers["bottom_barrier"].thickness_nm is None
    assert layers["quantum_well_inas"].thickness_nm == 6.0
    assert layers["quantum_well_inassb"].thickness_nm == 2.0
    assert layers["superconductor"].material == "Pb"
    assert layers["superconductor"].thickness_nm == 10.0


def test_generic_recipe_cannot_be_rendered_as_majorana_product():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    with pytest.raises(core.RecipeError, match="public_device_reference"):
        build_product_scene(recipe, stage="final")
```

- [ ] **Step 2: Run the new test and confirm RED**

Run:

```bash
python -m pytest -q tests/test_product_scene.py
```

Expected: import failure for `ald_product_scene`.

- [ ] **Step 3: Implement immutable scene/document dataclasses and strict extraction**

Define `ProductLayer`, `ProductTetron`, `ProductGateLayer`, `ProductQuantumDot`, `SimulationOverlay`, `ProductScene`, and `ProductDocument` as frozen dataclasses.

Require exact `False` at `recipe.metadata["simulation_mapping"]["physical_fabrication_mapping"]`. Read device appearance only from `recipe.metadata["public_device_reference"]`.

Use this layer order:

```python
(
    ProductLayer("substrate", "GaSb", None, False),
    ProductLayer("buffer", None, None, False),
    ProductLayer("bottom_barrier", None, None, False),
    ProductLayer("quantum_well_inas", "InAs", 6.0, True),
    ProductLayer("quantum_well_inassb", "InAs0.8Sb0.2", 2.0, True),
    ProductLayer("top_barrier", None, None, False),
    ProductLayer("superconductor", "Pb", 10.0, True),
)
```

If source metadata later supplies an unknown layer value, preserve that source value only. Never derive process values or physical coordinates.

Construct three gate layers from the source `functions` list. Construct QD1-QD5 as schematic identities; mark exactly three as shared with vertical neighbors.

For `simulation-status` and `final`, require a successful simulation and exact integer `simulation.seed`. Overlay only final coverage, thickness, defect fraction, and seed, labeled `generic A/B surrogate simulation status`.

- [ ] **Step 4: Write SVG determinism tests**

Add:

```python
from ald_product_svg import render_final_svg, render_stack_svg, render_top_svg


def test_svg_views_are_deterministic_and_structurally_distinct():
    scene = build_product_scene(majorana_recipe(), stage="final")
    top_a = render_top_svg(scene)
    top_b = render_top_svg(scene)
    stack = render_stack_svg(scene)
    final = render_final_svg(scene)
    assert top_a == top_b
    assert top_a.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b"QD1" in top_a and b"QD5" in top_a
    assert b"InAs0.8Sb0.2" in stack
    assert b"Pb" in stack
    assert b"UNSPECIFIED" in stack
    assert top_a != stack
    assert final != stack
```

- [ ] **Step 5: Implement deterministic SVG serialization**

Use `xml.sax.saxutils.escape`, a fixed 1600x900 viewBox, fixed attribute ordering, integer presentation coordinates, LF endings, no timestamps, and no random IDs.

Top view must show two horizontal nanowires, central backbone forming an H, three gate bands, five QD circles, public dimension labels, and `PUBLIC-REFERENCE SCHEMATIC — NOT A FABRICATION RECIPE`.

Stack view must show layers in semantic order. Unknown layer material or thickness is rendered as `UNSPECIFIED`; unknown layers get a fixed display height only, never a numeric inferred thickness.

Final view combines top and stack and includes `physical_fabrication_mapping=false`.

- [ ] **Step 6: Implement canonical product document serialization and parser**

`ProductDocument` contains scene, exact 32-byte recipe SHA-256, exact 32-byte root hash, and exactly three lowercase SHA-256 view digests keyed `top`, `stack`, `final`.

Serialize sorted compact UTF-8 JSON plus one LF. `parse_product_json()` must reject duplicate keys, nonfinite numbers, field drift, malformed digests, invalid stage values, noncanonical encoding, and any `physical_fabrication_mapping` value other than exact `False`. Parsed documents must reserialize byte-identically.

- [ ] **Step 7: Package, test, and commit**

Add `ald_product_scene` and `ald_product_svg` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py
python -m py_compile ald_product_scene.py ald_product_svg.py
python -m pytest -q tests/test_ald_media_controller.py tests/test_media_codecs.py tests/test_phase_one_acceptance.py
```

Expected: all pass.

Commit:

```bash
git add ald_product_scene.py ald_product_svg.py tests/test_product_scene.py pyproject.toml
git commit -m "feat: add Majorana 2 product scene views"
```

---

### Task 2: Fixed 1024-Byte Timed Product Data Protocol

**Files:**
- Create: `ald_product_data.py`
- Create: `tests/test_product_data.py`
- Modify: `ald_media_codecs.py`
- Modify: `tests/test_media_codecs.py`
- Modify: `pyproject.toml`

**Interfaces:**

```python
ald_media_codecs.validate_hashed_packet(item: core.HashedPacket) -> None
ald_media_codecs.decode_canonical_packet_bytes(payload: bytes) -> core.Packet
encode_product_slot(item: core.HashedPacket, *, pts_ms: int, duration_ms: int) -> bytes
decode_product_slot(slot: bytes) -> ProductDataRecord
build_product_slots(compiled: core.CompiledRecipe, *, interval_ms: int = 3000) -> tuple[bytes, ...]
write_product_slot_stream(
    compiled: core.CompiledRecipe,
    destination: Path,
    *,
    interval_ms: int = 3000,
    include_guard: bool = True,
) -> Path
```

- [ ] **Step 1: Promote shared packet validators without changing semantics**

Rename `_validate_hashed_packet` to `validate_hashed_packet` and `_decode_canonical_packet` to `decode_canonical_packet_bytes`. Update existing QR functions to call the promoted names.

Add a regression test that validates and decodes `compiled_recipe.packets[0]`, then asserts canonical bytes are unchanged.

Run:

```bash
python -m pytest -q tests/test_media_codecs.py
```

Expected: all existing and new codec tests pass.

- [ ] **Step 2: Write RED fixed-slot tests**

Create tests asserting a slot is exactly 1024 bytes, sequence 0 has PTS 0 and duration 3000, canonical bytes and digest round-trip exactly, and all compiled packets produce contiguous three-second timestamps.

Run:

```bash
python -m pytest -q tests/test_product_data.py
```

Expected: import failure for `ald_product_data`.

- [ ] **Step 3: Implement the binary envelope**

Use:

```python
DATA_MAGIC = b"ALDP"
DATA_VERSION = 1
DATA_SLOT_BYTES = 1024
MAX_CANONICAL_BYTES = 800
_HEADER = struct.Struct(">4sBIQIH32s")
_CRC = struct.Struct(">I")
```

Exact layout:

```text
4 bytes  magic ALDP
1 byte   version 1
4 bytes  sequence, unsigned big endian
8 bytes  pts_ms, unsigned big endian
4 bytes  duration_ms, unsigned big endian
2 bytes  canonical packet length, unsigned big endian
32 bytes ALD1 chained digest
N bytes  canonical packet, N <= 800
4 bytes  CRC-32 over header plus canonical packet
zero padding through byte 1023
```

`encode_product_slot()` calls `validate_hashed_packet()`, requires nonnegative 63-bit `pts_ms`, positive 32-bit `duration_ms`, packet <=800 bytes, and zero pads to 1024.

`decode_product_slot()` requires exact `bytes`, exact length, exact magic/version, valid duration, bounded packet length, valid CRC, zero-only padding, canonical packet parse success, and envelope sequence equal to packet sequence.

- [ ] **Step 4: Add corruption tests**

Test wrong magic, version, sequence, zero duration, oversized declared length, corrupted payload, corrupted digest, CRC failure, nonzero padding, truncation, and trailing bytes. Every mutation must raise an ALD error before a trusted packet is returned.

- [ ] **Step 5: Implement deterministic slot stream with one guard slot**

`build_product_slots()` emits only real packet slots with `pts_ms = sequence * interval_ms` and `duration_ms = interval_ms`.

`write_product_slot_stream(compiled, destination, interval_ms=3000, include_guard=True)` writes all real slots followed by one all-zero 1024-byte guard. The guard is FFmpeg staging only. Task 3 must prove it is absent from final MP4; verification rejects any final extra packet.

- [ ] **Step 6: Package, test, and commit**

Add `ald_product_data` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_data.py tests/test_media_codecs.py
python -m py_compile ald_product_data.py ald_media_codecs.py
```

Expected: all pass.

Commit:

```bash
git add ald_product_data.py ald_media_codecs.py tests/test_product_data.py tests/test_media_codecs.py pyproject.toml
git commit -m "feat: add timed product MP4 data records"
```

---

### Task 3: Product Raster/BFSK Sources and Real FFmpeg MP4 Data Track

**Files:**
- Create: `ald_product_render.py`
- Create: `ald_product_mp4.py`
- Create: `tests/test_product_mp4.py`
- Modify: `pyproject.toml`

**Interfaces:**

```python
stage_product_tracks(
    compiled: core.CompiledRecipe,
    simulation: core.SimulationResult,
    root: Path,
    profile: media.MediaProfile,
) -> ProductTrackSources

probe_product_mp4_capabilities(capabilities: MediaCapabilities) -> None
mux_product_mp4(
    sources: ProductTrackSources,
    destination: Path,
    capabilities: MediaCapabilities,
    profile: media.MediaProfile,
) -> Path
probe_product_mp4(
    path: Path,
    capabilities: MediaCapabilities,
    *,
    packet_count: int,
    interval_seconds: float,
) -> ProductMP4Probe
extract_product_data(path: Path, destination: Path, capabilities: MediaCapabilities) -> Path
extract_product_audio(path: Path, destination: Path, capabilities: MediaCapabilities) -> Path
```

- [ ] **Step 1: Write RED staging tests**

Test that one 1920x1080 PNG exists per compiled packet, source duration is `packet_count * 3.0`, and product staging succeeds even when `media.render_instruction_frame` is monkeypatched to raise. This proves no QR frame dependency.

- [ ] **Step 2: Implement deterministic frames and full BFSK WAV**

Use exact opcode-stage mapping:

```python
_STAGE_BY_OPCODE = {
    "CONFIGURE": "reference-stack",
    "SET_TEMPERATURE": "reference-stack",
    "EVACUATE": "tetron",
    "STABILIZE": "gates",
    "ALD_CYCLE": "simulation-status",
    "MEASURE": "quantum-dots",
    "SHUTDOWN": "final",
}
```

Each frame shows H-tetron geometry, gate bands, QD labels, stack context, packet sequence/opcode as status only, and the non-fabrication banner. `simulation-status` and `final` include synthetic final coverage/thickness/defect/seed with an explicit surrogate label. Never render QR or command bytes.

Concatenate one `media.encode_checksum_audio(sequence, digest, profile)` interval per packet and write mono 16-bit PCM WAV at 48 kHz. Write the guarded packet slot stream beside the other private staging inputs.

- [ ] **Step 3: Implement a real FFmpeg capability proof**

Create two deterministic 1024-byte slots plus one zero guard. Stage them to MPEG-TS with:

```python
stage_args = [
    str(capabilities.ffmpeg),
    "-hide_banner", "-loglevel", "error",
    "-f", "data", "-raw_packet_size", "1024",
    "-i", str(slot_path),
    "-map", "0:0", "-c", "copy",
    "-bsf:0", "setts=pts=N*3000:dts=N*3000:duration=3000:time_base=1/1000",
    "-f", "mpegts", "-y", str(data_ts),
]
```

Create six seconds of lavfi video/audio plus `data.ts`, map one video/audio/data stream, encode H.264/AAC, copy data, use `-copy_unknown`, `-tag:d:0 gpmd`, and `handler_name=ALD Instruction Data`.

Require ffprobe to report exactly one H.264 video stream, one AAC audio stream, and one `codec_type=data`, `codec_name=bin_data`, `codec_tag_string=gpmd` stream.

Demux the data stream to raw `-f data` and require bytes equal exactly the two real slots, excluding the guard. Require two data packets of 1024 bytes with PTS 0 and 3 seconds and duration 3 seconds within 50 ms. If this profile is unsupported, raise `core.DependencyError`; do not fall back to subtitles, OCR, metadata tags, or sidecars.

- [ ] **Step 4: Run capability test before final mux implementation**

Run:

```bash
python -m pytest -q tests/test_product_mp4.py -m requires_ffmpeg
```

Expected: capability proof passes on supported CI FFmpeg.

- [ ] **Step 5: Implement final MP4 mux and probe**

Use product PNGs at `-framerate 1/3`, checksum WAV, and staged `data.ts`. Map exactly one video, one audio, one data stream. Encode H.264/AAC, copy data with `gpmd`, and do not use `-shortest` so the guard can provide final sample duration while being discarded.

Reject output unless video is H.264 1920x1080, audio is mono 48 kHz AAC, data is `bin_data/gpmd`, stream counts are exactly one each, data packet count equals compiled packet count, each data packet is 1024 bytes, PTS increments by three seconds within 50 ms, duration is three seconds within 50 ms, and total media duration covers the final interval.

- [ ] **Step 6: Add real end-to-end track test**

Mux the Majorana recipe product MP4, probe it, extract data, split into 1024-byte slots, decode each slot, and compare canonical bytes and digest with `compiled.packets`.

- [ ] **Step 7: Package, test, and commit**

Add `ald_product_render` and `ald_product_mp4` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py tests/test_product_data.py tests/test_product_mp4.py
python -m py_compile ald_product_render.py ald_product_mp4.py
```

Expected: all pass.

Commit:

```bash
git add ald_product_render.py ald_product_mp4.py tests/test_product_mp4.py pyproject.toml
git commit -m "feat: mux visual product MP4 data tracks"
```

---

### Task 4: Canonical Product Bundle, Signatures, and Fail-Closed Verification

**Files:**
- Create: `ald_product_bundle.py`
- Create: `ald_product_verify.py`
- Create: `tests/test_product_verification.py`
- Modify: `ald_hls_signature.py`
- Modify: `tests/test_hls_verification.py`
- Modify: `pyproject.toml`

**Interfaces:**

```python
write_product_bundle_index(
    compiled: core.CompiledRecipe,
    *,
    product_path: Path,
    recipe_path: Path,
    scene_path: Path,
    top_svg_path: Path,
    stack_svg_path: Path,
    final_svg_path: Path,
    destination: Path,
    profile: media.MediaProfile,
    render_seed: int,
    ffmpeg_version: str,
    video_encoder: str,
    audio_encoder: str,
) -> Path

verify_product_bundle(
    index_path: Path,
    *,
    require_signature: bool = False,
    trusted_public_key: Path | None = None,
) -> VerifiedProductRecipe
```

- [ ] **Step 1: Generalize signature schema while preserving HLS defaults**

Change hardcoded HLS bundle keys to `_HLS_BUNDLE_KEYS`. Add keyword-only `expected_keys: frozenset[str] = _HLS_BUNDLE_KEYS` to `sign_bundle_index()` and `verify_bundle_signature_bytes()`, thread it through private parsers/loaders, and keep `ALD-BUNDLE-SIGNATURE\x00` unchanged.

Run:

```bash
python -m pytest -q tests/test_hls_verification.py
```

Expected: all existing HLS signature/verifier tests pass.

- [ ] **Step 2: Define exact product manifest schema**

```python
PRODUCT_BUNDLE_KEYS = frozenset({
    "protocol", "media_type", "media_profile", "ffmpeg",
    "product", "recipe", "scene", "views", "packets",
    "root_hash", "render_seed", "signature", "creation_tool_version",
})
```

Use fixed artifact names `product.mp4`, `recipe.canonical.json`, `product.json`, `product-top.svg`, `product-stack.svg`, `product-final.svg`. Bind each final artifact by SHA-256. Packet index entries contain exact `sequence`, `digest`, `pts_ms`, and `duration_ms` from the compiled packet stream. Product FFmpeg metadata declares `data_codec="bin_data"` and `data_tag="gpmd"`.

- [ ] **Step 3: Implement canonical atomic index writing**

Reject symlinks, missing files, and non-regular files. Require exact integer render seed. Use only fixed relative artifact names. Initialize `signature` as `None`, serialize canonical sorted compact JSON plus LF, and atomically publish within the candidate bundle.

- [ ] **Step 4: Write RED tamper tests**

Build one real Majorana candidate bundle at seed 42. Add separate rejection tests for modifying product MP4, product JSON, each SVG, canonical recipe, packet digest, packet PTS, packet duration, manifest keys, symlink substitution, data-slot bytes with updated outer MP4 digest, and audio interval bytes with updated outer MP4 digest.

Every case must raise product `IntegrityError` and expose no executable packets.

- [ ] **Step 5: Implement strict manifest and artifact parsing**

`VerifiedProductRecipe` fields are:

```python
packets: tuple[core.HashedPacket, ...]
root_hash: bytes
profile: media.MediaProfile
signature_status: SignatureStatus
recipe_bytes: bytes
product_bytes: bytes
render_seed: int
```

Reject duplicate JSON keys, nonfinite numbers, field drift, noncanonical JSON, unsafe relative paths, symlinks, digest mismatches, invalid render seed, and media profile drift.

- [ ] **Step 6: Verify MP4 structure/timing before instruction extraction**

Call `probe_product_mp4()`. Require manifest and ffprobe to agree on packet count, ordering, 1024-byte size, PTS, and duration. Reject extra, missing, duplicate, reordered, zero-duration, or out-of-window data packets.

- [ ] **Step 7: Extract and verify authoritative instruction slots**

Use `extract_product_data()`, require exact byte length `packet_count * 1024`, split on slot boundaries, decode each slot, require sequence and embedded timeline match manifest, recompute `core.hash_packet(previous_digest, canonical_bytes)`, compare embedded and manifest digest, then construct `core.HashedPacket`. Require final digest equals manifest root hash.

- [ ] **Step 8: Verify one BFSK witness per packet interval**

Use `extract_product_audio()` to mono 48 kHz PCM. Require exact sample count `packet_count * 144000`. Decode each 3-second interval with `media.decode_checksum_audio()` and require its sequence and digest equal the corresponding verified data record. Do not decode QR or OCR video.

- [ ] **Step 9: Recompile bound recipe and require packet identity**

Stage bound canonical recipe bytes privately, run existing load/validate/compile, and compare packet count, canonical bytes, previous digests, digests, and root hash against the data-track-derived packet stream.

- [ ] **Step 10: Parse product JSON and re-render SVGs**

Require scene protocol, recipe ID, exact false fabrication mapping, recipe SHA-256, packet root, view digests, and overlay seed to match verified bundle data. Re-render all three SVGs from parsed scene and require byte equality with bound SVG files.

- [ ] **Step 11: Add product signature tests**

Use:

```python
sign_bundle_index(
    index_path,
    private_key_path,
    expected_keys=PRODUCT_BUNDLE_KEYS,
)
```

and:

```python
verify_bundle_signature_bytes(
    raw_bundle_bytes,
    trusted_public_key,
    expected_keys=PRODUCT_BUNDLE_KEYS,
)
```

Cover unsigned accepted by default, unsigned rejected when required, trusted valid signature accepted, wrong key rejected, and signed manifest mutation rejected.

- [ ] **Step 12: Package, test, and commit**

Add `ald_product_bundle` and `ald_product_verify` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_verification.py tests/test_hls_verification.py
python -m py_compile ald_product_bundle.py ald_product_verify.py ald_hls_signature.py
```

Expected: all pass.

Commit:

```bash
git add ald_product_bundle.py ald_product_verify.py ald_hls_signature.py tests/test_product_verification.py tests/test_hls_verification.py pyproject.toml
git commit -m "feat: verify signed product MP4 bundles"
```

---

### Task 5: CLI, Facade, Transactional Publication, Documentation, and CI

**Files:**
- Create: `tests/test_product_cli.py`
- Create: `.github/workflows/product-mp4.yml`
- Modify: `ald_media_cli.py`
- Modify: `ald_media_controller.py`
- Modify: `README.md`
- Modify: `docs/majorana2-public-spec-reference.md`
- Modify: `pyproject.toml`

**CLI Contract:**

```text
ald-media-controller compile-product RECIPE --output DIR [--seed N] [--overwrite] [--signing-key KEY]
ald-media-controller verify-product BUNDLE_JSON [--require-signature] [--trusted-public-key KEY]
ald-media-controller simulate-product BUNDLE_JSON --seed N --output DIR [--overwrite] [--require-signature] [--trusted-public-key KEY]
```

`compile-product` render seed defaults to 42. Existing commands remain unchanged.

- [ ] **Step 1: Write RED parser tests**

Test that `compile-product` parses with seed 42 by default and that legacy `compile` still parses to command `compile` with no product behavior.

Run:

```bash
python -m pytest -q tests/test_product_cli.py
```

Expected: parser rejects product command before implementation.

- [ ] **Step 2: Add product subcommands and exit-code fallbacks**

Add `compile-product`, `verify-product`, and `simulate-product` with the CLI contract above. Map unexpected errors to MEDIA, INTEGRITY, and CONTROLLER respectively.

- [ ] **Step 3: Implement `_run_compile_product()` with existing safe publication lifecycle**

Exact order:

1. resolve publishable target;
2. reject recipe/output overlap;
3. load, validate, compile recipe;
4. run deterministic simulation at render seed and reject fault;
5. probe normal and product MP4 capabilities;
6. create private build root under target parent;
7. create candidate bundle directory;
8. build final product scene with synthetic overlay;
9. write three SVGs;
10. stage PNG/BFSK/data inputs outside candidate;
11. mux `candidate/product.mp4`;
12. write `candidate/recipe.canonical.json`;
13. compute SVG digests, build product document, write `candidate/product.json`;
14. write `candidate/bundle.json`;
15. optionally sign with `PRODUCT_BUNDLE_KEYS` and derive temporary trusted public key;
16. verify completed candidate with `verify_product_bundle()`;
17. compare verified canonical packets, digests, root, and recipe bytes to just-built inputs;
18. atomically publish candidate;
19. remove all private staging in `finally`.

Do not publish `data.ts`, PNG staging frames, checksum WAV, or slot-stream files.

- [ ] **Step 4: Implement verify and simulate product orchestration**

`_run_verify_product()` prints compact JSON with `protocol`, `media_type`, `packet_count`, `root_hash`, `render_seed`, and `signature_status`.

`_run_simulate_product()` verifies the product bundle, reuses `_bind_verified_recipe()` because the verified type exposes `packets`, `root_hash`, and `recipe_bytes`, rejects output overlap, executes the deterministic simulator with requested seed, and publishes existing reports.

Document that render seed and simulation execution seed may differ; visual numeric overlay always represents compile-time render seed.

- [ ] **Step 5: Re-export product APIs in `ald_media_controller.py`**

Import all product modules beside existing media modules. Re-export scene/document types and functions, SVG APIs, data slot APIs, product staging APIs, product MP4 APIs, `PRODUCT_BUNDLE_KEYS`, bundle writer, `VerifiedProductRecipe`, and `verify_product_bundle`. Also re-export promoted `decode_canonical_packet_bytes` and `validate_hashed_packet`.

Keep `_core.build_parser`, `_core.main`, and module aliasing behavior unchanged.

- [ ] **Step 6: Add real CLI end-to-end acceptance**

Run:

```bash
ald-media-controller compile-product recipes/majorana2_public_specs_reference_sim.json --seed 42 --output build/product-acceptance/bundle
ald-media-controller verify-product build/product-acceptance/bundle/bundle.json
ald-media-controller simulate recipes/majorana2_public_specs_reference_sim.json --seed 42 --output build/product-acceptance/direct
ald-media-controller simulate-product build/product-acceptance/bundle/bundle.json --seed 42 --output build/product-acceptance/product
cmp build/product-acceptance/direct/cycles.csv build/product-acceptance/product/cycles.csv
cmp build/product-acceptance/direct/surface-final.json build/product-acceptance/product/surface-final.json
```

Require product bundle files `product.mp4`, `product.json`, `product-top.svg`, `product-stack.svg`, `product-final.svg`, `recipe.canonical.json`, and `bundle.json`. Require no `stream.m3u8`.

- [ ] **Step 7: Run legacy QR/HLS regression from same head**

Run:

```bash
ald-media-controller compile recipes/generic_al2o3.json --output build/qr-regression/bundle
ald-media-controller verify build/qr-regression/bundle/stream.m3u8
ald-media-controller simulate-media build/qr-regression/bundle/stream.m3u8 --seed 42 --output build/qr-regression/media
```

Expected: unchanged behavior.

- [ ] **Step 8: Add dedicated product CI workflow**

Use Ubuntu latest, Python 3.11, apt-installed FFmpeg, and `python -m pip install -e '.[test,signature]'`. Run full pytest, compile all existing and seven new Python modules, then run Task 5 Step 6 acceptance and direct/product byte comparisons.

- [ ] **Step 9: Update documentation**

README mode table:

| Mode | Human visual | Executable source | Independent checksum | Container |
| --- | --- | --- | --- | --- |
| Direct | reports only | canonical recipe | ALD1 hash chain | none |
| QR media | QR instruction frame | decoded QR bytes | BFSK audio | HLS/fMP4 |
| Product MP4 | Majorana 2 schematic product stage | MP4 `bin_data/gpmd` slots | BFSK audio | single MP4 bundle |

Document exact product commands. State that `gpmd` is the FFmpeg/MP4 transport tag for `bin_data`; payload bytes use repository-defined `ALDP` version 1 and are not GoPro GPMF telemetry. State that video is display-only and never OCR-executable.

Update Majorana 2 reference docs to distinguish public-reference metadata, schematic presentation coordinates, synthetic A/B simulator overlay, and executable canonical ALD-MEDIA/1 surrogate packets. Preserve all excluded process details and `physical_fabrication_mapping=false`.

- [ ] **Step 10: Run complete verification matrix**

Run:

```bash
python -m pytest -q
python -m py_compile ald_core.py ald_hardened_core.py ald_media_codecs.py ald_media_staging.py ald_compression.py ald_media_controller.py ald_media_cli.py ald_hls_integration.py ald_hls_packaging.py ald_hls_bundle.py ald_hls_signature.py ald_hls_verify.py ald_product_scene.py ald_product_svg.py ald_product_data.py ald_product_render.py ald_product_mp4.py ald_product_bundle.py ald_product_verify.py
```

Then repeat product and QR end-to-end commands from Steps 6 and 7.

Inspect final product streams:

```bash
ffprobe -v error -show_entries stream=index,codec_type,codec_name,codec_tag_string,width,height,sample_rate,channels -of json build/product-acceptance/bundle/product.mp4
ffprobe -v error -select_streams d:0 -show_packets -show_entries packet=pts_time,duration_time,size -of json build/product-acceptance/bundle/product.mp4
```

Expected: exactly one H.264 1920x1080 video stream, one mono 48 kHz AAC stream, one `bin_data/gpmd` data stream, one 1024-byte data packet per canonical instruction at three-second intervals, and no guard packet.

- [ ] **Step 11: Commit Task 5**

```bash
git add ald_media_cli.py ald_media_controller.py tests/test_product_cli.py .github/workflows/product-mp4.yml README.md docs/majorana2-public-spec-reference.md pyproject.toml
git commit -m "feat: add verified Majorana 2 product MP4 mode"
```

---

## Final Review Gate

Before merging the implementation PR:

- run the complete Task 5 verification matrix on the exact head;
- confirm the Majorana 2 reference recipe gained no physical fabrication parameters;
- confirm product verification never calls QR decoding or OCR;
- confirm unchanged QR/HLS commands remain green;
- confirm product verification rejects modified video, audio, data, product JSON, SVG, recipe, and manifest artifacts;
- inspect the final visual for H-tetron geometry, gate bands, five QD labels, and material stack;
- confirm `product.json` contains `physical_fabrication_mapping:false`;
- confirm ffprobe reports exactly one H.264 video, one AAC audio, and one `bin_data/gpmd` data stream;
- confirm direct/product simulation reports are byte-identical at seed 42;
- request code review on the exact verified head before merge.
