# Substitute — Verified Media-Encoded ALD Simulator

Substitute is an **offline atomic layer deposition (ALD) recipe compiler, deterministic simulator, and verified media transport experiment**.

It can run a validated recipe directly in the simulator, or encode the same compact instruction packets into QR video plus redundant BFSK checksum audio, package them as local HLS/fMP4, verify the completed encoded media, and then feed the verified packet stream back into the **same simulator**.

> **Safety boundary**
>
> Substitute does **not** control industrial hardware. It does not open valves, drive heaters, pumps, mass-flow controllers, precursor delivery, PLCs, field buses, networked process equipment, or vendor safety systems. The included generic A/B and Al2O3 examples are simulation labels and are not chemical-handling or machine-operation instructions.

## What can I do with it?

| Goal | Command |
| --- | --- |
| Check that a recipe is valid | `ald-media-controller validate ...` |
| Run a deterministic simulation directly | `ald-media-controller simulate ...` |
| Encode a recipe into a verified local HLS/fMP4 bundle | `ald-media-controller compile ...` |
| Verify an existing media bundle | `ald-media-controller verify ...` |
| Verify a media bundle and then simulate it | `ald-media-controller simulate-media ...` |

The two simulation paths are designed to be equivalent: for the same canonical recipe, verified packet stream, controller implementation, and random seed, direct simulation and verified-media simulation should produce the same deterministic reports.

## Requirements

You need:

- Python **3.10 or newer**;
- `ffmpeg` and `ffprobe` on your `PATH` for media compilation and media verification;
- FFmpeg support for H.264, AAC, MP4/fMP4, and HLS;
- the optional Python `signature` extra only if you want Ed25519 signing or signature verification.

Check the media tools before starting:

```bash
ffmpeg -version
ffprobe -version
```

## Install

Clone the repository and install the command-line tool:

```bash
git clone https://github.com/jordanlegare/substitute.git
cd substitute
python -m pip install -e .
```

This installs the executable:

```bash
ald-media-controller
```

If you also want Ed25519 bundle signing and trusted-key verification:

```bash
python -m pip install -e '.[signature]'
```

For development and the full test suite:

```bash
python -m pip install -e '.[test,signature]'
```

## 5-minute quick start

The repository includes `recipes/generic_al2o3.json`, a generic A/B ALD simulation recipe used by the acceptance workflow.

**Writing your own recipe?** Start with the [Recipe Authoring Guide](docs/recipe-authoring.md) for a small runnable recipe, complete field/opcode reference, surface-model defaults, controller ordering, common validation failures, and the full annotated example.

### 1. Validate the recipe

```bash
ald-media-controller validate recipes/generic_al2o3.json
```

A successful command exits normally. Invalid recipes fail with a structured JSON error on stderr.

### 2. Run the recipe directly in the simulator

```bash
ald-media-controller simulate \
  recipes/generic_al2o3.json \
  --seed 42 \
  --output build/direct
```

The seed is required so deterministic runs are explicit and reproducible.

### 3. Compile the recipe into verified media

```bash
ald-media-controller compile \
  recipes/generic_al2o3.json \
  --output build/al2o3
```

`compile` stages QR and BFSK media, encodes it as H.264/AAC, packages a local fMP4 HLS bundle, verifies the **completed encoded bundle**, and only then publishes the output directory.

### 4. Verify the media bundle

```bash
ald-media-controller verify build/al2o3/stream.m3u8
```

A successful verification prints compact JSON similar to:

```json
{"media_profile":{...},"packet_count":7,"protocol":"ALD-MEDIA/1","root_hash":"...","signature_status":"UNSIGNED"}
```

### 5. Simulate from the verified media

```bash
ald-media-controller simulate-media \
  build/al2o3/stream.m3u8 \
  --seed 42 \
  --output build/media
```

`simulate-media` always verifies the bundle first. Only after verification succeeds are the recovered canonical packets and verified recipe configuration passed to the deterministic simulator.

### 6. Compare direct and media results

For the checked-in demonstration recipe and seed 42:

```bash
cmp build/direct/cycles.csv build/media/cycles.csv
cmp build/direct/surface-final.json build/media/surface-final.json
```

The project CI performs these same byte-for-byte comparisons.

## Command reference

### `validate`

Validate and compile a recipe without running a simulation or creating a media bundle.

```bash
ald-media-controller validate RECIPE.json
```

Use this first when authoring or modifying recipes.

### `simulate`

Run a validated recipe directly through the deterministic simulated controller.

```bash
ald-media-controller simulate RECIPE.json \
  --seed 42 \
  --output build/direct
```

Options:

- `--seed N` — required deterministic random seed;
- `--output DIR` — required report directory;
- `--overwrite` — replace an existing safe output directory;
- `--log-level DEBUG` — include a traceback for CLI failures.

### `compile`

Compile a recipe into a verified local HLS/fMP4 bundle.

```bash
ald-media-controller compile RECIPE.json \
  --output build/bundle
```

Options:

- `--output DIR` — required bundle directory;
- `--overwrite` — transactionally replace an existing safe bundle directory;
- `--signing-key PRIVATE.pem` — sign `bundle.json` with an Ed25519 private key;
- `--log-level DEBUG` — include a traceback for failures.

The output is not published until the completed encoded media has passed verification.

### `verify`

Verify a completed local media bundle.

```bash
ald-media-controller verify build/bundle/stream.m3u8
```

For a signed bundle:

```bash
ald-media-controller verify build/bundle/stream.m3u8 \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

Options:

- `--require-signature` — reject unsigned bundles;
- `--trusted-public-key PUBLIC.pem` — caller-supplied trusted Ed25519 public key;
- `--log-level DEBUG` — include a traceback for failures.

A signed bundle is **not** trusted merely because it contains a fingerprint. Trust comes from the public key supplied by the caller.

### `simulate-media`

Verify a bundle and, only if verification succeeds, execute the recovered recipe in the deterministic simulator.

```bash
ald-media-controller simulate-media build/bundle/stream.m3u8 \
  --seed 42 \
  --output build/media
```

For signed-only execution:

```bash
ald-media-controller simulate-media build/bundle/stream.m3u8 \
  --seed 42 \
  --output build/media \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

Use an output directory separate from the media bundle. The CLI rejects output paths that overlap the bundle or its ancestors.

## What gets written?

### Simulation reports

A successful simulation publishes deterministic reports such as:

- `audit.jsonl` — controller/audit events;
- `cycles.csv` — per-cycle simulation metrics;
- `surface-final.json` — final simulated surface state;
- `fault.json` — written when a simulated controller fault occurs.

Report publication is transactional: existing outputs are not silently replaced.

### Media bundle

A compiled bundle contains:

```text
build/bundle/
├── stream.m3u8
├── init.mp4
├── packet-000000.m4s
├── packet-000001.m4s
├── ...
├── bundle.json
└── recipe.canonical.json
```

The important files are:

- `stream.m3u8` — normalized local HLS media playlist;
- `init.mp4` — shared fragmented-MP4 initialization segment;
- `packet-*.m4s` — one encoded media segment per compact instruction packet;
- `bundle.json` — canonical ordered packet metadata, media profile, root hash, recipe digest, and optional Ed25519 signature;
- `recipe.canonical.json` — exact canonical recipe/configuration bytes bound to `bundle.json` by SHA-256.

Do not manually edit generated bundle files and expect verification to continue succeeding. The verifier is intentionally fail-closed.

## Signed bundles

Unsigned bundles provide integrity consistency and corruption/tamper detection across the redundant records, but they do **not** prove who created the bundle. A party that can replace an entire unsigned bundle can create a different internally consistent unsigned bundle.

For publisher identity, use Ed25519 signatures and distribute the public key through a channel you trust.

### Install signature support

```bash
python -m pip install -e '.[signature]'
```

### Create an Ed25519 key pair

One option is OpenSSL:

```bash
mkdir -p keys
openssl genpkey -algorithm Ed25519 -out keys/publisher-private.pem
openssl pkey \
  -in keys/publisher-private.pem \
  -pubout \
  -out keys/publisher-public.pem
```

Keep `publisher-private.pem` private. The public key is what verifiers should receive through a trusted channel.

### Compile a signed bundle

```bash
ald-media-controller compile \
  recipes/generic_al2o3.json \
  --output build/signed-al2o3 \
  --signing-key keys/publisher-private.pem
```

### Require the trusted signature when verifying

```bash
ald-media-controller verify build/signed-al2o3/stream.m3u8 \
  --require-signature \
  --trusted-public-key keys/publisher-public.pem
```

The Ed25519 signature covers the canonical unsigned bundle index. That index binds the ordered packet digests/root, media profile, and SHA-256 of `recipe.canonical.json`, so a valid signature authenticates the declared recipe/configuration binding as well.

## Direct mode or media mode?

Use **direct simulation** when you want the shortest route from a JSON recipe to deterministic simulation results.

Use **verified media simulation** when you want to exercise the experimental transport/integrity layer:

```text
recipe
  ↓
canonical compact packets
  ↓
QR instruction frames + redundant BFSK digest audio
  ↓
H.264/AAC fragmented MP4 / HLS
  ↓
fail-closed verification
  ↓
same deterministic simulator
```

The three-second media interval used for each packet is a transport framing interval. It is **not** the physical or simulated duration of an ALD process step.

## What verification checks

Before packets become executable simulator input, the verifier checks the completed encoded bundle across multiple independent records.

It rejects, among other things:

- unsafe absolute, URL-bearing, traversal, or escaping paths;
- unsupported HLS constructs such as master playlists, keys/encryption, discontinuities, and byte ranges;
- missing, duplicate, extra, misordered, or unexpected `.m4s` media fragments;
- incorrect media codecs or stream properties;
- audio/video segment timeline drift;
- QR sequence/digest disagreement;
- BFSK sequence/digest disagreement;
- disagreement between QR, audio, `bundle.json`, and the recomputed packet hash chain;
- missing or modified `recipe.canonical.json` bytes;
- malformed canonical instruction packets;
- terminal ALD1 root-hash mismatch;
- invalid, mismatched, or untrusted Ed25519 signatures when signature verification is requested.

The HLS manifest is parsed and path-checked by Substitute itself. The verifier does not hand an untrusted playlist directly to FFmpeg as an executable network/media locator.

## How the media encoding works

The executable instruction bytes live in the QR channel. The audio channel is redundant integrity evidence.

Default media profile:

- frame size: **1920 × 1080**;
- QR error correction: **Q**;
- QR box/module scale: **8**;
- QR quiet-zone border: **4 modules**;
- media interval: **3.0 seconds per packet**;
- audio: **48 kHz mono PCM** before AAC encoding;
- BFSK: **1200 symbols/s**;
- space: **1200 Hz**;
- mark: **2400 Hz**;
- checksum copies per interval: **3**;
- matching CRC-valid copies required: **2**.

The 49-byte audio record carries a preamble, protocol version, packet sequence, 256-bit packet digest, and CRC-32. It is Manchester coded before BFSK modulation.

## Packet integrity model

Validated instructions are serialized as deterministic canonical JSON packets. Packet integrity is chained:

```text
H_i = SHA-256( ASCII("ALD1") || H_(i-1) || P_i )
```

where:

- `P_i` is the canonical packet byte string;
- `H_0` is 32 zero bytes;
- the final packet digest is the bundle root hash.

Repeated ALD cycles remain compact: an `ALD_CYCLE` packet keeps its `repeat` count rather than being expanded into hundreds of nearly identical instruction records.

## Procedural compaction vs. HLS size

Substitute deliberately reports two different size concepts.

`measure_procedural_compression(...)` compares the compact instruction representation with an analytical naive expansion. For the checked-in demonstration recipe, the accepted integration run measured:

- canonical instruction bytes: **1,140**;
- analytical per-cycle instruction JSONL bytes: **27,076**;
- procedural instruction ratio: **23.75×**;
- estimated potential half-reaction/site events: **200,000,000**;
- estimated site-event JSONL size: **16.6 GB**.

Those large event counts are estimated arithmetically; the simulator does not allocate hundreds of millions of event objects just to calculate this metric.

`measure_hls_bundle_bytes(...)` measures the physical generated media bundle. The same accepted Ubuntu/FFmpeg run produced a **512,981-byte** bundle.

That does **not** mean HLS/fMP4 is the compression mechanism. HLS/fMP4 intentionally adds QR, audio, codec, container, and redundancy overhead. The compression benefit being explored is the compact procedural instruction representation relative to naive repeated/event-expanded representations.

## Output safety and overwrite behavior

Output directories are protected by default.

If an output already exists, choose a new path or explicitly pass:

```bash
--overwrite
```

For media compilation, overwrite is transactional: the previous bundle is preserved until a newly built candidate has passed completed-media verification and is ready to publish.

The CLI also rejects dangerous recipe/output and bundle/output path overlaps.

## Troubleshooting

### `ffmpeg executable is required` or `ffprobe executable is required`

Install FFmpeg and make sure both commands are available on your `PATH`:

```bash
ffmpeg -version
ffprobe -version
```

The build also requires H.264, AAC, MP4/fMP4, and HLS capabilities.

### `output directory already exists`

Use a new directory, remove the old output yourself, or explicitly use `--overwrite` if replacement is intended.

### `signature required`

The bundle is unsigned but you used `--require-signature`. Compile a signed bundle or remove that policy flag.

### `trusted public key` / `fingerprint` / `signature` error

A signed bundle requires the expected external trusted public key. Check that:

- the `signature` Python extra is installed;
- the public key corresponds to the signing private key;
- you are passing the intended key with `--trusted-public-key`;
- the bundle has not been changed since it was signed.

### Media verification fails after I edited a generated file

That is expected. Restore the original bundle or recompile it from the source recipe. Generated media bundles are integrity-checked artifacts, not files intended for manual in-place editing.

### I need more diagnostic detail

Add:

```bash
--log-level DEBUG
```

CLI failures are emitted as structured JSON on stderr; DEBUG additionally includes the traceback.

## Testing and acceptance

Run the complete Python test suite with:

```bash
python -m pytest -q
```

The HLS GitHub Actions acceptance workflow also:

- installs real FFmpeg;
- installs the signature dependency;
- compiles every project Python module;
- builds a real media bundle;
- verifies the completed encoded bundle;
- runs direct simulation and verified-media simulation with seed 42;
- byte-compares `cycles.csv` and `surface-final.json`;
- prints procedural-compaction and physical-bundle-size metrics.

The media integration that landed on `main` passed **150/150 tests** on the actual pull-request merge ref before merge.

## Project status

The current `main` line includes:

- deterministic recipe validation and compilation;
- hardened offline simulated controller execution;
- deterministic QR instruction encoding;
- redundant Manchester/BFSK checksum audio;
- H.264/AAC fMP4/HLS packaging;
- strict local-only completed-media verification;
- canonical recipe SHA-256 binding;
- optional trusted Ed25519 bundle signatures;
- transactional media publication;
- direct/media deterministic equivalence checks;
- bounded procedural-compaction metrics.

It remains **simulation-only**.

## Technical documents

- `docs/recipe-authoring.md` — end-user recipe schema, examples, opcode reference, surface-model defaults, and authoring workflow.
- `docs/specs/2026-09-03-ald-media-controller-design.md` — protocol and system design.
- `docs/superpowers/plans/2026-09-03-ald-core-simulator.md` — core compiler/simulator implementation plan.
- `docs/superpowers/plans/2026-09-03-ald-media-codecs.md` — QR and BFSK implementation plan.
- `docs/superpowers/plans/2026-09-03-ald-hls-integration.md` — HLS/fMP4 packaging, verification, signing, and CLI plan.

## Non-goals

Substitute is not an industrial machine-control stack and should not be treated as one.

This repository does not provide:

- live valve, pump, heater, gas, precursor, or vacuum-system control;
- PLC or safety-PLC replacement;
- fieldbus or equipment-network control;
- vendor safety-interlock bypasses;
- chemical handling procedures;
- production process qualification;
- authorization to operate real deposition equipment.

Any future real-machine adapter would require a separate architecture, explicit authentication/authorization, independent process-safety analysis, vendor/interlock integration, staged hardware-in-the-loop validation, operational procedures, and deployment review. It is intentionally outside the current simulator path.