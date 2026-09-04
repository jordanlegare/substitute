# Majorana 2 Product-MP4 Mode — Design Specification

**Date:** 2026-09-04  
**Status:** Approved design scope; written for implementation review  
**Scope:** Add a visual product-oriented MP4 representation while preserving the existing verified QR/BFSK HLS path and simulation-only safety boundary.

## 1. Purpose

Add a second media representation that makes the simulator output look recognizably like the public Majorana 2 reference device while still carrying the canonical executable instruction stream inside the media container.

The new representation is **product-MP4 mode**:

- the video track is human-facing and shows a deterministic product-stage visualization;
- the machine-readable canonical instruction packets move out of QR symbols and into a timed MP4 data track;
- the existing BFSK audio checksum track remains available as an independent synchronized integrity witness;
- the existing QR-based HLS/fMP4 mode remains supported and unchanged by default;
- direct simulation and all media modes continue to converge on the same verified packet objects before simulator execution.

This is a presentation and transport upgrade only. It does not turn the public Majorana 2 metadata into a physical fabrication recipe.

## 2. Approved User Requirements

The upgrade must satisfy all of the following:

1. Produce a visible product-stage representation instead of showing a QR code as the primary visual artifact.
2. Make the result recognizably Majorana2-like through:
   - gate and quantum-dot layout;
   - H-shaped tetron geometry;
   - material-layer stack.
3. Preserve JSON plus SVG views as deterministic product-description artifacts.
4. Carry machine-readable instructions in an embedded MP4 data track.
5. Preserve the current QR mode as a supported compatibility mode rather than replacing it globally.
6. Keep the implementation simulation-only and preserve the existing trust, validation, and fail-closed behavior.

## 3. Non-goals

- Reconstructing undisclosed Microsoft fabrication steps.
- Inventing precursor chemistry, lithography recipes, etch recipes, deposition parameters, cryogenic setpoints, or equipment-specific settings.
- Claiming that the generic A/B ALD surrogate physically fabricates the public Majorana 2 stack.
- Inferring atomically accurate device geometry from promotional imagery.
- Using OCR, rendered labels, or the product video pixels as an executable instruction source.
- Removing the existing QR/BFSK mode.
- Adding live industrial-machine, valve, heater, pump, precursor, robot, or network-control integration.

## 4. User-visible Modes

### 4.1 Existing QR media mode

The current path remains available:

```text
canonical packets -> QR video + BFSK audio -> HLS/fMP4 -> closed verification
```

No compatibility break is required for existing bundles, CLI usage, or verification semantics.

### 4.2 New product-MP4 mode

The new path is:

```text
recipe
  -> canonical packet compiler
  -> direct simulator checkpoints
  -> product scene builder
      -> product JSON
      -> SVG views
      -> raster video frames
  -> timed binary packet data track
  -> synchronized BFSK checksum audio
  -> single product.mp4
  -> closed product-MP4 verification
  -> same verified packet objects used by direct/QR media simulation
```

The primary human artifact is `product.mp4`. The primary deterministic structural artifacts are JSON and SVG.

## 5. Product Visualization Model

### 5.1 Source of truth

The renderer consumes two distinct inputs and must keep them visibly and structurally separate:

1. **Public device reference metadata** from `recipes/majorana2_public_specs_reference_sim.json`.
2. **Synthetic simulator state** from the existing generic A/B surface/controller model.

Reference metadata defines the recognizable device appearance. Simulator state drives progress/status overlays but must not be relabeled as physical Majorana 2 fabrication progress.

### 5.2 Required recognizable geometry

The final product scene must encode the public reference fields already present in the recipe:

- GaSb substrate.
- InAs 6 nm quantum-well layer.
- InAs0.8Sb0.2 2 nm quantum-well layer.
- Pb 10 nm superconducting layer.
- H-shaped superconducting island.
- Two horizontal nanowires.
- Public reference horizontal length and width proportions.
- Public reference backbone length and width proportions.
- Three functional gate layers.
- Five quantum dots per tetron, including the shared-neighbor relationship as a schematic annotation.

Unknown or undisclosed fields remain visually marked as unspecified rather than guessed.

### 5.3 Scene representation

Introduce a pure deterministic scene model, independent of SVG and raster output. A scene consists of primitives such as:

- layer rectangles/polygons;
- nanowire paths;
- superconducting backbone;
- gate bands/electrodes;
- quantum-dot nodes;
- labels and dimension annotations;
- simulation-status overlays;
- provenance/status banner.

The scene model is serialized to canonical JSON. SVG and raster frames are generated from the same scene object so they cannot drift semantically.

### 5.4 Views

At minimum, generate:

- `product-top.svg`: tetron, gates, and quantum-dot layout;
- `product-stack.svg`: material-layer cross-section;
- `product-final.svg`: composed final product/reference view.

The MP4 video track may alternate or transition between these views but must always remain a human visualization only.

### 5.5 Product stages

The initial implementation should use a small deterministic stage vocabulary rather than one frame per simulated atom:

1. Reference stack established.
2. H-tetron geometry introduced.
3. Gate architecture introduced.
4. Quantum-dot/readout layout introduced.
5. Simulated interface-deposition progress/status.
6. Final composed reference product view.

Simulator checkpoints update coverage/thickness/status overlays without implying an undisclosed physical process sequence.

## 6. Product Artifact Contract

A successful product-MP4 compile produces a transactional bundle directory containing:

- `product.mp4` — visual product video + instruction data track + checksum audio;
- `product.json` — canonical scene/reference/simulation summary;
- `product-top.svg`;
- `product-stack.svg`;
- `product-final.svg`;
- `recipe.canonical.json` — exact canonical recipe bytes already used by the verified media path;
- `bundle.json` — extended media manifest binding all product artifacts and the packet chain.

The product JSON must identify:

- recipe id;
- renderer/schema version;
- source recipe SHA-256;
- packet root hash;
- public-reference status;
- `physical_fabrication_mapping: false`;
- rendered view digests;
- simulator seed/checkpoint identifiers when simulation state is embedded;
- explicit list of unspecified reference fields.

## 7. MP4 Track Layout

The initial product-MP4 file contains three synchronized tracks:

1. **Video:** H.264 visual product-stage frames.
2. **Audio:** existing Manchester/BFSK checksum records, preserving the current sequence/hash integrity witness.
3. **Data:** timed binary canonical packet records.

The video track is non-executable. The data track is the authoritative media-carried instruction source.

### 7.1 Data record

Define a compact binary packet envelope with an independent magic/version so product-MP4 records cannot be confused with QR payload bytes. Conceptually:

```text
magic | version | sequence | pts_start | duration | packet_length | canonical_packet | chained_hash | crc32
```

Requirements:

- canonical packet bytes are identical to direct/QR mode canonical packet bytes;
- sequence is contiguous and unique;
- chained hash is the existing ALD1 packet-chain hash;
- CRC-32 detects local record corruption before hash-chain verification;
- record lengths and total payload are strictly bounded;
- no executable values are recovered from video pixels or text overlays.

### 7.2 Container binding

Use an ISO BMFF/MOV-compatible timed binary metadata/data track that round-trips through the project-supported FFmpeg build and is visible to `ffprobe` as a data stream.

The preferred implementation path is a `bin_data`/`gpmd`-style track because FFmpeg already recognizes such MP4 data streams in existing files. Implementation must begin with an automated capability probe that proves this exact sequence on the pinned CI FFmpeg:

1. create a deterministic binary data sample stream;
2. mux it with H.264/AAC into an intermediate MOV/MP4-compatible container;
3. produce final `.mp4`;
4. demux the data track;
5. prove byte-for-byte equality and timestamp order.

If the pinned FFmpeg cannot create a new conforming data track directly from raw binary input, the implementation may use the documented MOV staging/remux technique, but the final artifact must still be `.mp4` and verification must operate on the final encoded file.

No implementation should silently downgrade to subtitles, OCR, file-level metadata tags, or sidecar-only instructions.

### 7.3 Timing

Retain the current presentation concept: media duration is transport/presentation time, not simulated process time.

Each canonical packet gets one bounded presentation interval. Video stage frames, the packet data record, and the BFSK checksum record must overlap the same interval within an explicit synchronization tolerance.

## 8. Verification Model

Add a product-MP4 verifier parallel to the existing QR media verifier.

Before packets are returned for execution, verification must prove:

1. `product.mp4` exists and passes local path/regular-file checks.
2. The file exposes exactly the expected product video, checksum audio, and instruction data streams.
3. The data stream handler/tag/profile is on the accepted allowlist.
4. Every data record parses canonically and is within size limits.
5. Sequence numbers are contiguous, unique, and ordered.
6. Every canonical packet hash and complete ALD1 chain recompute correctly.
7. BFSK sequence/hash records agree with the data-track records.
8. Track presentation timestamps satisfy the synchronization tolerance.
9. The packet root equals `bundle.json`.
10. `recipe.canonical.json` digest equals the manifest binding.
11. Product JSON and all SVG digests equal the manifest bindings.
12. If signatures are required, the signature authenticates the exact canonical bundle-index bytes, including all product artifact digests.
13. Only after all checks pass are verified packet objects exposed to simulation.

Video contents are not part of executable instruction recovery, but their digests are integrity-bound so the displayed product cannot be swapped without detection.

## 9. CLI Design

Preserve existing commands and add explicit product-mode commands rather than changing defaults.

Recommended interface:

```text
ald-media-controller compile RECIPE --output DIR
ald-media-controller compile-product RECIPE --output DIR [--seed N]
ald-media-controller verify MANIFEST
ald-media-controller verify-product MANIFEST
ald-media-controller simulate RECIPE --seed N --output DIR
ald-media-controller simulate-media MANIFEST --seed N --output DIR
ald-media-controller simulate-product MANIFEST --seed N --output DIR
```

A later cleanup may unify verification dispatch through bundle media type, but the first implementation should keep the new path explicit and easy to test.

## 10. Component Boundaries

Keep the existing small-module direction rather than expanding `ald_media_controller.py`.

Recommended new modules:

- `ald_product_scene.py` — pure scene/reference model and canonical JSON.
- `ald_product_svg.py` — SVG serialization from scene objects.
- `ald_product_render.py` — raster/video frame rendering from the same scene model.
- `ald_product_data.py` — binary data-record encoding/decoding.
- `ald_product_mp4.py` — FFmpeg capability probe and transactional A/V/data muxing.
- `ald_product_verify.py` — final product bundle/file verification and packet recovery.

Existing modules reused without semantic duplication:

- canonical recipe compiler and ALD1 hash chain;
- QR/BFSK codec primitives where applicable;
- signature and canonical manifest machinery;
- transactional publication patterns;
- direct simulator/controller.

## 11. Error Handling

Product compilation fails closed on:

- missing public-reference metadata required by the renderer;
- non-finite or invalid scene geometry;
- out-of-range product dimensions;
- SVG/raster generation mismatch with canonical scene data;
- unsupported FFmpeg data-track capability;
- data-track mux/demux byte mismatch;
- data/audio timestamp drift;
- packet/hash/manifest/signature mismatch;
- extra or missing expected product artifacts;
- symlink/path substitution;
- final-file verification failure.

Publication remains transactional: compile into a private temporary directory, verify the final encoded product bundle, then publish atomically.

## 12. Determinism

Given the same:

- canonical recipe;
- renderer version;
- seed;
- supported FFmpeg build/profile;

`product.json` and all SVG files must be byte-identical. Raster/video elementary-stream bytes may vary across supported FFmpeg versions, so the bundle binds the actual final artifact digests produced by the compiler. Verification checks those digests rather than assuming cross-version MP4 byte identity.

The machine-readable data-track packet bytes must remain canonical and byte-identical across modes.

## 13. Tests and Acceptance Criteria

Implementation follows red/green TDD.

Minimum acceptance coverage:

### Product scene

- Majorana 2 reference recipe produces an H-shaped tetron scene.
- Scene contains two horizontal nanowires, backbone, three gate layers, and five quantum dots.
- Stack view contains GaSb, InAs 6 nm, InAs0.8Sb0.2 2 nm, and Pb 10 nm reference layers.
- Undisclosed fields remain explicit `null`/unspecified and are never filled with guessed values.
- Scene JSON and SVG outputs are deterministic.

### Data track

- Canonical packet round-trip is byte-exact.
- Sequence/hash/CRC corruption is rejected.
- Truncation, oversized records, trailing bytes, unknown versions, duplicate sequence numbers, and timestamp disorder are rejected.
- Pinned FFmpeg CI proves actual MP4 mux -> demux equality for the new data track.

### Product MP4

- Final file exposes video + audio + data tracks.
- No QR symbol is required for instruction recovery in product mode.
- Product video shows the final product reference stage.
- BFSK record agrees with the data-track packet hash.
- Modified video, audio, data, product JSON, SVG, recipe, or manifest is rejected.
- Direct simulation and verified product-MP4 simulation produce byte-identical `cycles.csv` and `surface-final.json` for the same seed.
- Existing QR/HLS acceptance suite remains green without behavior changes.

### Safety boundary

- Tests assert `physical_fabrication_mapping` remains false for the Majorana 2 reference recipe.
- Product renderer does not create executable process parameters from public reference geometry/material metadata.
- No live hardware/network control path is introduced.

## 14. Documentation

Update:

- `README.md` with a product-MP4 quick start and mode comparison.
- `docs/majorana2-public-spec-reference.md` with product-visualization semantics and caveats.
- `docs/recipe-authoring.md` only if generic recipes are allowed to provide optional product visualization metadata.

Documentation must distinguish:

- public device reference data;
- synthetic simulator parameters;
- product visualization;
- executable canonical packets;
- integrity/authentication status.

## 15. Implementation Sequence

After design approval, implementation should proceed in four reviewable phases:

1. **Scene + JSON/SVG:** deterministic reference-device scene generation and acceptance tests.
2. **Binary data protocol + FFmpeg capability proof:** data record codec and real MP4 round-trip acceptance.
3. **Product-MP4 compiler/verifier:** synchronized video/audio/data tracks, manifest binding, transactional publication.
4. **CLI/docs/integration:** commands, Majorana 2 end-to-end test, direct/product equivalence, QR compatibility regression.

Each phase should be independently green before the next phase begins.

## 16. Security and Scientific Boundary

This feature is an offline visualization, transport, verification, and simulation system. The Majorana 2 product view is a source-attributed public-reference schematic. It is not a complete device blueprint and not a validated manufacturing recipe.

The implementation must continue to preserve the recipe's explicit excluded-process list and must not convert missing process knowledge into guessed executable values.
