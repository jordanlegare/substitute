# Majorana 2 Product-MP4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified `product.mp4` mode that renders a recognizable Majorana 2 public-reference product view, carries the existing canonical ALD packet stream in a synchronized MP4 `bin_data/gpmd` track, preserves BFSK checksum audio, and leaves the existing QR/HLS mode unchanged.

**Architecture:** Keep the canonical recipe compiler, ALD1 hash chain, simulator, BFSK codec, transactional publication, and verification boundary as the shared trust core. Add deterministic product-scene/SVG/raster modules, a fixed 1024-byte binary packet-slot protocol, an FFmpeg data-track bridge that timestamps raw slots with `setts`, stages them through MPEG-TS as `bin_data`, then remuxes them into the final MP4 as `gpmd`, plus a product-specific manifest/verifier that returns the same `HashedPacket` objects consumed by the simulator.

**Tech Stack:** Python 3.10+, stdlib `dataclasses`/`hashlib`/`json`/`struct`/`wave`/`zlib`, NumPy, Pillow, existing QR/BFSK codec module, FFmpeg/ffprobe, pytest, optional `cryptography` Ed25519 support.

**Spec:** `docs/specs/2026-09-04-majorana2-product-mp4-design.md`

## Global Constraints

- Preserve `recipes/majorana2_public_specs_reference_sim.json` as a public-reference simulation model with `physical_fabrication_mapping: false`.
- Do not invent precursor chemistry, lithography/etch/deposition recipes, cryogenic setpoints, barrier composition/thickness, or equipment-specific process values.
- Existing `compile`, `verify`, and `simulate-media` QR/HLS behavior must remain backward compatible.
- Product video pixels and OCR are never executable instruction sources.
- Product-mode executable bytes come only from the embedded MP4 data stream after full fail-closed verification.
- Existing Manchester/BFSK audio remains an independent synchronized sequence/hash witness.
- Canonical packet bytes and the ALD1 chained SHA-256 root remain byte-identical across direct, QR-media, and product-MP4 modes.
- Product compilation remains local-only and transactional; no network or live industrial hardware/control path is introduced.
- Python floor remains 3.10; current dependency bounds in `pyproject.toml` remain unchanged unless a task explicitly says otherwise.
- Use the fixed existing media dimensions/audio profile: 1920x1080, 3.0-second packet intervals, mono 48 kHz BFSK audio, 1200 symbols/s, 1200/2400 Hz carriers, three copies with two required matches.
- Product data slots are exactly 1024 bytes; canonical packet payloads remain bounded to 800 bytes.
- Product bundle protocol is `ALD-PRODUCT/1`; scene protocol is `ALD-PRODUCT-SCENE/1`; product data version is 1.

---

## File Structure

Create these focused modules:

- `ald_product_scene.py` — strict extraction of public-reference metadata, immutable scene model, stage selection, canonical `product.json` payload construction.
- `ald_product_svg.py` — deterministic top/stack/final SVG serialization from the scene model.
- `ald_product_data.py` — 1024-byte timed packet-slot codec and stream writer/parser.
- `ald_product_render.py` — Pillow raster frames and concatenated BFSK checksum WAV for product intervals.
- `ald_product_mp4.py` — FFmpeg capability proof, raw-data -> MPEG-TS `bin_data` staging, final H.264/AAC/gpmd MP4 muxing, ffprobe helpers.
- `ald_product_bundle.py` — canonical `bundle.json` construction and artifact digest binding.
- `ald_product_verify.py` — strict product manifest/artifact/stream/timestamp/data/audio/hash/signature verification.

Create these tests:

- `tests/test_product_scene.py`
- `tests/test_product_data.py`
- `tests/test_product_mp4.py`
- `tests/test_product_verification.py`
- `tests/test_product_cli.py`

Modify only the existing integration surfaces that need product-mode awareness:

- `ald_media_codecs.py` — expose the existing canonical packet-byte parser publicly so QR and product data share one parser.
- `ald_hls_signature.py` — make bundle-key schema an optional argument while keeping the existing HLS schema as the default.
- `ald_media_cli.py` — add `compile-product`, `verify-product`, and `simulate-product` orchestration.
- `ald_media_controller.py` — re-export product public APIs only if the controller facade currently re-exports sibling media APIs.
- `pyproject.toml` — package all new flat modules.
- `.github/workflows/product-mp4.yml` — dedicated FFmpeg-backed product acceptance gate.
- `README.md` and `docs/majorana2-public-spec-reference.md` — user commands, artifact contract, mode comparison, scientific/safety caveats.

Do not restructure `ald_core.py`, `ald_hardened_core.py`, or the existing HLS packaging/verifier unless a failing compatibility test demonstrates a product-mode dependency that cannot live behind the new modules.

---

### Task 1: Deterministic Majorana 2 Product Scene, JSON, and SVG Views

**Files:**
- Create: `ald_product_scene.py`
- Create: `ald_product_svg.py`
- Create: `tests/test_product_scene.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: validated `ald_core.Recipe`; optional `ald_core.SimulationResult` used only for explicitly labeled synthetic status overlays.
- Produces:
  - `ProductScene`
  - `ProductLayer`
  - `ProductTetron`
  - `ProductGateLayer`
  - `ProductQuantumDot`
  - `SimulationOverlay`
  - `build_product_scene(recipe: core.Recipe, *, stage: str, simulation: core.SimulationResult | None = None) -> ProductScene`
  - `canonical_product_json(scene: ProductScene, *, recipe_sha256: bytes, root_hash: bytes, view_sha256: Mapping[str, str]) -> bytes`
  - `render_top_svg(scene: ProductScene) -> bytes`
  - `render_stack_svg(scene: ProductScene) -> bytes`
  - `render_final_svg(scene: ProductScene) -> bytes`
  - `write_product_svgs(scene: ProductScene, root: Path) -> Mapping[str, Path]`

- [ ] **Step 1: Write the public-reference extraction tests**

Create `tests/test_product_scene.py` with a helper that loads the checked-in Majorana 2 reference recipe and tests the exact fields the renderer is allowed to use:

```python
from pathlib import Path

import ald_hardened_core as core
from ald_product_scene import build_product_scene


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def majorana_recipe() -> core.Recipe:
    return core.validate_recipe(core.load_recipe(RECIPE))


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


def test_majorana_scene_keeps_unknown_stack_fields_unspecified():
    scene = build_product_scene(majorana_recipe(), stage="reference-stack")
    layers = {layer.role: layer for layer in scene.layers}

    assert layers["substrate"].material == "GaSb"
    assert layers["substrate"].thickness_nm is None
    assert layers["bottom_barrier"].material is None
    assert layers["bottom_barrier"].thickness_nm is None
    assert layers["quantum_well_inas"].material == "InAs"
    assert layers["quantum_well_inas"].thickness_nm == 6.0
    assert layers["quantum_well_inassb"].material == "InAs0.8Sb0.2"
    assert layers["quantum_well_inassb"].thickness_nm == 2.0
    assert layers["superconductor"].material == "Pb"
    assert layers["superconductor"].thickness_nm == 10.0
```

Add a rejection test proving that a recipe with missing public-reference metadata cannot silently fall back to guessed geometry:

```python
import pytest


def test_product_scene_rejects_recipe_without_public_device_reference():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    with pytest.raises(core.RecipeError, match="public_device_reference"):
        build_product_scene(recipe, stage="final")
```

- [ ] **Step 2: Run the scene tests and verify RED**

Run:

```bash
python -m pytest -q tests/test_product_scene.py
```

Expected: collection/import failure because `ald_product_scene` does not exist.

- [ ] **Step 3: Implement the immutable scene model and strict metadata extraction**

In `ald_product_scene.py`, define exact scene types and fixed stage names:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

import ald_hardened_core as core


SCENE_PROTOCOL = "ALD-PRODUCT-SCENE/1"
PRODUCT_STAGES = (
    "reference-stack",
    "tetron",
    "gates",
    "quantum-dots",
    "simulation-status",
    "final",
)


@dataclass(frozen=True)
class ProductLayer:
    role: str
    material: str | None
    thickness_nm: float | None
    specified: bool


@dataclass(frozen=True)
class ProductTetron:
    shape: str
    horizontal_nanowires: int
    horizontal_nanowire_length_um: float
    horizontal_nanowire_width_nm: float
    backbone_length_um: float
    backbone_width_nm: float
    target_majorana_zero_modes: int


@dataclass(frozen=True)
class ProductGateLayer:
    index: int
    function: str
    schematic: bool = True


@dataclass(frozen=True)
class ProductQuantumDot:
    index: int
    label: str
    shared_with_vertical_neighbor: bool
    schematic: bool = True


@dataclass(frozen=True)
class SimulationOverlay:
    seed: int
    coverage: float
    thickness_nm: float
    defect_fraction: float
    label: str = "generic A/B surrogate simulation status"


@dataclass(frozen=True)
class ProductScene:
    protocol: str
    recipe_id: str
    reference_target: str
    reference_status: str
    scientific_caveat: str
    physical_fabrication_mapping: bool
    stage: str
    layers: tuple[ProductLayer, ...]
    tetron: ProductTetron
    gate_layers: tuple[ProductGateLayer, ...]
    quantum_dots: tuple[ProductQuantumDot, ...]
    unspecified_fields: tuple[str, ...]
    overlay: SimulationOverlay | None
```

Implement `build_product_scene()` so it reads only `recipe.metadata["public_device_reference"]` and the existing source/status/caveat metadata. Require `physical_fabrication_mapping` to be exact `False`; if it is absent or true, raise `core.RecipeError`.

Build the stack in this fixed semantic order:

```python
(
    ProductLayer("substrate", "GaSb", None, False),
    ProductLayer("buffer", buffer_material_or_none, None, buffer_material_or_none is not None),
    ProductLayer("bottom_barrier", bottom_material_or_none, bottom_thickness_or_none, both_known),
    ProductLayer("quantum_well_inas", "InAs", 6.0, True),
    ProductLayer("quantum_well_inassb", "InAs0.8Sb0.2", 2.0, True),
    ProductLayer("top_barrier", top_material_or_none, top_thickness_or_none, both_known),
    ProductLayer("superconductor", "Pb", 10.0, True),
)
```

Do not infer a substrate thickness. Do not convert the public layer dimensions into process parameters.

Construct five quantum-dot objects as schematic identities, not physical coordinates. Mark exactly three as `shared_with_vertical_neighbor=True`, matching the public reference count. The renderer may choose normalized display positions later, but the model must not store invented physical positions.

When a `SimulationResult` is supplied, permit an overlay only for `simulation-status` and `final`. Build it from the final result fields:

```python
SimulationOverlay(
    seed=simulation.seed,
    coverage=simulation.surface.coverage,
    thickness_nm=simulation.surface.thickness_nm,
    defect_fraction=simulation.surface.defect_fraction,
)
```

Reject a faulted simulation when an overlay is requested.

- [ ] **Step 4: Add deterministic SVG tests**

Extend `tests/test_product_scene.py`:

```python
from ald_product_svg import render_final_svg, render_stack_svg, render_top_svg


def test_majorana_svg_views_are_deterministic_and_structurally_distinct():
    scene = build_product_scene(majorana_recipe(), stage="final")

    top_a = render_top_svg(scene)
    top_b = render_top_svg(scene)
    stack = render_stack_svg(scene)
    final = render_final_svg(scene)

    assert top_a == top_b
    assert top_a.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b"H-shaped superconducting island" in top_a
    assert b"QD1" in top_a and b"QD5" in top_a
    assert b"InAs0.8Sb0.2" in stack
    assert b"Pb" in stack
    assert b"UNSPECIFIED" in stack
    assert top_a != stack
    assert final != stack
```

- [ ] **Step 5: Implement deterministic SVG serialization**

In `ald_product_svg.py`, generate SVG bytes directly with `xml.sax.saxutils.escape`; do not use a browser or external rasterizer. Use a fixed 1600x900 viewBox and integer normalized layout coordinates. Physical dimension text may be annotated, but layout coordinates are explicitly schematic.

Top-view rules:

- draw two long horizontal nanowire rectangles;
- draw one vertical central backbone to form an H;
- draw three gate-layer bands as semi-transparent schematic overlays;
- draw five labeled dot circles `QD1` through `QD5`;
- include a banner: `PUBLIC-REFERENCE SCHEMATIC — NOT A FABRICATION RECIPE`;
- include the public tetron dimensions as text annotations, never as process instructions.

Stack-view rules:

- draw each layer in semantic order;
- use a fixed display thickness for unknown layers and label them `UNSPECIFIED`;
- use relative visual thickness for the known 6/2/10 nm layers while retaining exact values in labels;
- never infer a numeric value for unknown thickness.

Final-view rules:

- place top view on the left and stack view on the right in one 1600x900 SVG;
- include the same provenance banner and `physical_fabrication_mapping=false` text.

Canonicalize output manually: fixed attribute order, `\n` line endings, no timestamps, no random IDs, and a final newline.

- [ ] **Step 6: Implement canonical `product.json` bytes**

Add `canonical_product_json()` in `ald_product_scene.py`. Serialize these exact top-level keys:

```python
{
    "protocol": "ALD-PRODUCT-SCENE/1",
    "recipe_id": scene.recipe_id,
    "reference_target": scene.reference_target,
    "reference_status": scene.reference_status,
    "scientific_caveat": scene.scientific_caveat,
    "physical_fabrication_mapping": False,
    "stage": scene.stage,
    "layers": [...],
    "tetron": {...},
    "gate_layers": [...],
    "quantum_dots": [...],
    "unspecified_fields": [...],
    "simulation_overlay": None or {...},
    "recipe_sha256": recipe_sha256.hex(),
    "packet_root_hash": root_hash.hex(),
    "views": dict(sorted(view_sha256.items())),
}
```

Use:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

Validate `recipe_sha256` and `root_hash` are exact 32-byte values and every view digest is a 64-character lowercase hex string.

- [ ] **Step 7: Package modules and run focused tests**

Add `ald_product_scene` and `ald_product_svg` to `[tool.setuptools].py-modules` in `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py
python -m py_compile ald_product_scene.py ald_product_svg.py
```

Expected: all product-scene tests pass and both modules compile.

- [ ] **Step 8: Run the existing non-FFmpeg regression suite**

Run:

```bash
python -m pytest -q tests/test_ald_media_controller.py tests/test_media_codecs.py tests/test_phase_one_acceptance.py
```

Expected: all existing tests remain green.

- [ ] **Step 9: Commit Task 1**

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
- Consumes: exact `core.HashedPacket` objects from `compile_recipe()` and the shared canonical packet parser in `ald_media_codecs`.
- Produces:
  - `ProductDataRecord(sequence: int, pts_ms: int, duration_ms: int, packet: core.Packet, canonical_bytes: bytes, digest: bytes)`
  - `encode_product_slot(item: core.HashedPacket, *, pts_ms: int, duration_ms: int) -> bytes`
  - `decode_product_slot(slot: bytes) -> ProductDataRecord`
  - `build_product_slots(compiled: core.CompiledRecipe, *, interval_ms: int = 3000) -> tuple[bytes, ...]`
  - `write_product_slot_stream(compiled: core.CompiledRecipe, destination: Path, *, interval_ms: int = 3000, include_guard: bool = True) -> Path`
  - public `ald_media_codecs.decode_canonical_packet_bytes(payload: bytes) -> core.Packet`

- [ ] **Step 1: Expose the shared canonical packet decoder without changing QR behavior**

In `tests/test_media_codecs.py`, add:

```python
from ald_media_codecs import decode_canonical_packet_bytes


def test_public_canonical_packet_decoder_round_trips_compiled_packet(compiled_recipe):
    item = compiled_recipe.packets[0]
    packet = decode_canonical_packet_bytes(item.canonical_bytes)
    assert core.canonical_packet_bytes(packet) == item.canonical_bytes
```

Rename `_decode_canonical_packet()` to `decode_canonical_packet_bytes()` in `ald_media_codecs.py` and update `decode_qr_payload()` to call the public name. Do not change parsing rules or accepted canonical bytes.

Run:

```bash
python -m pytest -q tests/test_media_codecs.py
```

Expected: existing QR/audio tests and the new public-parser test pass.

- [ ] **Step 2: Write RED tests for exact slot layout and round-trip**

Create `tests/test_product_data.py` with:

```python
import hashlib
from pathlib import Path

import pytest

import ald_hardened_core as core
from ald_product_data import (
    DATA_SLOT_BYTES,
    build_product_slots,
    decode_product_slot,
    encode_product_slot,
)


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compiled_recipe() -> core.CompiledRecipe:
    return core.compile_recipe(core.validate_recipe(core.load_recipe(RECIPE)))


def test_product_slot_is_fixed_size_and_round_trips_canonical_packet():
    item = compiled_recipe().packets[0]
    slot = encode_product_slot(item, pts_ms=0, duration_ms=3000)
    decoded = decode_product_slot(slot)

    assert len(slot) == DATA_SLOT_BYTES == 1024
    assert decoded.sequence == 0
    assert decoded.pts_ms == 0
    assert decoded.duration_ms == 3000
    assert decoded.canonical_bytes == item.canonical_bytes
    assert decoded.digest == item.digest
    assert core.canonical_packet_bytes(decoded.packet) == item.canonical_bytes


def test_product_slots_have_contiguous_three_second_timeline():
    compiled = compiled_recipe()
    records = tuple(decode_product_slot(slot) for slot in build_product_slots(compiled))
    assert [record.sequence for record in records] == list(range(len(compiled.packets)))
    assert [record.pts_ms for record in records] == [index * 3000 for index in range(len(records))]
    assert {record.duration_ms for record in records} == {3000}
```

- [ ] **Step 3: Run data tests and verify RED**

Run:

```bash
python -m pytest -q tests/test_product_data.py
```

Expected: collection/import failure because `ald_product_data` does not exist.

- [ ] **Step 4: Implement the exact slot envelope**

In `ald_product_data.py` define:

```python
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import zlib

import ald_hardened_core as core
from ald_media_codecs import decode_canonical_packet_bytes


DATA_MAGIC = b"ALDP"
DATA_VERSION = 1
DATA_SLOT_BYTES = 1024
MAX_CANONICAL_BYTES = 800
_HEADER = struct.Struct(">4sBIQIH32s")
_CRC = struct.Struct(">I")
_GUARD_SLOT = bytes(DATA_SLOT_BYTES)


@dataclass(frozen=True)
class ProductDataRecord:
    sequence: int
    pts_ms: int
    duration_ms: int
    packet: core.Packet
    canonical_bytes: bytes
    digest: bytes
```

The binary layout is exactly:

```text
4 bytes  magic = ALDP
1 byte   version = 1
4 bytes  sequence (big endian unsigned)
8 bytes  pts_ms (big endian unsigned)
4 bytes  duration_ms (big endian unsigned)
2 bytes  canonical packet length (big endian unsigned)
32 bytes ALD1 chained packet digest
N bytes  canonical packet bytes, N <= 800
4 bytes  CRC-32 over header + canonical packet bytes
zero padding to exactly 1024 bytes
```

`encode_product_slot()` must call the same hashed-packet structural checks used by the QR codec or repeat the exact immutable-type/hash checks without relaxing them. Require `0 <= pts_ms <= 2**63-1` and `1 <= duration_ms <= 2**32-1`.

CRC code:

```python
body = _HEADER.pack(
    DATA_MAGIC,
    DATA_VERSION,
    item.packet.sequence,
    pts_ms,
    duration_ms,
    len(item.canonical_bytes),
    item.digest,
) + item.canonical_bytes
crc = _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
slot = body + crc
return slot + bytes(DATA_SLOT_BYTES - len(slot))
```

`decode_product_slot()` must require exact `bytes`, exact length 1024, exact magic/version, packet length <= 800, matching CRC, all remaining padding bytes zero, canonical packet parser success, and envelope sequence equal to parsed packet sequence.

- [ ] **Step 5: Add corruption and boundary tests**

Add explicit tests for every failure class:

```python
@pytest.mark.parametrize("offset", [0, 4, 8, 20, 60, 100])
def test_product_slot_rejects_single_byte_corruption(offset):
    item = compiled_recipe().packets[0]
    slot = bytearray(encode_product_slot(item, pts_ms=0, duration_ms=3000))
    slot[offset] ^= 0x01
    with pytest.raises(core.ALDError):
        decode_product_slot(bytes(slot))


def test_product_slot_rejects_nonzero_padding():
    item = compiled_recipe().packets[0]
    slot = bytearray(encode_product_slot(item, pts_ms=0, duration_ms=3000))
    slot[-1] = 1
    with pytest.raises(core.ALDError, match="padding"):
        decode_product_slot(bytes(slot))


def test_product_slot_rejects_truncation_and_trailing_bytes():
    item = compiled_recipe().packets[0]
    slot = encode_product_slot(item, pts_ms=0, duration_ms=3000)
    with pytest.raises(core.ALDError):
        decode_product_slot(slot[:-1])
    with pytest.raises(core.ALDError):
        decode_product_slot(slot + b"\x00")
```

Also mutate the version, sequence, duration, declared payload length, digest, canonical payload, and CRC independently. Each mutation must fail before any `HashedPacket` is returned to a simulator.

- [ ] **Step 6: Implement slot-stream generation with one FFmpeg guard slot**

`build_product_slots()` must produce only real packet slots. `write_product_slot_stream(..., include_guard=True)` writes all real slots followed by one all-zero 1024-byte guard slot.

The guard exists only to give the final real packet a following timestamp during MPEG-TS -> MP4 remux. It is not an executable record and the product-MP4 capability test in Task 3 must prove the final MP4 discards it. Verification must reject a final MP4 that retains a guard or any other extra data packet.

- [ ] **Step 7: Run focused and regression tests**

Add `ald_product_data` to `pyproject.toml`, then run:

```bash
python -m pytest -q tests/test_product_data.py tests/test_media_codecs.py
python -m py_compile ald_product_data.py ald_media_codecs.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add ald_product_data.py ald_media_codecs.py tests/test_product_data.py tests/test_media_codecs.py pyproject.toml
git commit -m "feat: add timed product MP4 data records"
```

---

### Task 3: Product Raster Frames, BFSK Track, and Real FFmpeg H.264/AAC/gpmd MP4

**Files:**
- Create: `ald_product_render.py`
- Create: `ald_product_mp4.py`
- Create: `tests/test_product_mp4.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `core.CompiledRecipe`, `core.Recipe`, `core.SimulationResult`, `media.MediaProfile`, Task 1 scene/SVG model, Task 2 slot stream, existing `encode_checksum_audio()`.
- Produces:
  - `ProductTrackSources(frame_dir: Path, checksum_wav: Path, data_slots: Path, packet_count: int, duration_seconds: float)`
  - `stage_product_tracks(compiled, simulation, root, profile) -> ProductTrackSources`
  - `ProductMP4Probe(data_packets: tuple[ProductPacketTiming, ...], video_stream_index: int, audio_stream_index: int, data_stream_index: int)`
  - `probe_product_mp4_capabilities(capabilities: MediaCapabilities) -> None`
  - `mux_product_mp4(sources: ProductTrackSources, destination: Path, capabilities: MediaCapabilities, profile: MediaProfile) -> Path`
  - `probe_product_mp4(path: Path, capabilities: MediaCapabilities, *, packet_count: int, interval_seconds: float) -> ProductMP4Probe`

- [ ] **Step 1: Write RED staging tests that prove product frames contain no executable QR dependency**

Create `tests/test_product_mp4.py`:

```python
from pathlib import Path

from PIL import Image

import ald_hardened_core as core
import ald_media_codecs as media
from ald_product_render import stage_product_tracks


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compile_and_simulate():
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    compiled = core.compile_recipe(recipe)
    simulation = core.SimulatedALDController().execute(compiled, seed=42)
    assert simulation.fault is None
    return recipe, compiled, simulation


def test_product_staging_generates_one_visual_interval_per_packet(tmp_path):
    recipe, compiled, simulation = compile_and_simulate()
    sources = stage_product_tracks(compiled, simulation, tmp_path, media.DEFAULT_MEDIA_PROFILE)

    frames = sorted(sources.frame_dir.glob("frame-*.png"))
    assert len(frames) == len(compiled.packets)
    assert sources.packet_count == len(compiled.packets)
    assert sources.duration_seconds == len(compiled.packets) * 3.0
    with Image.open(frames[-1]) as image:
        assert image.size == (1920, 1080)
```

Add a test that monkeypatches `ald_media_codecs.render_instruction_frame` to raise if called; `stage_product_tracks()` must still succeed. This proves product mode does not render QR instruction frames.

- [ ] **Step 2: Implement deterministic raster-frame staging**

In `ald_product_render.py`, map packet opcodes to visualization stages exactly:

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

Each frame must include:

- the same schematic H-tetron / gate / dot / stack concepts as the SVG scene;
- current packet sequence and opcode as human-readable status only;
- `PUBLIC-REFERENCE SCHEMATIC` and `NOT A FABRICATION RECIPE` text;
- for `simulation-status` and `final`, the final generic A/B surrogate coverage/thickness/defect values plus seed, labeled `synthetic simulator status`;
- no QR symbol and no encoded command payload in the pixels.

Use Pillow primitives and `ImageFont.load_default(size=...)`; no platform font files. Use only deterministic integer coordinates and no timestamps.

- [ ] **Step 3: Implement one concatenated BFSK checksum WAV**

In `stage_product_tracks()`, concatenate one `media.encode_checksum_audio(packet.sequence, packet.digest, profile)` array per packet:

```python
samples = np.concatenate(
    [media.encode_checksum_audio(item.packet.sequence, item.digest, profile) for item in compiled.packets]
)
pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
```

Write a mono 16-bit 48 kHz PCM WAV whose frame count is exactly:

```python
len(compiled.packets) * round(profile.interval_seconds * profile.sample_rate)
```

Call `write_product_slot_stream(compiled, root / "packet-slots.bin", interval_ms=3000, include_guard=True)` for the data input.

- [ ] **Step 4: Write a real FFmpeg capability test for the 1024-byte gpmd bridge**

Mark the test with `@pytest.mark.requires_ffmpeg`. The test must call `probe_media_capabilities()` and then `probe_product_mp4_capabilities()`.

The capability proof must construct at least two nonzero 1024-byte test slots plus one zero guard slot and execute this two-stage pattern using `run_media_tool()` only:

Stage raw slots to MPEG-TS:

```text
ffmpeg
  -hide_banner -loglevel error
  -f data -raw_packet_size 1024 -i packet-slots.bin
  -map 0:0
  -c copy
  -bsf:0 setts=pts=N*3000:dts=N*3000:duration=3000:time_base=1/1000
  -f mpegts data.ts
```

Then combine deterministic test video/audio with `data.ts` into MP4:

```text
ffmpeg
  -hide_banner -loglevel error
  ... video input ...
  ... audio input ...
  -i data.ts
  -map 0:v:0 -map 1:a:0 -map 2:d:0
  -c:v <capabilities.video_encoder>
  -pix_fmt yuv420p
  -c:a aac -b:a 128k
  -c:d copy
  -copy_unknown
  -tag:d:0 gpmd
  -metadata:s:d:0 handler_name=ALD Instruction Data
  -movflags +faststart
  product.mp4
```

After muxing, require ffprobe to show exactly one video stream, one audio stream, and one `codec_type=data`, `codec_name=bin_data`, `codec_tag_string=gpmd` stream.

Extract the final data stream:

```text
ffmpeg -hide_banner -loglevel error -i product.mp4 -map 0:d:0 -c copy -f data extracted.bin
```

Require `extracted.bin` to equal exactly the real slots and to exclude the guard slot.

Require ffprobe packet timing to show real data samples at 0 ms, 3000 ms, ... with a 3000 ms interval tolerance no larger than 50 ms.

If any of these invariants fail, raise `core.DependencyError` with a message stating the local FFmpeg build cannot produce the required ALD product data track. Do not fall back to subtitles, OCR, file metadata, or sidecars.

- [ ] **Step 5: Run the real capability test and verify GREEN before product muxing**

Run:

```bash
python -m pytest -q tests/test_product_mp4.py -m requires_ffmpeg
```

Expected: the raw-data -> MPEG-TS -> MP4 bridge passes on the supported CI FFmpeg image. If it fails, stop Task 3 and keep the failure as the compatibility gate rather than weakening the data-track contract.

- [ ] **Step 6: Implement final product MP4 muxing**

`mux_product_mp4()` first runs or relies on a cached successful per-process capability probe, then stages the real packet-slot stream to `data.ts` with the exact `setts` expression above.

Use image2 for the product frames:

```text
-framerate 1/3 -start_number 0 -i frame-%06d.png
```

Use the staged checksum WAV as input 1 and `data.ts` as input 2. Map exactly one stream of each type. Do not use `-shortest`; the trailing guard data packet must be read so FFmpeg can derive the final real data-sample duration, while the zero-duration guard itself is discarded by the accepted profile.

Encode H.264/AAC and copy the `bin_data` stream using `gpmd`. After the file is closed, call `probe_product_mp4()` and reject publication unless:

- video codec is H.264 and dimensions are exactly 1920x1080;
- audio codec is AAC, mono, 48 kHz;
- data codec is `bin_data` with tag `gpmd`;
- there are exactly `packet_count` data packets, each exactly 1024 bytes;
- data PTS starts at 0 and increments by 3 seconds within 50 ms;
- each data-packet duration is 3 seconds within 50 ms;
- overall media duration covers all packet intervals.

- [ ] **Step 7: Add end-to-end MP4 track tests**

Add:

```python
@pytest.mark.requires_ffmpeg
def test_real_product_mp4_contains_video_audio_and_gpmd_data(tmp_path):
    recipe, compiled, simulation = compile_and_simulate()
    capabilities = probe_media_capabilities()
    sources = stage_product_tracks(compiled, simulation, tmp_path / "source", media.DEFAULT_MEDIA_PROFILE)
    output = mux_product_mp4(
        sources,
        tmp_path / "product.mp4",
        capabilities,
        media.DEFAULT_MEDIA_PROFILE,
    )
    probe = probe_product_mp4(
        output,
        capabilities,
        packet_count=len(compiled.packets),
        interval_seconds=3.0,
    )
    assert len(probe.data_packets) == len(compiled.packets)
```

Also extract the data stream and decode each 1024-byte slot; compare canonical bytes and digests with `compiled.packets`.

- [ ] **Step 8: Package and run focused tests**

Add `ald_product_render` and `ald_product_mp4` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py tests/test_product_data.py tests/test_product_mp4.py
python -m py_compile ald_product_render.py ald_product_mp4.py
```

Expected: all tests pass, with FFmpeg-marked tests running on machines that satisfy the existing FFmpeg requirement.

- [ ] **Step 9: Commit Task 3**

```bash
git add ald_product_render.py ald_product_mp4.py tests/test_product_mp4.py pyproject.toml
git commit -m "feat: mux visual product MP4 data tracks"
```

---

### Task 4: Canonical Product Bundle, Signature Binding, and Fail-Closed Verification

**Files:**
- Create: `ald_product_bundle.py`
- Create: `ald_product_verify.py`
- Create: `tests/test_product_verification.py`
- Modify: `ald_hls_signature.py`
- Modify: `tests/test_hls_verification.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: completed `product.mp4`, canonical recipe bytes, `product.json`, three SVG views, compiled packet index, FFmpeg metadata, existing optional Ed25519 keys.
- Produces:
  - `PRODUCT_BUNDLE_KEYS`
  - `write_product_bundle_index(...) -> Path`
  - `VerifiedProductRecipe(packets, root_hash, profile, signature_status, recipe_bytes, product_bytes, render_seed)`
  - `verify_product_bundle(index_path: Path, *, require_signature: bool = False, trusted_public_key: Path | None = None) -> VerifiedProductRecipe`
- Existing `sign_bundle_index()` and `verify_bundle_signature_bytes()` remain source-compatible for HLS callers while accepting an optional bundle-key schema for product bundles.

- [ ] **Step 1: Generalize signature schema without changing HLS defaults**

In `ald_hls_signature.py`, rename the hardcoded key set to `_HLS_BUNDLE_KEYS` and change internal parsers to accept `expected_keys`.

Keep existing two-argument calls valid:

```python
def sign_bundle_index(
    index_path: Path,
    private_key_path: Path,
    *,
    expected_keys: frozenset[str] = _HLS_BUNDLE_KEYS,
) -> BundleSignature:
    ...


def verify_bundle_signature_bytes(
    bundle_bytes: bytes,
    trusted_public_key: Path,
    *,
    expected_keys: frozenset[str] = _HLS_BUNDLE_KEYS,
) -> SignatureStatus:
    ...
```

Thread `expected_keys` through `_parse_bundle_bytes()` and `_load_bundle()`; keep the signature domain `ALD-BUNDLE-SIGNATURE\x00` unchanged.

Run the existing signature/HLS verification tests immediately:

```bash
python -m pytest -q tests/test_hls_verification.py
```

Expected: all existing tests remain green before product schema support is added.

- [ ] **Step 2: Write the product manifest contract test**

Create `tests/test_product_verification.py` and assert `bundle.json` has these exact top-level keys:

```python
PRODUCT_BUNDLE_KEYS = frozenset({
    "protocol",
    "media_type",
    "media_profile",
    "ffmpeg",
    "product",
    "recipe",
    "scene",
    "views",
    "packets",
    "root_hash",
    "render_seed",
    "signature",
    "creation_tool_version",
})
```

Use these exact nested forms:

```python
"protocol": "ALD-PRODUCT/1"
"media_type": "product-mp4"
"product": {"path": "product.mp4", "sha256": "<64 hex>"}
"recipe": {"path": "recipe.canonical.json", "sha256": "<64 hex>"}
"scene": {"path": "product.json", "sha256": "<64 hex>"}
"views": {
    "final": {"path": "product-final.svg", "sha256": "<64 hex>"},
    "stack": {"path": "product-stack.svg", "sha256": "<64 hex>"},
    "top": {"path": "product-top.svg", "sha256": "<64 hex>"},
}
"packets": [
    {"sequence": 0, "digest": "<64 hex>", "pts_ms": 0, "duration_ms": 3000},
    ...
]
```

`media_profile` carries the existing fixed width/height/interval/audio fields but omits QR-only fields from the product manifest. `ffmpeg` includes `version`, `video_encoder`, `audio_encoder`, `data_codec="bin_data"`, and `data_tag="gpmd"`.

- [ ] **Step 3: Implement canonical product index writing**

In `ald_product_bundle.py`:

- reject symlinks and missing/non-regular artifact paths;
- hash final artifact bytes with SHA-256;
- derive packet entries only from the trusted `core.CompiledRecipe`;
- require packet PTS `sequence * 3000` and duration 3000;
- write canonical sorted compact JSON plus newline;
- initialize `signature` to `None`;
- write atomically in the candidate bundle directory.

Do not include absolute filesystem paths.

- [ ] **Step 4: Write RED verifier tests for all bound artifacts**

Create a fixture that builds a real candidate product bundle with the Majorana recipe at seed 42. Add one test per mutation:

- flip one byte in `product.mp4`;
- flip one byte in `product.json`;
- alter `product-top.svg`;
- alter `product-stack.svg`;
- alter `product-final.svg`;
- alter `recipe.canonical.json`;
- change one packet digest in `bundle.json`;
- change one packet PTS/duration;
- remove or add a top-level manifest key;
- make an artifact path a symlink;
- add an unexpected stream to a copied MP4 fixture when feasible;
- corrupt one data slot while keeping the manifest file digest updated in an unsigned test fixture;
- corrupt one audio interval while keeping the manifest file digest updated in an unsigned test fixture.

Every case must raise `IntegrityError` and return no executable packets.

- [ ] **Step 5: Implement strict product bundle parsing and artifact binding**

In `ald_product_verify.py`, define:

```python
from dataclasses import dataclass

from ald_hls_signature import SignatureStatus


class IntegrityError(core.ALDError):
    exit_code = core.ExitCode.INTEGRITY


@dataclass(frozen=True)
class VerifiedProductRecipe:
    packets: tuple[core.HashedPacket, ...]
    root_hash: bytes
    profile: media.MediaProfile
    signature_status: SignatureStatus
    recipe_bytes: bytes
    product_bytes: bytes
    render_seed: int
```

Parse `bundle.json` with duplicate-key rejection, nonfinite-number rejection, exact key sets, canonical sorted compact JSON enforcement, safe relative filenames, and digest checks.

Require artifact filenames exactly:

```text
product.mp4
recipe.canonical.json
product.json
product-top.svg
product-stack.svg
product-final.svg
```

Require no symlink for any bound artifact.

- [ ] **Step 6: Verify the MP4 stream structure and packet timing before data extraction**

Call `probe_product_mp4()` and require exactly the profile described in Task 3. Compare every ffprobe data packet against the manifest packet index:

```python
abs(actual_pts_seconds - expected_pts_ms / 1000.0) <= 0.05
abs(actual_duration_seconds - expected_duration_ms / 1000.0) <= 0.05
actual_size == 1024
```

Reject extra, missing, reordered, duplicate, zero-duration, or out-of-window data samples.

- [ ] **Step 7: Extract and verify authoritative instruction slots**

Demux only the data stream to a private temporary file using:

```text
ffmpeg -hide_banner -loglevel error -i product.mp4 -map 0:d:0 -c copy -f data extracted.bin
```

Require exact byte length `packet_count * 1024` and split on 1024-byte boundaries.

For every slot:

1. `decode_product_slot()` must succeed.
2. slot sequence equals index.
3. embedded PTS/duration equal manifest PTS/duration.
4. recompute `expected_digest = core.hash_packet(previous_digest, canonical_bytes)`.
5. require embedded digest equals expected digest and manifest digest.
6. create `core.HashedPacket(packet, canonical_bytes, previous_digest, digest)` only after all checks succeed.
7. advance `previous_digest`.

Require the final digest equals manifest `root_hash`.

- [ ] **Step 8: Decode the full AAC checksum track and verify one BFSK witness per interval**

Demux audio to mono 48 kHz 16-bit PCM WAV using the local FFmpeg boundary. Read the complete PCM vector and require exactly `packet_count * interval_samples` samples.

For each packet interval:

```python
start = sequence * interval_samples
stop = start + interval_samples
record = media.decode_checksum_audio(samples[start:stop], profile)
assert record.sequence == sequence
assert record.digest == verified_data_record.digest
```

Any missing/conflicting/CRC-invalid audio witness is an `IntegrityError`. Do not use video frames to recover instructions.

- [ ] **Step 9: Recompile the bound recipe bytes and require exact packet identity**

Stage `recipe.canonical.json` bytes to a private temporary file exactly as `_bind_verified_recipe()` currently does, validate and compile it, then compare:

- packet count;
- each canonical packet byte string;
- each previous digest;
- each digest;
- root hash.

This prevents a self-consistent data track from being substituted for a different bound recipe.

- [ ] **Step 10: Validate `product.json` scientific/safety boundary and SVG reproducibility**

Parse `product.json` canonically and require:

- `protocol == "ALD-PRODUCT-SCENE/1"`;
- `recipe_id` equals the bound recipe;
- `physical_fabrication_mapping is False`;
- `recipe_sha256` equals the bound canonical recipe digest;
- `packet_root_hash` equals the verified ALD1 root;
- `views` digests equal the manifest view digests;
- `simulation_overlay.seed` equals manifest `render_seed` when an overlay is present.

Rebuild the final `ProductScene` from the bound recipe and the manifest/product metadata necessary for deterministic rendering. Re-render the three SVGs and compare bytes with the bound SVG files. Do not attempt to reconstruct stochastic simulation values from video pixels.

- [ ] **Step 11: Add product Ed25519 tests**

Use `sign_bundle_index(index, private_key, expected_keys=PRODUCT_BUNDLE_KEYS)` and verify with:

```python
verify_bundle_signature_bytes(
    raw_bundle_bytes,
    trusted_public_key,
    expected_keys=PRODUCT_BUNDLE_KEYS,
)
```

Tests must cover unsigned accepted-by-default, unsigned rejected when required, valid signature accepted with trusted key, wrong key rejected, and any signed product/SVG/recipe/data manifest digest change rejected.

- [ ] **Step 12: Package and run verification suites**

Add `ald_product_bundle` and `ald_product_verify` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_verification.py tests/test_hls_verification.py
python -m py_compile ald_product_bundle.py ald_product_verify.py ald_hls_signature.py
```

Expected: all product verification and existing HLS verification tests pass.

- [ ] **Step 13: Commit Task 4**

```bash
git add ald_product_bundle.py ald_product_verify.py ald_hls_signature.py tests/test_product_verification.py tests/test_hls_verification.py pyproject.toml
git commit -m "feat: verify signed product MP4 bundles"
```

---

### Task 5: Product CLI, Transactional Publication, Documentation, and CI Acceptance

**Files:**
- Create: `tests/test_product_cli.py`
- Create: `.github/workflows/product-mp4.yml`
- Modify: `ald_media_cli.py`
- Modify: `ald_media_controller.py` if facade exports need updating
- Modify: `README.md`
- Modify: `docs/majorana2-public-spec-reference.md`
- Modify: `pyproject.toml` if a module was not already listed by Tasks 1-4

**Interfaces:**
- Produces CLI commands:
  - `ald-media-controller compile-product RECIPE --output DIR [--seed N] [--overwrite] [--signing-key KEY]`
  - `ald-media-controller verify-product BUNDLE_JSON [--require-signature] [--trusted-public-key KEY]`
  - `ald-media-controller simulate-product BUNDLE_JSON --seed N --output DIR [--overwrite] [--require-signature] [--trusted-public-key KEY]`
- `compile-product` uses render seed 42 when `--seed` is omitted.
- Existing commands retain their current argument contract and behavior.

- [ ] **Step 1: Write RED CLI parser tests**

In `tests/test_product_cli.py`:

```python
from ald_media_cli import build_parser


def test_product_commands_are_explicit_and_do_not_change_existing_compile_default():
    parser = build_parser()
    args = parser.parse_args([
        "compile-product",
        "recipes/majorana2_public_specs_reference_sim.json",
        "--output",
        "build/product",
    ])
    assert args.command == "compile-product"
    assert args.seed == 42

    old = parser.parse_args([
        "compile",
        "recipes/generic_al2o3.json",
        "--output",
        "build/hls",
    ])
    assert old.command == "compile"
```

Run:

```bash
python -m pytest -q tests/test_product_cli.py
```

Expected: RED because product subcommands are absent.

- [ ] **Step 2: Add product subcommands to `build_parser()`**

Add:

```python
compile_product = commands.add_parser(
    "compile-product",
    help="compile a public-reference product visualization with embedded verified instructions",
)
compile_product.add_argument("recipe", type=Path)
compile_product.add_argument("--output", type=Path, required=True)
compile_product.add_argument("--seed", type=int, default=42)
compile_product.add_argument("--overwrite", action="store_true")
compile_product.add_argument("--signing-key", type=Path)
core._add_log_level(compile_product)
```

Add equivalent `verify-product` and `simulate-product` parsers matching the interface above.

Update the unexpected-exception fallback map so:

```python
"compile-product": core.ExitCode.MEDIA
"verify-product": core.ExitCode.INTEGRITY
"simulate-product": core.ExitCode.CONTROLLER
```

- [ ] **Step 3: Implement `_run_compile_product()` using the existing transactional publication pattern**

Follow `_run_compile()`'s safe output lifecycle:

1. `_require_publishable_output()`.
2. `_reject_recipe_output_overlap()`.
3. load, validate, compile recipe.
4. execute `SimulatedALDController().execute(compiled, seed)` and reject a faulted result.
5. `probe_media_capabilities()` and `probe_product_mp4_capabilities()`.
6. create a private build directory under the target parent.
7. create candidate `bundle/`.
8. render final scene and SVG views.
9. stage raster/audio/data track sources.
10. mux final `candidate/product.mp4`.
11. write `candidate/recipe.canonical.json` with the existing canonical recipe writer.
12. hash SVGs and create canonical `candidate/product.json`.
13. write canonical `candidate/bundle.json`.
14. optionally sign using `PRODUCT_BUNDLE_KEYS`.
15. call `verify_product_bundle()` on the completed candidate.
16. compare verified packet canonical bytes/digests/root with `compiled` and verified recipe bytes with the candidate canonical recipe bytes.
17. publish using `_publish_verified_bundle()` only after all checks pass.
18. always remove private build remnants in `finally`.

Do not publish `data.ts`, source PNGs, WAV staging files, or `packet-slots.bin`; those remain temporary build inputs.

- [ ] **Step 4: Implement `_run_verify_product()` and `_run_simulate_product()`**

`_run_verify_product()` calls the product verifier and prints canonical compact JSON containing:

```python
{
    "protocol": "ALD-PRODUCT/1",
    "packet_count": len(verified.packets),
    "root_hash": verified.root_hash.hex(),
    "render_seed": verified.render_seed,
    "signature_status": verified.signature_status.value,
    "media_type": "product-mp4",
}
```

`_run_simulate_product()`:

1. verifies `bundle.json`;
2. reuses `_bind_verified_recipe(verified)` because `VerifiedProductRecipe` exposes the same `packets`, `root_hash`, and `recipe_bytes` attributes;
3. rejects output overlap with the product bundle directory;
4. executes `SimulatedALDController().execute(compiled, seed)`;
5. publishes reports with existing `core.publish_reports()`.

Execution seed remains a simulator input and may differ from the compile-time `render_seed`; documentation must say the product video's numeric overlay represents the compile-time render seed only.

- [ ] **Step 5: Add real CLI end-to-end acceptance test**

Mark with `requires_ffmpeg` and run the installed-style `main()` path or subprocess console script. The test sequence is:

```bash
ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/product-acceptance/bundle

ald-media-controller verify-product \
  build/product-acceptance/bundle/bundle.json

ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/product-acceptance/direct

ald-media-controller simulate-product \
  build/product-acceptance/bundle/bundle.json \
  --seed 42 \
  --output build/product-acceptance/product

cmp build/product-acceptance/direct/cycles.csv \
    build/product-acceptance/product/cycles.csv
cmp build/product-acceptance/direct/surface-final.json \
    build/product-acceptance/product/surface-final.json
```

The test also requires these published files and no QR/HLS requirement inside the product bundle:

```text
product.mp4
product.json
product-top.svg
product-stack.svg
product-final.svg
recipe.canonical.json
bundle.json
```

`stream.m3u8` must not be required or generated by `compile-product`.

- [ ] **Step 6: Add QR compatibility regression in the same branch**

Run the unchanged existing path:

```bash
ald-media-controller compile recipes/generic_al2o3.json --output build/qr-regression/bundle
ald-media-controller verify build/qr-regression/bundle/stream.m3u8
ald-media-controller simulate-media build/qr-regression/bundle/stream.m3u8 --seed 42 --output build/qr-regression/media
```

This must remain green with no product artifacts required by the legacy verifier.

- [ ] **Step 7: Add dedicated product CI workflow**

Create `.github/workflows/product-mp4.yml` with Python 3.11, Ubuntu latest, apt-installed FFmpeg, and `pip install -e '.[test,signature]'`.

The workflow must run:

```bash
python -m pytest -q
python -m py_compile \
  ald_core.py \
  ald_hardened_core.py \
  ald_media_codecs.py \
  ald_media_staging.py \
  ald_compression.py \
  ald_media_controller.py \
  ald_media_cli.py \
  ald_hls_integration.py \
  ald_hls_packaging.py \
  ald_hls_bundle.py \
  ald_hls_signature.py \
  ald_hls_verify.py \
  ald_product_scene.py \
  ald_product_svg.py \
  ald_product_data.py \
  ald_product_render.py \
  ald_product_mp4.py \
  ald_product_bundle.py \
  ald_product_verify.py
```

Then run the end-to-end command sequence from Step 5 and byte-compare direct/product simulation reports.

- [ ] **Step 8: Update README product-mode documentation**

Add a mode comparison table:

| Mode | Human visual | Executable source | Independent checksum | Container |
| --- | --- | --- | --- | --- |
| Direct | reports only | canonical recipe | ALD1 hash chain | none |
| QR media | QR instruction frame | decoded QR bytes | BFSK audio | HLS/fMP4 |
| Product MP4 | Majorana 2 schematic product stage | MP4 `bin_data/gpmd` slots | BFSK audio | single MP4 bundle |

Add the exact compile/verify/simulate-product commands from Step 5.

State explicitly that `gpmd` is used as the FFmpeg/MP4 `bin_data` transport tag; the payload itself is the repository's `ALDP` version-1 slot format, not GoPro GPMF telemetry.

State that the video track is display-only and cannot be executed through OCR.

- [ ] **Step 9: Update Majorana 2 reference documentation**

In `docs/majorana2-public-spec-reference.md`, document:

- H-shaped tetron/gates/dots/material stack are public-reference visualization metadata;
- unknown barrier/buffer/process fields remain unspecified;
- normalized SVG/Pillow drawing coordinates are schematic presentation coordinates, not fabrication dimensions;
- the generic A/B simulator overlay is synthetic and `physical_fabrication_mapping` remains false;
- product-MP4 instruction bytes are the same canonical ALD-MEDIA/1 surrogate packets already used by direct/QR modes.

- [ ] **Step 10: Run the complete local verification matrix**

Run:

```bash
python -m pytest -q
python -m py_compile \
  ald_core.py ald_hardened_core.py ald_media_codecs.py ald_media_staging.py \
  ald_compression.py ald_media_controller.py ald_media_cli.py \
  ald_hls_integration.py ald_hls_packaging.py ald_hls_bundle.py \
  ald_hls_signature.py ald_hls_verify.py \
  ald_product_scene.py ald_product_svg.py ald_product_data.py \
  ald_product_render.py ald_product_mp4.py ald_product_bundle.py \
  ald_product_verify.py
```

Then manually run both end-to-end modes:

```bash
rm -rf build/final-product-check build/final-qr-check

ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/final-product-check/bundle
ald-media-controller verify-product build/final-product-check/bundle/bundle.json
ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/final-product-check/direct
ald-media-controller simulate-product \
  build/final-product-check/bundle/bundle.json \
  --seed 42 \
  --output build/final-product-check/media
cmp build/final-product-check/direct/cycles.csv build/final-product-check/media/cycles.csv
cmp build/final-product-check/direct/surface-final.json build/final-product-check/media/surface-final.json

ald-media-controller compile recipes/generic_al2o3.json --output build/final-qr-check/bundle
ald-media-controller verify build/final-qr-check/bundle/stream.m3u8
```

Expected: every command exits 0, both direct/product report comparisons are byte-identical, and legacy QR verification still succeeds.

- [ ] **Step 11: Inspect the final MP4 independently with ffprobe**

Run:

```bash
ffprobe -v error \
  -show_entries stream=index,codec_type,codec_name,codec_tag_string,width,height,sample_rate,channels \
  -of json \
  build/final-product-check/bundle/product.mp4
```

Expected stream set:

```text
video: h264, 1920x1080
audio: aac, 48000 Hz, mono
data:  bin_data, codec tag gpmd
```

Then inspect data packet timing:

```bash
ffprobe -v error \
  -select_streams d:0 \
  -show_packets \
  -show_entries packet=pts_time,duration_time,size \
  -of json \
  build/final-product-check/bundle/product.mp4
```

Expected: one 1024-byte packet per canonical instruction at 3-second intervals, no guard packet.

- [ ] **Step 12: Commit Task 5**

```bash
git add \
  ald_media_cli.py ald_media_controller.py pyproject.toml \
  tests/test_product_cli.py .github/workflows/product-mp4.yml \
  README.md docs/majorana2-public-spec-reference.md
git commit -m "feat: add verified Majorana 2 product MP4 mode"
```

---

## Final Review Gate

Before opening or merging the implementation PR:

- run the complete test/compile/end-to-end matrix in Task 5;
- confirm `git diff main...HEAD -- recipes/majorana2_public_specs_reference_sim.json` does not add physical fabrication parameters;
- confirm the product verifier never calls `decode_instruction_frame()` or OCR;
- confirm the legacy HLS verifier still accepts bundles produced by the unchanged `compile` command;
- confirm product bundle verification rejects modified video, audio, data, product JSON, SVG, recipe, and manifest artifacts;
- confirm the final product MP4 visibly contains the H-tetron, gate layers, quantum-dot labels, and material-stack view;
- confirm `product.json` contains `physical_fabrication_mapping:false`;
- confirm `ffprobe` reports exactly one H.264 video stream, one AAC audio stream, and one `bin_data/gpmd` data stream;
- confirm direct/product simulation reports are byte-identical at seed 42.

When all checks are green, request code review on the exact verified head before merge.
