# Substitute — Verified Media-Encoded ALD Simulator

Substitute is an **offline atomic layer deposition (ALD) recipe compiler, deterministic simulator, and verified media-transport experiment**.

It supports three execution paths that converge on the same canonical ALD packet objects:

| Mode | Human-facing representation | Authoritative instruction source | Independent witness | Container |
| --- | --- | --- | --- | --- |
| Direct | simulation reports | canonical recipe / ALD1 packets | none | none |
| QR media | QR instruction frames | decoded QR canonical packets | BFSK sequence/digest audio | local HLS/fMP4 |
| Product MP4 | deterministic product/reference visualization | ALDP v1 timed `bin_data/gpmd` records | BFSK sequence/digest audio | one MP4 plus bound sidecars |

For a fixed canonical recipe, controller implementation, and random seed, verified-media execution is designed to produce the same deterministic simulation reports as direct execution.

> **Safety boundary**
>
> Substitute is simulation-only. It does **not** control industrial hardware, valves, heaters, pumps, mass-flow controllers, precursor delivery, PLCs, field buses, networked process equipment, or vendor safety systems. Public device metadata and generic A/B examples are not chemical-handling or machine-operation instructions.

## What can I do with it?

| Goal | Command |
| --- | --- |
| Validate a recipe | `ald-media-controller validate ...` |
| Run a deterministic simulation directly | `ald-media-controller simulate ...` |
| Build the original QR/HLS media bundle | `ald-media-controller compile ...` |
| Verify a QR/HLS bundle | `ald-media-controller verify ...` |
| Verify QR/HLS and then simulate | `ald-media-controller simulate-media ...` |
| Build a product-stage MP4 bundle | `ald-media-controller compile-product ...` |
| Verify a product-MP4 bundle | `ald-media-controller verify-product ...` |
| Verify product MP4 and then simulate | `ald-media-controller simulate-product ...` |

The product-MP4 path **adds** a product visualization mode; it does not replace the existing QR/HLS mode.

## Requirements

You need:

- Python **3.10 or newer**;
- `ffmpeg` and `ffprobe` on `PATH` for media compilation/verification;
- FFmpeg support for H.264, AAC, MP4/fMP4, and HLS;
- for product mode, FFmpeg support for timed `bin_data` in MP4 with the `gpmd` fourcc;
- the optional Python `signature` extra only for Ed25519 signing or signature verification.

Check the media tools with:

```bash
ffmpeg -version
ffprobe -version
```

## Install

```bash
git clone https://github.com/jordanlegare/substitute.git
cd substitute
python -m pip install -e .
```

For Ed25519 bundle signatures:

```bash
python -m pip install -e '.[signature]'
```

For development and the full test suite:

```bash
python -m pip install -e '.[test,signature]'
```

The installed executable is:

```bash
ald-media-controller
```

## Quick start: direct simulation

The repository includes `recipes/generic_al2o3.json`, a generic A/B simulation recipe.

```bash
ald-media-controller validate recipes/generic_al2o3.json

ald-media-controller simulate \
  recipes/generic_al2o3.json \
  --seed 42 \
  --output build/direct
```

The seed is explicit so deterministic runs are reproducible.

For recipe authoring, see [`docs/recipe-authoring.md`](docs/recipe-authoring.md).

## Quick start: QR/HLS mode

Compile the generic recipe into the original verified QR/BFSK HLS/fMP4 transport:

```bash
ald-media-controller compile \
  recipes/generic_al2o3.json \
  --output build/al2o3-media

ald-media-controller verify build/al2o3-media/stream.m3u8

ald-media-controller simulate-media \
  build/al2o3-media/stream.m3u8 \
  --seed 42 \
  --output build/al2o3-media-run
```

`compile` publishes only after the completed media bundle has passed fail-closed verification.

## Quick start: Majorana 2 product-MP4 mode

`recipes/majorana2_public_specs_reference_sim.json` contains a public-reference Majorana 2 device description plus the same kind of generic A/B surrogate simulator program. It explicitly sets `physical_fabrication_mapping` to `false`.

Build a product-stage MP4:

```bash
ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/majorana2-product
```

Verify it:

```bash
ald-media-controller verify-product build/majorana2-product/bundle.json
```

Run the verified packet stream through the deterministic simulator:

```bash
ald-media-controller simulate-product \
  build/majorana2-product/bundle.json \
  --seed 42 \
  --output build/majorana2-product-run
```

For the same recipe and seed, compare direct and product-mediated results:

```bash
ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/majorana2-direct

cmp build/majorana2-direct/cycles.csv build/majorana2-product-run/cycles.csv
cmp build/majorana2-direct/surface-final.json build/majorana2-product-run/surface-final.json
```

The Product MP4 CI workflow performs these same byte-for-byte comparisons.

## Product-MP4 artifacts

A product bundle contains exactly these primary generated artifacts:

```text
build/majorana2-product/
├── product.mp4
├── product.json
├── product-top.svg
├── product-stack.svg
├── product-final.svg
├── recipe.canonical.json
└── bundle.json
```

`product.mp4` uses the supported three-stream profile:

1. **H.264 video** — human-facing deterministic product/reference visualization;
2. **AAC audio** — redundant Manchester/BFSK packet-sequence and ALD1-digest witness;
3. **`bin_data` / `gpmd` data** — authoritative timed ALDP v1 packet records.

The video shows the public-reference material-layer stack, H-shaped tetron, three functional gate layers, five quantum dots with three shared in the represented layout, simulation-status stage, and final composed schematic.

The video pixels are **not** executable. Product verification has no QR/OCR/pixel fallback. Instructions are accepted only from the verified binary data track.

### `gpmd` does not mean GPMF

`gpmd` is used as an FFmpeg/MOV/MP4 transport fourcc for the binary data stream. The payload is Substitute's **ALDP v1** record format, not GoPro GPMF telemetry.

Each fixed-width ALDP slot binds:

- protocol magic/version;
- zero-based packet sequence;
- packet presentation time and duration;
- bounded canonical packet bytes;
- the existing chained ALD1 digest;
- CRC-32;
- deterministic zero padding.

The data track is the authoritative instruction source in product mode. The BFSK audio remains an independent witness.

## Public-reference Majorana 2 scope

Product mode is intentionally a **public-reference visualization plus generic simulator surrogate**, not a fabrication reconstruction.

The checked-in reference includes public-facing device fields such as:

- GaSb substrate;
- 6 nm InAs + 2 nm InAs0.8Sb0.2 quantum-well reference layers;
- 10 nm Pb superconductor reference layer;
- H-shaped superconducting-island/tetron schematic;
- two horizontal nanowires;
- 3.5 µm public nanowire length reference;
- 35 nm public nanowire width reference;
- 1 µm × 20 nm public backbone reference;
- three functional gate layers;
- five quantum dots, three represented as shared with vertical neighbors.

Unknown or undisclosed process values remain unspecified. Substitute does not infer epitaxy conditions, barrier recipes, precursor chemistry, lithography, etch conditions, Pb deposition conditions, cryogenic setpoints, or equipment recipes.

See [`docs/majorana2-public-spec-reference.md`](docs/majorana2-public-spec-reference.md) for the detailed scientific and source-status caveats.

## Command reference

### `validate`

```bash
ald-media-controller validate RECIPE.json
```

Validate and compile a recipe without executing it.

### `simulate`

```bash
ald-media-controller simulate RECIPE.json \
  --seed 42 \
  --output build/direct
```

Options include required `--seed`, required `--output`, `--overwrite`, and `--log-level DEBUG`.

### `compile`

```bash
ald-media-controller compile RECIPE.json \
  --output build/bundle
```

Build the original QR/BFSK local HLS/fMP4 bundle. Optional `--signing-key PRIVATE.pem` signs `bundle.json`. `--overwrite` performs transactional replacement only after a new candidate verifies successfully.

### `verify`

```bash
ald-media-controller verify build/bundle/stream.m3u8
```

For signed-only policy:

```bash
ald-media-controller verify build/bundle/stream.m3u8 \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

### `simulate-media`

```bash
ald-media-controller simulate-media build/bundle/stream.m3u8 \
  --seed 42 \
  --output build/media
```

The media bundle is verified before the canonical recipe is rebound and executed.

### `compile-product`

```bash
ald-media-controller compile-product RECIPE.json \
  --seed 42 \
  --output build/product
```

Options:

- `--seed N` — product render/surrogate simulation seed; defaults to `42`;
- `--output DIR` — required product bundle directory;
- `--overwrite` — transactionally replace an existing safe product bundle;
- `--signing-key PRIVATE.pem` — sign the canonical product `bundle.json` with Ed25519;
- `--log-level DEBUG` — include traceback detail on failure.

Compilation performs the simulator run, product-scene rendering, MP4 transport capability proof, real mux, bundle binding, optional signing, and full candidate verification **before publication**.

### `verify-product`

```bash
ald-media-controller verify-product build/product/bundle.json
```

For signed-only policy:

```bash
ald-media-controller verify-product build/product/bundle.json \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

### `simulate-product`

```bash
ald-media-controller simulate-product build/product/bundle.json \
  --seed 42 \
  --output build/product-run
```

`simulate-product` verifies the product bundle, recompiles the bound canonical recipe, requires exact packet/root identity with the trusted MP4 data track, and only then executes the deterministic simulator.

Use an output directory separate from the media bundle. Overlapping bundle/output ancestors are rejected.

## What verification checks

### QR/HLS verifier

The legacy verifier rejects, among other things:

- unsafe absolute, URL-bearing, traversal, or escaping paths;
- unsupported HLS constructs;
- missing, duplicate, extra, misordered, or unexpected fragments;
- incorrect media codecs or stream properties;
- audio/video timeline drift;
- QR sequence/digest disagreement;
- BFSK sequence/digest disagreement;
- disagreement between QR, audio, bundle index, and recomputed ALD1 chain;
- modified canonical recipe bytes;
- invalid or untrusted requested signatures.

The HLS manifest is parsed and path-checked locally rather than handed to FFmpeg as an untrusted network locator.

### Product-MP4 verifier

Before product packets become executable, verification requires agreement across:

- exact canonical `bundle.json` schema/bytes;
- fixed artifact names and SHA-256 bindings;
- regular non-symlink files confined to the bundle root;
- exactly one H.264 video, one mono 48 kHz AAC stream, and one `bin_data/gpmd` stream;
- exact data-packet count, 1024-byte record size, presentation timing, and durations;
- ALDP v1 magic/version/CRC/padding/canonical-packet structure;
- contiguous zero-based packet sequence;
- recomputed ALD1 previous-digest chain and terminal root;
- BFSK audio sequence/hash witness for every three-second packet interval;
- only bounded trailing AAC decoder padding, never missing witness samples;
- canonical recipe SHA-256, recompilation, packet identity, and root identity;
- canonical `product.json` with `physical_fabrication_mapping=false`;
- deterministic byte-for-byte SVG regeneration from the bound product scene;
- optional Ed25519 signature under the exact product bundle schema.

Only after all checks succeed does the verifier return executable `HashedPacket` objects.

## Signed bundles

Unsigned bundles provide internal integrity/corruption detection but do not prove publisher identity. A party able to replace an entire unsigned bundle can create a different internally consistent unsigned bundle.

For publisher identity, use Ed25519 signatures and distribute the public key through a trusted channel.

Example key pair with OpenSSL:

```bash
mkdir -p keys
openssl genpkey -algorithm Ed25519 -out keys/publisher-private.pem
openssl pkey \
  -in keys/publisher-private.pem \
  -pubout \
  -out keys/publisher-public.pem
```

For QR/HLS:

```bash
ald-media-controller compile recipes/generic_al2o3.json \
  --output build/signed-media \
  --signing-key keys/publisher-private.pem

ald-media-controller verify build/signed-media/stream.m3u8 \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

For product MP4:

```bash
ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --output build/signed-product \
  --signing-key keys/publisher-private.pem

ald-media-controller verify-product build/signed-product/bundle.json \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

The signing implementation uses the same domain-separated Ed25519 primitive for both bundle types while requiring each bundle's own exact top-level schema.

## Packet integrity model

Validated instructions are serialized as deterministic canonical JSON packets. Packet integrity is chained:

```text
H_i = SHA-256( ASCII("ALD1") || H_(i-1) || P_i )
```

where `P_i` is the canonical packet byte string, `H_0` is 32 zero bytes, and the final packet digest is the bundle root hash.

Repeated `ALD_CYCLE` operations remain procedural: the packet keeps its `repeat` value rather than expanding it into hundreds of duplicated instructions.

## Procedural compaction vs. media size

Substitute distinguishes compact procedural instructions from the physical media container size.

`measure_procedural_compression(...)` compares canonical compact instructions with analytical naive expansion. Media formats then add deliberate QR/audio/container/redundancy or video/data-track overhead.

Neither HLS/fMP4 nor product MP4 is claimed to be the source of procedural compression. The compact packet representation is.

## Output safety

Output directories are protected by default. Existing paths require explicit `--overwrite`.

Media compilation is transactional: a previous output is preserved until the replacement candidate has passed completed-media verification and can be atomically published. Recipe/output and bundle/output overlap checks prevent dangerous self-overwrite patterns.

## Troubleshooting

### FFmpeg or ffprobe is missing

```bash
ffmpeg -version
ffprobe -version
```

Install FFmpeg and ensure both tools are on `PATH`.

### Product mode reports unsupported `bin_data/gpmd`

Product compilation runs an executable local capability proof. The FFmpeg build must preserve timed 1024-byte binary samples through MPEG-TS staging into MP4 and back out byte-exactly while dropping the staging guard. Use an FFmpeg build that satisfies that proof.

### `output directory already exists`

Choose a different path or pass `--overwrite` when transactional replacement is intended.

### `signature required`

The bundle is unsigned but the caller requested signed-only verification. Compile with `--signing-key` or remove the signed-only policy.

### Verification fails after editing a generated file

That is expected. Generated bundles are fail-closed integrity artifacts. Recompile from the source recipe instead of editing generated files in place.

### More diagnostic detail

Add:

```bash
--log-level DEBUG
```

CLI errors are emitted as structured JSON on stderr; DEBUG also emits the traceback.

## Testing and acceptance

Run all tests:

```bash
python -m pytest -q
```

The repository has separate real-FFmpeg acceptance coverage for the original HLS path and the product-MP4 path.

The Product MP4 workflow additionally:

- compiles all Python modules;
- builds a real Majorana 2 public-reference product bundle;
- verifies the completed product MP4;
- asserts the H.264/AAC/`bin_data(gpmd)` stream profile with `ffprobe`;
- asserts `physical_fabrication_mapping=false`, the H-tetron reference, three gates, five QDs, and three shared QDs;
- runs direct and product-mediated simulation at seed 42;
- byte-compares `cycles.csv` and `surface-final.json`.

Legacy QR/HLS regression coverage remains mandatory.

## Technical documents

- [`docs/recipe-authoring.md`](docs/recipe-authoring.md) — recipe schema and authoring guide.
- [`docs/majorana2-public-spec-reference.md`](docs/majorana2-public-spec-reference.md) — Majorana 2 public-reference scope, caveats, and product-mode usage.
- `docs/specs/2026-09-03-ald-media-controller-design.md` — original protocol/system design.
- `docs/specs/2026-09-04-majorana2-product-mp4-design.md` — product-MP4 design.
- `docs/superpowers/plans/2026-09-03-ald-hls-integration.md` — HLS/fMP4 implementation plan.
- `docs/superpowers/plans/2026-09-04-majorana2-product-mp4.md` — product-MP4 implementation plan.

## Non-goals

Substitute is not an industrial machine-control stack. This repository does not provide:

- live valve, pump, heater, gas, precursor, or vacuum-system control;
- PLC or safety-PLC replacement;
- fieldbus or equipment-network control;
- vendor safety-interlock bypasses;
- chemical handling procedures;
- production process qualification;
- undisclosed Majorana 2 fabrication reconstruction;
- authorization to operate real deposition equipment.

Any future real-machine adapter would require a separate architecture, explicit authentication/authorization, independent process-safety analysis, vendor/interlock integration, staged hardware-in-the-loop validation, operational procedures, and deployment review. It is intentionally outside the current simulator path.
