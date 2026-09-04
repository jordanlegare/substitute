# Majorana 2 Product-MP4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified `product.mp4` mode that renders a recognizable Majorana 2 public-reference product view, carries the existing canonical ALD packet stream in a synchronized MP4 `bin_data/gpmd` track, preserves BFSK checksum audio, and leaves the existing QR/HLS mode unchanged.

**Architecture:** Reuse the canonical recipe compiler, ALD1 hash chain, simulator, BFSK codec, local FFmpeg boundary, transactional publication, and simulator packet interface. Add deterministic product scene/SVG/raster modules, a fixed 1024-byte timed binary packet-slot protocol, an FFmpeg bridge that timestamps raw slots with `setts`, stages them through MPEG-TS as `bin_data`, remuxes them into the final MP4 as `gpmd`, and a product-specific manifest/verifier that returns the same `HashedPacket` objects used by direct and QR-media simulation.

**Tech Stack:** Python 3.10+, stdlib `dataclasses`/`hashlib`/`json`/`struct`/`wave`/`zlib`, NumPy, Pillow, existing Manchester/BFSK codecs, FFmpeg/ffprobe, pytest, optional `cryptography` Ed25519 support.

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
- Python floor remains 3.10 and current dependency bounds remain unchanged.
- Reuse the fixed existing media profile: 1920x1080, 3.0-second packet intervals, mono 48 kHz audio, 1200 symbols/s, 1200/2400 Hz carriers, three BFSK copies with two required matches.
- Product data slots are exactly 1024 bytes; canonical packet payloads remain bounded to 800 bytes.
- Product bundle protocol is `ALD-PRODUCT/1`; scene protocol is `ALD-PRODUCT-SCENE/1`; product data version is 1.

## File Structure

Create:

- `ald_product_scene.py` — strict public-reference extraction, immutable scene/document model, canonical `product.json` parser/serializer.
- `ald_product_svg.py` — deterministic top/stack/final SVG serialization.
- `ald_product_data.py` — fixed 1024-byte timed packet-slot codec.
- `ald_product_render.py` — deterministic Pillow frames and concatenated BFSK WAV.
- `ald_product_mp4.py` — FFmpeg capability proof, MPEG-TS `bin_data` staging, final MP4 mux/probe/demux helpers.
- `ald_product_bundle.py` — canonical product `bundle.json` writer and artifact digests.
- `ald_product_verify.py` — fail-closed product bundle verification.
- `tests/test_product_scene.py`
- `tests/test_product_data.py`
- `tests/test_product_mp4.py`
- `tests/test_product_verification.py`
- `tests/test_product_cli.py`
- `.github/workflows/product-mp4.yml`

Modify:

- `ald_media_codecs.py` — expose canonical packet-byte parsing and hashed-packet validation for reuse.
- `ald_hls_signature.py` — allow an explicit expected bundle-key schema while preserving the HLS schema default.
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

- Consumes: validated `core.Recipe`; optional successful `core.SimulationResult` for explicitly labeled synthetic overlays.
- Produces:
  - `ProductLayer`
  - `ProductTetron`
  - `ProductGateLayer`
  - `ProductQuantumDot`
  - `SimulationOverlay`
  - `ProductScene`
  - `ProductDocument`
  - `build_product_scene(recipe: core.Recipe, *, stage: str, simulation: core.SimulationResult | None = None) -> ProductScene`
  - `build_product_document(scene: ProductScene, *, recipe_sha256: bytes, root_hash: bytes, view_sha256: Mapping[str, str]) -> ProductDocument`
  - `canonical_product_json(document: ProductDocument) -> bytes`
  - `parse_product_json(raw: bytes) -> ProductDocument`
  - `render_top_svg(scene: ProductScene) -> bytes`
  - `render_stack_svg(scene: ProductScene) -> bytes`
  - `render_final_svg(scene: ProductScene) -> bytes`
  - `write_product_svgs(scene: ProductScene, root: Path) -> Mapping[str, Path]`

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


def test_product_scene_rejects_recipe_without_public_reference_metadata():
    generic = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    with pytest.raises(core.RecipeError, match="public_device_reference"):
        build_product_scene(generic, stage="final")
```

- [ ] **Step 2: Run the new test and confirm RED**

Run:

```bash
python -m pytest -q tests/test_product_scene.py
```

Expected: import failure for `ald_product_scene`.

- [ ] **Step 3: Implement immutable scene/document types and strict extraction**

In `ald_product_scene.py` define:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType

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


@dataclass(frozen=True)
class ProductDocument:
    scene: ProductScene
    recipe_sha256: bytes
    root_hash: bytes
    view_sha256: Mapping[str, str]
```

`build_product_scene()` must require exact `False` at `recipe.metadata["simulation_mapping"]["physical_fabrication_mapping"]`. Read the public device values only from `recipe.metadata["public_device_reference"]`.

Build the layer sequence as:

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

If future source metadata supplies a buffer/barrier composition or thickness, preserve that source value; never derive it from adjacent layers.

Construct three gate layers directly from the public `functions` list. Construct QD1-QD5 as schematic identities only; do not store invented physical coordinates. Mark exactly three QDs as shared with vertical neighbors.

For stages `simulation-status` and `final`, a supplied simulation must be successful, `simulation.seed` must be an exact `int`, and the overlay uses final `coverage`, `thickness_nm`, and `defect_fraction`. No other scene fields are derived from simulator state.

- [ ] **Step 4: Write deterministic SVG tests**

Add:

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

In `ald_product_svg.py`, write XML directly with `xml.sax.saxutils.escape`. Use a fixed 1600x900 viewBox, fixed attribute order, integer presentation coordinates, LF line endings, no timestamps, and no random element IDs.

Top view requirements:

- two horizontal nanowire rectangles;
- one central vertical backbone forming an H;
- three schematic gate bands;
- five dot circles labeled QD1-QD5;
- public tetron dimensions as text annotations;
- banner `PUBLIC-REFERENCE SCHEMATIC — NOT A FABRICATION RECIPE`.

Stack view requirements:

- layers in semantic order;
- exact text `UNSPECIFIED` for unknown layer material/thickness;
- known 6 nm, 2 nm, and 10 nm values shown as labels;
- unknown layers get a fixed display height only, never a fabricated numeric thickness.

Final view combines the top and stack concepts and contains `physical_fabrication_mapping=false` as text.

- [ ] **Step 6: Implement canonical product document serialization and parsing**

`build_product_document()` validates exact 32-byte recipe/root digests and exactly these view keys: `top`, `stack`, `final`. Each view digest must be lowercase 64-character hex.

`canonical_product_json()` serializes this exact shape:

```python
payload = {
    "gate_layers": [
        {"function": item.function, "index": item.index, "schematic": item.schematic}
        for item in document.scene.gate_layers
    ],
    "layers": [
        {
            "material": item.material,
            "role": item.role,
            "specified": item.specified,
            "thickness_nm": item.thickness_nm,
        }
        for item in document.scene.layers
    ],
    "packet_root_hash": document.root_hash.hex(),
    "physical_fabrication_mapping": False,
    "protocol": "ALD-PRODUCT-SCENE/1",
    "quantum_dots": [
        {
            "index": item.index,
            "label": item.label,
            "schematic": item.schematic,
            "shared_with_vertical_neighbor": item.shared_with_vertical_neighbor,
        }
        for item in document.scene.quantum_dots
    ],
    "recipe_id": document.scene.recipe_id,
    "recipe_sha256": document.recipe_sha256.hex(),
    "reference_status": document.scene.reference_status,
    "reference_target": document.scene.reference_target,
    "scientific_caveat": document.scene.scientific_caveat,
    "simulation_overlay": None if document.scene.overlay is None else {
        "coverage": document.scene.overlay.coverage,
        "defect_fraction": document.scene.overlay.defect_fraction,
        "label": document.scene.overlay.label,
        "seed": document.scene.overlay.seed,
        "thickness_nm": document.scene.overlay.thickness_nm,
    },
    "stage": document.scene.stage,
    "tetron": {
        "backbone_length_um": document.scene.tetron.backbone_length_um,
        "backbone_width_nm": document.scene.tetron.backbone_width_nm,
        "horizontal_nanowire_length_um": document.scene.tetron.horizontal_nanowire_length_um,
        "horizontal_nanowire_width_nm": document.scene.tetron.horizontal_nanowire_width_nm,
        "horizontal_nanowires": document.scene.tetron.horizontal_nanowires,
        "shape": document.scene.tetron.shape,
        "target_majorana_zero_modes": document.scene.tetron.target_majorana_zero_modes,
    },
    "unspecified_fields": list(document.scene.unspecified_fields),
    "views": dict(sorted(document.view_sha256.items())),
}
return (
    json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    + "\n"
).encode("utf-8")
```

`parse_product_json()` must reject duplicate keys, nonfinite numbers, unexpected/missing fields, noncanonical JSON, `physical_fabrication_mapping` values other than exact `False`, malformed digests, invalid stage names, and invalid typed nested records. It returns a `ProductDocument` that reserializes byte-identically.

- [ ] **Step 7: Run Task 1 tests and package modules**

Add `ald_product_scene` and `ald_product_svg` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py
python -m py_compile ald_product_scene.py ald_product_svg.py
python -m pytest -q tests/test_ald_media_controller.py tests/test_media_codecs.py tests/test_phase_one_acceptance.py
```

Expected: all commands pass.

- [ ] **Step 8: Commit Task 1**

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

- Consumes: exact `core.HashedPacket` objects.
- Produces:
  - public `ald_media_codecs.validate_hashed_packet(item: core.HashedPacket) -> None`
  - public `ald_media_codecs.decode_canonical_packet_bytes(payload: bytes) -> core.Packet`
  - `ProductDataRecord`
  - `encode_product_slot(item: core.HashedPacket, *, pts_ms: int, duration_ms: int) -> bytes`
  - `decode_product_slot(slot: bytes) -> ProductDataRecord`
  - `build_product_slots(compiled: core.CompiledRecipe, *, interval_ms: int = 3000) -> tuple[bytes, ...]`
  - `write_product_slot_stream(compiled: core.CompiledRecipe, destination: Path, *, interval_ms: int = 3000, include_guard: bool = True) -> Path`

- [ ] **Step 1: Promote shared packet validators without semantic changes**

Add tests in `tests/test_media_codecs.py` that call the promoted functions:

```python
from ald_media_codecs import decode_canonical_packet_bytes, validate_hashed_packet


def test_public_packet_helpers_accept_compiled_packet(compiled_recipe):
    item = compiled_recipe.packets[0]
    validate_hashed_packet(item)
    decoded = decode_canonical_packet_bytes(item.canonical_bytes)
    assert core.canonical_packet_bytes(decoded) == item.canonical_bytes
```

Rename `_validate_hashed_packet` to `validate_hashed_packet` and `_decode_canonical_packet` to `decode_canonical_packet_bytes`. Update QR functions to call the promoted names. Run:

```bash
python -m pytest -q tests/test_media_codecs.py
```

Expected: all existing and new codec tests pass.

- [ ] **Step 2: Write RED product slot tests**

Create `tests/test_product_data.py`:

```python
from pathlib import Path

import pytest

import ald_hardened_core as core
from ald_product_data import DATA_SLOT_BYTES, build_product_slots, decode_product_slot, encode_product_slot


RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def compiled_recipe() -> core.CompiledRecipe:
    recipe = core.validate_recipe(core.load_recipe(RECIPE))
    return core.compile_recipe(recipe)


def test_product_slot_is_fixed_size_and_round_trips():
    item = compiled_recipe().packets[0]
    slot = encode_product_slot(item, pts_ms=0, duration_ms=3000)
    record = decode_product_slot(slot)
    assert len(slot) == DATA_SLOT_BYTES == 1024
    assert record.sequence == 0
    assert record.pts_ms == 0
    assert record.duration_ms == 3000
    assert record.canonical_bytes == item.canonical_bytes
    assert record.digest == item.digest
    assert core.canonical_packet_bytes(record.packet) == item.canonical_bytes


def test_product_slots_have_contiguous_timeline():
    compiled = compiled_recipe()
    records = tuple(decode_product_slot(slot) for slot in build_product_slots(compiled))
    assert [record.sequence for record in records] == list(range(len(compiled.packets)))
    assert [record.pts_ms for record in records] == [index * 3000 for index in range(len(records))]
    assert [record.duration_ms for record in records] == [3000] * len(records)
```

Run:

```bash
python -m pytest -q tests/test_product_data.py
```

Expected: import failure for `ald_product_data`.

- [ ] **Step 3: Implement the exact binary envelope**

In `ald_product_data.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

import ald_hardened_core as core
from ald_media_codecs import decode_canonical_packet_bytes, validate_hashed_packet


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

The exact slot layout is:

```text
4 bytes  magic ALDP
1 byte   version 1
4 bytes  sequence, unsigned big endian
8 bytes  pts_ms, unsigned big endian
4 bytes  duration_ms, unsigned big endian
2 bytes  canonical packet length, unsigned big endian
32 bytes ALD1 chained packet digest
N bytes  canonical packet bytes, N <= 800
4 bytes  CRC-32 over header plus canonical packet bytes
zero bytes through offset 1023
```

Implementation core:

```python
def encode_product_slot(item: core.HashedPacket, *, pts_ms: int, duration_ms: int) -> bytes:
    validate_hashed_packet(item)
    if type(pts_ms) is not int or not 0 <= pts_ms <= (2**63 - 1):
        raise core.RecipeError("product PTS must be a non-negative 63-bit integer")
    if type(duration_ms) is not int or not 1 <= duration_ms <= (2**32 - 1):
        raise core.RecipeError("product duration must be a positive 32-bit integer")
    if len(item.canonical_bytes) > MAX_CANONICAL_BYTES:
        raise core.RecipeError("canonical packet exceeds product slot limit")
    body = _HEADER.pack(
        DATA_MAGIC,
        DATA_VERSION,
        item.packet.sequence,
        pts_ms,
        duration_ms,
        len(item.canonical_bytes),
        item.digest,
    ) + item.canonical_bytes
    encoded = body + _CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
    if len(encoded) > DATA_SLOT_BYTES:
        raise core.RecipeError("product record exceeds fixed slot")
    return encoded + bytes(DATA_SLOT_BYTES - len(encoded))
```

`decode_product_slot()` requires exact `bytes`, exact 1024-byte length, exact magic/version, valid positive duration, payload length <= 800, CRC match, zero-only padding, canonical packet parse success, and matching envelope/packet sequence.

- [ ] **Step 4: Add corruption and bound tests**

Add explicit tests for wrong magic, wrong version, sequence mismatch, zero duration, oversized declared packet length, corrupted packet bytes, corrupted digest, bad CRC, nonzero padding, truncation, and trailing bytes.

Use this mutation pattern:

```python
@pytest.mark.parametrize("offset", [0, 4, 8, 24, 60, 100])
def test_product_slot_rejects_single_byte_corruption(offset):
    item = compiled_recipe().packets[0]
    slot = bytearray(encode_product_slot(item, pts_ms=0, duration_ms=3000))
    slot[offset] ^= 1
    with pytest.raises(core.ALDError):
        decode_product_slot(bytes(slot))
```

- [ ] **Step 5: Implement deterministic slot stream and guard**

`build_product_slots()` emits one real slot per compiled packet with `pts_ms = sequence * interval_ms` and `duration_ms = interval_ms`.

`write_product_slot_stream(..., include_guard=True)` writes all real slots followed by one all-zero 1024-byte guard. The guard exists only to provide a following timestamp for the final real MPEG-TS packet. Task 3 must prove the supported FFmpeg profile discards the guard from final MP4. Product verification rejects any extra data packet.

- [ ] **Step 6: Run and commit Task 2**

Add `ald_product_data` to `pyproject.toml`, then run:

```bash
python -m pytest -q tests/test_product_data.py tests/test_media_codecs.py
python -m py_compile ald_product_data.py ald_media_codecs.py
```

Expected: all commands pass.

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

- Consumes: compiled recipe, successful simulation, fixed media profile, scene builder, product slot stream, existing BFSK encoder, existing `MediaCapabilities` and `run_media_tool()`.
- Produces:
  - `ProductTrackSources`
  - `ProductPacketTiming`
  - `ProductMP4Probe`
  - `stage_product_tracks(compiled: core.CompiledRecipe, simulation: core.SimulationResult, root: Path, profile: media.MediaProfile) -> ProductTrackSources`
  - `probe_product_mp4_capabilities(capabilities: MediaCapabilities) -> None`
  - `mux_product_mp4(sources: ProductTrackSources, destination: Path, capabilities: MediaCapabilities, profile: media.MediaProfile) -> Path`
  - `probe_product_mp4(path: Path, capabilities: MediaCapabilities, *, packet_count: int, interval_seconds: float) -> ProductMP4Probe`
  - `extract_product_data(path: Path, destination: Path, capabilities: MediaCapabilities) -> Path`
  - `extract_product_audio(path: Path, destination: Path, capabilities: MediaCapabilities) -> Path`

- [ ] **Step 1: Write RED staging tests**

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
    simulation = core.SimulatedALDController().execute(compiled, 42)
    assert simulation.fault is None
    return compiled, simulation


def test_product_staging_generates_one_visual_interval_per_packet(tmp_path):
    compiled, simulation = compile_and_simulate()
    sources = stage_product_tracks(compiled, simulation, tmp_path, media.DEFAULT_MEDIA_PROFILE)
    frames = sorted(sources.frame_dir.glob("frame-*.png"))
    assert len(frames) == len(compiled.packets)
    assert sources.packet_count == len(compiled.packets)
    assert sources.duration_seconds == len(compiled.packets) * 3.0
    with Image.open(frames[-1]) as image:
        assert image.size == (1920, 1080)
```

Add a monkeypatch test that replaces `media.render_instruction_frame` with a function that raises `AssertionError`; `stage_product_tracks()` must still pass.

- [ ] **Step 2: Implement deterministic product frames and full BFSK WAV**

Use this exact opcode-stage map:

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

Each 1920x1080 Pillow frame includes the H tetron, gate bands, QD labels, stack context, packet sequence/opcode as status text, and the banner `PUBLIC-REFERENCE SCHEMATIC — NOT A FABRICATION RECIPE`. For `simulation-status` and `final`, include final synthetic coverage/thickness/defect values and seed with label `synthetic simulator status`. Do not call QR rendering or embed command payloads in pixels.

Build the full checksum audio as:

```python
intervals = [
    media.encode_checksum_audio(item.packet.sequence, item.digest, profile)
    for item in compiled.packets
]
samples = np.concatenate(intervals)
pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
```

Write mono 16-bit PCM at 48 kHz and require exact frame count `packet_count * 3 * 48000` for the fixed profile.

Write `packet-slots.bin` with Task 2's guard slot.

- [ ] **Step 3: Write a real FFmpeg capability test for the data bridge**

Mark the test `requires_ffmpeg`. `probe_product_mp4_capabilities()` creates two deterministic real 1024-byte slots plus one zero guard and runs the following exact raw-data staging argv, substituting only resolved executable paths:

```python
stage_args = [
    str(capabilities.ffmpeg),
    "-hide_banner",
    "-loglevel", "error",
    "-f", "data",
    "-raw_packet_size", "1024",
    "-i", str(slot_path),
    "-map", "0:0",
    "-c", "copy",
    "-bsf:0", "setts=pts=N*3000:dts=N*3000:duration=3000:time_base=1/1000",
    "-f", "mpegts",
    "-y", str(data_ts),
]
```

Then create a six-second test MP4 with lavfi video/audio and the staged data:

```python
mux_args = [
    str(capabilities.ffmpeg),
    "-hide_banner",
    "-loglevel", "error",
    "-f", "lavfi",
    "-i", "color=c=black:s=320x240:r=1:d=6",
    "-f", "lavfi",
    "-i", "anullsrc=r=48000:cl=mono:d=6",
    "-i", str(data_ts),
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-map", "2:d:0",
    "-c:v", capabilities.video_encoder,
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    "-c:d", "copy",
    "-copy_unknown",
    "-tag:d:0", "gpmd",
    "-metadata:s:d:0", "handler_name=ALD Instruction Data",
    "-movflags", "+faststart",
    "-y", str(product_mp4),
]
```

Probe with ffprobe and require exactly one H.264 video, one AAC audio, and one `codec_type=data`, `codec_name=bin_data`, `codec_tag_string=gpmd` stream.

Extract the data stream with:

```python
extract_args = [
    str(capabilities.ffmpeg),
    "-hide_banner",
    "-loglevel", "error",
    "-i", str(product_mp4),
    "-map", "0:d:0",
    "-c", "copy",
    "-f", "data",
    "-y", str(extracted),
]
```

Require `extracted.read_bytes()` to equal the two real slots exactly; the zero guard must not be present. Require two ffprobe data packets, each size 1024, with PTS 0 and 3 seconds and duration 3 seconds within 50 ms. Any failure raises `core.DependencyError`; there is no alternate subtitle/OCR/sidecar mode.

- [ ] **Step 4: Run the capability test before implementing real muxing**

Run:

```bash
python -m pytest -q tests/test_product_mp4.py -m requires_ffmpeg
```

Expected: the capability proof is green on the supported CI FFmpeg build.

- [ ] **Step 5: Implement final `product.mp4` muxing**

Stage `data.ts` with the exact `setts` command from Step 3. Use product PNGs as input 0, checksum WAV as input 1, and `data.ts` as input 2.

The final argv shape is:

```python
args = [
    str(capabilities.ffmpeg),
    "-hide_banner",
    "-loglevel", "error",
    "-framerate", "1/3",
    "-start_number", "0",
    "-i", str(sources.frame_dir / "frame-%06d.png"),
    "-i", str(sources.checksum_wav),
    "-i", str(data_ts),
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-map", "2:d:0",
    "-c:v", capabilities.video_encoder,
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    "-c:d", "copy",
    "-copy_unknown",
    "-tag:d:0", "gpmd",
    "-metadata:s:d:0", "handler_name=ALD Instruction Data",
    "-movflags", "+faststart",
    "-y", str(destination),
]
```

Do not add `-shortest`; FFmpeg must read the trailing guard so the final real data packet receives a duration, while the guard itself is discarded by the accepted profile.

`probe_product_mp4()` rejects output unless:

- video is H.264, 1920x1080;
- audio is AAC, mono, 48 kHz;
- data is `bin_data/gpmd`;
- stream counts are exactly one video, one audio, one data;
- data packet count equals canonical packet count;
- every data packet is 1024 bytes;
- PTS values are `sequence * 3.0` seconds within 0.05 seconds;
- duration values are 3.0 seconds within 0.05 seconds;
- media duration covers the final packet interval.

- [ ] **Step 6: Add end-to-end track tests**

Add a real Majorana recipe test that stages sources, muxes `product.mp4`, probes it, extracts its data stream, splits it into 1024-byte slots, decodes every slot, and compares `canonical_bytes` and `digest` with `compiled.packets`.

Run:

```bash
python -m pytest -q tests/test_product_scene.py tests/test_product_data.py tests/test_product_mp4.py
python -m py_compile ald_product_render.py ald_product_mp4.py
```

Expected: all tests pass.

- [ ] **Step 7: Package and commit Task 3**

Add `ald_product_render` and `ald_product_mp4` to `pyproject.toml`.

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

- Produces:
  - `PRODUCT_BUNDLE_KEYS`
  - `write_product_bundle_index(...) -> Path` implemented with explicit arguments listed in Step 3
  - `VerifiedProductRecipe`
  - `verify_product_bundle(index_path: Path, *, require_signature: bool = False, trusted_public_key: Path | None = None) -> VerifiedProductRecipe`
- Existing HLS signature calls remain source-compatible.

- [ ] **Step 1: Generalize the signature parser with an explicit schema argument**

Change the HLS constant to `_HLS_BUNDLE_KEYS` and define:

```python
def sign_bundle_index(
    index_path: Path,
    private_key_path: Path,
    *,
    expected_keys: frozenset[str] = _HLS_BUNDLE_KEYS,
) -> BundleSignature:
    bundle, _ = _load_bundle(Path(index_path), expected_keys=expected_keys)
    return _sign_loaded_bundle(bundle, Path(index_path), Path(private_key_path))


def verify_bundle_signature_bytes(
    bundle_bytes: bytes,
    trusted_public_key: Path,
    *,
    expected_keys: frozenset[str] = _HLS_BUNDLE_KEYS,
) -> SignatureStatus:
    bundle, _ = _parse_bundle_bytes(bundle_bytes, expected_keys=expected_keys)
    return _verify_loaded_bundle(bundle, trusted_public_key)
```

Refactor existing private helpers so the only semantic change is schema selection. Keep `ALD-BUNDLE-SIGNATURE\x00` unchanged. Add regression tests and run:

```bash
python -m pytest -q tests/test_hls_verification.py
```

Expected: all existing HLS tests pass.

- [ ] **Step 2: Define the exact product manifest schema**

In `ald_product_bundle.py`:

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

Nested shapes are exact:

```python
product_record = {"path": "product.mp4", "sha256": hashlib.sha256(product_bytes).hexdigest()}
recipe_record = {"path": "recipe.canonical.json", "sha256": hashlib.sha256(recipe_bytes).hexdigest()}
scene_record = {"path": "product.json", "sha256": hashlib.sha256(scene_bytes).hexdigest()}
view_records = {
    "final": {"path": "product-final.svg", "sha256": hashlib.sha256(final_svg).hexdigest()},
    "stack": {"path": "product-stack.svg", "sha256": hashlib.sha256(stack_svg).hexdigest()},
    "top": {"path": "product-top.svg", "sha256": hashlib.sha256(top_svg).hexdigest()},
}
```

Packet entries are:

```python
packet_records = [
    {
        "digest": item.digest.hex(),
        "duration_ms": 3000,
        "pts_ms": item.packet.sequence * 3000,
        "sequence": item.packet.sequence,
    }
    for item in compiled.packets
]
```

Product `media_profile` keys are exactly `width`, `height`, `interval_seconds`, `sample_rate`, `symbol_rate`, `mark_hz`, `space_hz`, `copies`, `required_matching_copies`. Product `ffmpeg` keys are exactly `version`, `video_encoder`, `audio_encoder`, `data_codec`, `data_tag` with `data_codec="bin_data"` and `data_tag="gpmd"`.

- [ ] **Step 3: Implement canonical atomic index writing**

Define this interface:

```python
def write_product_bundle_index(
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
) -> Path:
```

Reject symlinks/missing/non-regular files, require exact `int` render seed, hash final bytes, use only relative fixed artifact names, initialize `signature=None`, serialize canonical sorted compact JSON plus LF, and publish atomically inside the candidate bundle.

- [ ] **Step 4: Write RED tamper tests**

Build one real Majorana candidate bundle at seed 42. Add separate tests that mutate:

- one byte in `product.mp4`;
- one byte in `product.json`;
- each SVG individually;
- `recipe.canonical.json`;
- one packet digest in `bundle.json`;
- one packet PTS;
- one packet duration;
- one top-level manifest key;
- one bound artifact replaced with a symlink;
- one extracted/rebuilt data slot with the manifest MP4 digest updated;
- one audio interval with the manifest MP4 digest updated.

Each test requires `IntegrityError` and no returned packet stream.

- [ ] **Step 5: Implement strict product manifest/artifact parsing**

In `ald_product_verify.py`:

```python
from dataclasses import dataclass

import ald_hardened_core as core
import ald_media_codecs as media
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

Require exact artifact filenames:

```text
product.mp4
recipe.canonical.json
product.json
product-top.svg
product-stack.svg
product-final.svg
```

Reject duplicate JSON keys, nonfinite numbers, unexpected/missing fields, noncanonical JSON, unsafe relative paths, symlinks, digest mismatches, invalid render seed, and media profile drift.

- [ ] **Step 6: Verify MP4 stream structure and packet timing before extracting instructions**

Call `probe_product_mp4()` and compare each data packet to manifest packet metadata with:

```python
if abs(actual.pts_seconds - expected["pts_ms"] / 1000.0) > 0.05:
    raise IntegrityError("product data PTS mismatch")
if abs(actual.duration_seconds - expected["duration_ms"] / 1000.0) > 0.05:
    raise IntegrityError("product data duration mismatch")
if actual.size != 1024:
    raise IntegrityError("product data packet size mismatch")
```

Reject extra, missing, reordered, duplicate, or zero-duration samples.

- [ ] **Step 7: Extract and verify authoritative instruction slots**

Use `extract_product_data()`. Require byte length `len(packet_records) * 1024` and split on exact slot boundaries.

For each index:

```python
record = decode_product_slot(slot)
if record.sequence != index:
    raise IntegrityError("product data sequence discontinuity")
if record.pts_ms != packet_record["pts_ms"] or record.duration_ms != packet_record["duration_ms"]:
    raise IntegrityError("product data timeline does not match bundle index")
expected_digest = core.hash_packet(previous_digest, record.canonical_bytes)
if record.digest != expected_digest or record.digest.hex() != packet_record["digest"]:
    raise IntegrityError("product data digest mismatch")
verified_packets.append(
    core.HashedPacket(
        packet=record.packet,
        canonical_bytes=record.canonical_bytes,
        previous_digest=previous_digest,
        digest=record.digest,
    )
)
previous_digest = record.digest
```

Require final `previous_digest` equals manifest root hash.

- [ ] **Step 8: Decode the full AAC track and require one matching BFSK witness per interval**

Use `extract_product_audio()` to produce mono 48 kHz PCM WAV. Read all samples and require exact length `packet_count * 144000` for the fixed 3-second profile.

For each interval:

```python
start = sequence * 144000
stop = start + 144000
audio_record = media.decode_checksum_audio(samples[start:stop], profile)
if audio_record.sequence != sequence or audio_record.digest != verified_packets[sequence].digest:
    raise IntegrityError("product audio witness does not match product data")
```

Do not decode QR or OCR video pixels.

- [ ] **Step 9: Recompile bound recipe bytes and require exact packet identity**

Stage bound recipe bytes into a private temporary `recipe.canonical.json`, run existing load/validate/compile, and compare packet count, every canonical byte string, every previous digest, every digest, and root hash to the data-track-derived packet stream.

- [ ] **Step 10: Parse product JSON and re-render bound SVGs**

Call `parse_product_json(product_bytes)`. Require:

- scene protocol `ALD-PRODUCT-SCENE/1`;
- recipe ID equals the bound recipe;
- `physical_fabrication_mapping is False`;
- recipe SHA-256 equals canonical recipe bytes;
- packet root equals verified root;
- view digests equal manifest SVG digests;
- simulation overlay exists and overlay seed equals manifest `render_seed`.

Re-render top/stack/final SVG bytes from `document.scene` and require byte equality with each bound SVG.

- [ ] **Step 11: Verify optional signatures with product schema**

Call:

```python
status = verify_bundle_signature_bytes(
    raw_bundle_bytes,
    trusted_public_key,
    expected_keys=PRODUCT_BUNDLE_KEYS,
)
```

Tests cover unsigned accepted by default, unsigned rejected when required, valid trusted signature accepted, wrong trusted key rejected, and signed manifest mutation rejected.

- [ ] **Step 12: Run and commit Task 4**

Add `ald_product_bundle` and `ald_product_verify` to `pyproject.toml`.

Run:

```bash
python -m pytest -q tests/test_product_verification.py tests/test_hls_verification.py
python -m py_compile ald_product_bundle.py ald_product_verify.py ald_hls_signature.py
```

Expected: all commands pass.

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

**Interfaces:**

- Adds:
  - `ald-media-controller compile-product RECIPE --output DIR [--seed N] [--overwrite] [--signing-key KEY]`
  - `ald-media-controller verify-product BUNDLE_JSON [--require-signature] [--trusted-public-key KEY]`
  - `ald-media-controller simulate-product BUNDLE_JSON --seed N --output DIR [--overwrite] [--require-signature] [--trusted-public-key KEY]`
- `compile-product` render seed defaults to 42.
- Existing commands remain unchanged.

- [ ] **Step 1: Write RED CLI parser tests**

Create `tests/test_product_cli.py`:

```python
from ald_media_cli import build_parser


def test_product_commands_are_explicit_and_legacy_compile_stays_legacy():
    parser = build_parser()
    product = parser.parse_args([
        "compile-product",
        "recipes/majorana2_public_specs_reference_sim.json",
        "--output",
        "build/product",
    ])
    assert product.command == "compile-product"
    assert product.seed == 42

    legacy = parser.parse_args([
        "compile",
        "recipes/generic_al2o3.json",
        "--output",
        "build/hls",
    ])
    assert legacy.command == "compile"
```

Run:

```bash
python -m pytest -q tests/test_product_cli.py
```

Expected: parser rejection for `compile-product`.

- [ ] **Step 2: Add the three explicit product subcommands**

Add `compile-product` with recipe, required output, integer `--seed` default 42, `--overwrite`, and `--signing-key`.

Add `verify-product` with bundle JSON path, `--require-signature`, and `--trusted-public-key`.

Add `simulate-product` with bundle JSON path, required integer `--seed`, required output, `--overwrite`, `--require-signature`, and `--trusted-public-key`.

Add unexpected-exception fallback mappings:

```python
"compile-product": core.ExitCode.MEDIA
"verify-product": core.ExitCode.INTEGRITY
"simulate-product": core.ExitCode.CONTROLLER
```

- [ ] **Step 3: Implement `_run_compile_product()` using the existing safe publication lifecycle**

Exact order:

1. resolve publishable target with `_require_publishable_output()`;
2. reject recipe/output overlap;
3. load, validate, and compile recipe;
4. run deterministic simulation at render seed and reject any fault;
5. probe generic media capabilities and product-MP4 capabilities;
6. create private build root under target parent;
7. create candidate `bundle` directory;
8. build final product scene with simulation overlay;
9. write `product-top.svg`, `product-stack.svg`, `product-final.svg`;
10. stage product PNG/BFSK/data inputs outside candidate publication directory;
11. mux `candidate/product.mp4`;
12. write `candidate/recipe.canonical.json` with the existing canonical recipe writer;
13. compute SVG digests, build `ProductDocument`, write canonical `candidate/product.json`;
14. write `candidate/bundle.json`;
15. if signing key is supplied, call `sign_bundle_index(..., expected_keys=PRODUCT_BUNDLE_KEYS)` and derive the temporary trusted public key with the existing helper;
16. call `verify_product_bundle(candidate / "bundle.json")` with the appropriate signature requirement;
17. compare verified packet canonical bytes/digests/root and canonical recipe bytes to the just-built inputs;
18. atomically publish candidate with `_publish_verified_bundle()`;
19. remove every private staging directory in `finally`.

Do not publish `data.ts`, PNG source frames, checksum WAV, or `packet-slots.bin`.

- [ ] **Step 4: Implement verify/simulate product orchestration**

`_run_verify_product()` prints canonical compact JSON:

```python
payload = {
    "media_type": "product-mp4",
    "packet_count": len(verified.packets),
    "protocol": "ALD-PRODUCT/1",
    "render_seed": verified.render_seed,
    "root_hash": verified.root_hash.hex(),
    "signature_status": verified.signature_status.value,
}
```

`_run_simulate_product()` verifies `bundle.json`, reuses `_bind_verified_recipe()` because `VerifiedProductRecipe` exposes `packets`, `root_hash`, and `recipe_bytes`, rejects output overlap, executes the deterministic simulator with the requested seed, and publishes existing reports.

Execution seed may differ from render seed; docs must state that the visual numeric overlay represents only the compile-time render seed.

- [ ] **Step 5: Re-export product APIs through `ald_media_controller.py`**

Import all seven product modules beside the existing sibling imports. Re-export these public groups through `setattr(_core, name, ...)` loops:

- scene/document dataclasses and scene/document builders/parsers;
- SVG render/write functions;
- data record/slot functions and constants;
- product track staging functions/dataclasses;
- product MP4 capability/mux/probe/extract functions/dataclasses;
- product bundle key constant and writer;
- product `VerifiedProductRecipe` and `verify_product_bundle`.

Also re-export `decode_canonical_packet_bytes` and `validate_hashed_packet` from `ald_media_codecs`.

Keep `_core.build_parser = _cli.build_parser`, `_core.main = _cli.main`, and module aliasing behavior unchanged.

- [ ] **Step 6: Add real CLI end-to-end test**

Mark the acceptance test `requires_ffmpeg`. Run:

```bash
ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/product-acceptance/bundle
ald-media-controller verify-product build/product-acceptance/bundle/bundle.json
ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/product-acceptance/direct
ald-media-controller simulate-product \
  build/product-acceptance/bundle/bundle.json \
  --seed 42 \
  --output build/product-acceptance/product
cmp build/product-acceptance/direct/cycles.csv build/product-acceptance/product/cycles.csv
cmp build/product-acceptance/direct/surface-final.json build/product-acceptance/product/surface-final.json
```

Require published files exactly include the seven product artifacts plus any ordinary filesystem metadata, with these required names:

```text
product.mp4
product.json
product-top.svg
product-stack.svg
product-final.svg
recipe.canonical.json
bundle.json
```

Require no `stream.m3u8` in a product bundle.

- [ ] **Step 7: Run legacy QR/HLS regression from the same implementation head**

Run:

```bash
ald-media-controller compile recipes/generic_al2o3.json --output build/qr-regression/bundle
ald-media-controller verify build/qr-regression/bundle/stream.m3u8
ald-media-controller simulate-media \
  build/qr-regression/bundle/stream.m3u8 \
  --seed 42 \
  --output build/qr-regression/media
```

Expected: unchanged behavior and successful verification/simulation.

- [ ] **Step 8: Add dedicated product CI workflow**

Create `.github/workflows/product-mp4.yml` using Ubuntu latest, Python 3.11, apt-installed FFmpeg, and `python -m pip install -e '.[test,signature]'`.

Run full pytest, then compile exactly these modules:

```bash
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

Then execute the Task 5 Step 6 product acceptance sequence and byte comparisons.

- [ ] **Step 9: Document the mode contract**

README mode table:

| Mode | Human visual | Executable source | Independent checksum | Container |
| --- | --- | --- | --- | --- |
| Direct | reports only | canonical recipe | ALD1 hash chain | none |
| QR media | QR instruction frame | decoded QR bytes | BFSK audio | HLS/fMP4 |
| Product MP4 | Majorana 2 schematic product stage | MP4 `bin_data/gpmd` slots | BFSK audio | single MP4 bundle |

Document the exact commands from Step 6. State that `gpmd` is the FFmpeg/MP4 transport tag for `bin_data`; the bytes themselves use repository-defined `ALDP` version-1 slots and are not GoPro GPMF telemetry. State that video is display-only and cannot be executed via OCR.

Update `docs/majorana2-public-spec-reference.md` to distinguish public reference metadata, schematic presentation coordinates, synthetic A/B simulator overlay, and executable canonical ALD-MEDIA/1 surrogate packets. Preserve the explicit excluded-process list and `physical_fabrication_mapping=false` statement.

- [ ] **Step 10: Run the complete verification matrix**

Run:

```bash
python -m pytest -q
python -m py_compile \
  ald_core.py ald_hardened_core.py ald_media_codecs.py ald_media_staging.py \
  ald_compression.py ald_media_controller.py ald_media_cli.py \
  ald_hls_integration.py ald_hls_packaging.py ald_hls_bundle.py \
  ald_hls_signature.py ald_hls_verify.py ald_product_scene.py \
  ald_product_svg.py ald_product_data.py ald_product_render.py \
  ald_product_mp4.py ald_product_bundle.py ald_product_verify.py
```

Then run both final acceptance paths:

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

Inspect final streams:

```bash
ffprobe -v error \
  -show_entries stream=index,codec_type,codec_name,codec_tag_string,width,height,sample_rate,channels \
  -of json \
  build/final-product-check/bundle/product.mp4
ffprobe -v error \
  -select_streams d:0 \
  -show_packets \
  -show_entries packet=pts_time,duration_time,size \
  -of json \
  build/final-product-check/bundle/product.mp4
```

Expected: one H.264 1920x1080 video stream, one mono 48 kHz AAC stream, one `bin_data/gpmd` data stream, one 1024-byte data packet per canonical instruction at three-second intervals, and no guard packet.

- [ ] **Step 11: Commit Task 5**

```bash
git add ald_media_cli.py ald_media_controller.py tests/test_product_cli.py \
  .github/workflows/product-mp4.yml README.md \
  docs/majorana2-public-spec-reference.md pyproject.toml
git commit -m "feat: add verified Majorana 2 product MP4 mode"
```

---

## Final Review Gate

Before merging the implementation PR:

- run the complete Task 5 verification matrix on the exact head;
- confirm the Majorana 2 reference recipe gained no physical fabrication parameters;
- confirm product verification never calls QR decoding or OCR;
- confirm the unchanged QR/HLS commands remain green;
- confirm product verification rejects modified video, audio, data, product JSON, SVG, recipe, and manifest artifacts;
- inspect the final visual to confirm H-tetron geometry, gate bands, five quantum-dot labels, and material stack are visible;
- confirm `product.json` contains `physical_fabrication_mapping:false`;
- confirm ffprobe reports exactly one H.264 video, one AAC audio, and one `bin_data/gpmd` data stream;
- confirm direct/product simulation reports are byte-identical at seed 42;
- request code review on the exact verified head before merge.
