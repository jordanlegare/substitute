# substitute

Research and simulation artifacts for a media-encoded atomic layer deposition (ALD) instruction controller.

> **Safety boundary:** this project is an offline recipe compiler and simulated controller. It does not control industrial hardware, initiate network control, or replace PLC, hardwired, or vendor safety interlocks. The generic precursor names and Al2O3 mapping are simulation labels, not operational handling instructions.

## What the project does

The project supports two deterministic execution modes over the same validated recipe and controller model:

1. **Direct simulation** — validate and compile the recipe in memory, then execute the simulated controller.
2. **Verified media simulation** — compile the same compact instruction packets into QR video plus BFSK checksum audio, mux/package them as local HLS/fMP4, decode the completed encoded media, verify every integrity boundary, then execute the same simulated controller.

The media path is deliberately not a hardware-control adapter. A verified media bundle becomes input only to the simulator.

## Core instruction and simulation model

The deterministic core provides:

- strict `ALD-MEDIA/1` recipe validation;
- canonical compact JSON instruction packets;
- the chained integrity formula `H_i = SHA-256("ALD1" || H_(i-1) || P_i)` with a 32-byte zero `H_0`;
- compact repeated `ALD_CYCLE` packets that retain `repeat` rather than unrolling every cycle;
- a deterministic region/site surface model with bounded atom-event samples;
- a simulated ALD controller state machine with interlocks and fail-closed fault handling;
- transactional publication of `audit.jsonl`, `cycles.csv`, `surface-final.json`, and `fault.json` when a simulated fault occurs.

## QR and BFSK packet media

Each compact hashed packet has a fixed three-second **transport-media interval**. The three seconds are a framing/transport property and are not the simulated process duration of the ALD instruction.

The local codec layer provides:

- 1920x1080 QR-Q instruction frames with at least eight encoded pixels per module;
- a strict binary QR envelope carrying sequence, chained packet digest, and the executable canonical packet bytes;
- raw-byte QR decoding through ZXing, with zero/multiple-code ambiguity rejected and no OCR execution path;
- a 49-byte checksum record containing the 64-bit alternating preamble, protocol version, big-endian sequence, 256-bit packet digest, and CRC-32;
- Manchester coding with `0 -> 01` and `1 -> 10`;
- phase-continuous 1200/2400 Hz BFSK at 1200 symbols/second, mono 48 kHz PCM, with three record copies per interval;
- correlation decoding that requires at least two matching CRC-valid audio copies;
- deterministic packet staging with immediate frame/audio cross-verification.

The QR channel contains the executable canonical packet. The BFSK channel is redundant integrity evidence: its sequence and digest must agree with the QR frame, bundle index, and recomputed ALD1 hash chain.

## HLS/fMP4 bundle

`compile` encodes the staged packet media as H.264/AAC and publishes a local fMP4 HLS VOD bundle only after the **completed encoded media** verifies successfully. Verification never substitutes the source PNG/WAV staging artifacts for the encoded output.

A published bundle contains:

- `stream.m3u8` — normalized local HLS media playlist;
- `init.mp4` — shared fMP4 initialization segment;
- `packet-000000.m4s`, ... — one media segment per compact instruction packet;
- `bundle.json` — canonical ordered packet/index/root/profile metadata, the canonical-recipe SHA-256 binding, and optional signature;
- `recipe.canonical.json` — exact canonical recipe bytes containing the simulation configuration used to rebind verified media to the simulator.

`bundle.json` records both the fixed path `recipe.canonical.json` and SHA-256 of its exact bytes. Verification rejects a missing, symlinked, renamed, or digest-mismatched recipe artifact. The verified recipe bytes are retained in memory and `simulate-media` parses those verified bytes from a private scratch file rather than reopening the mutable bundle recipe after verification.

Bundle publication is transactional. Existing output is preserved unless `--overwrite` is supplied, and a replacement is not published until the new encoded bundle has verified.

### Fail-closed verification

The verifier rejects a bundle before exposing executable packets when any required independent record disagrees. Among other checks, it rejects:

- absolute paths, URL/scheme-bearing paths, path traversal, and unsupported playlist forms;
- discontinuities, encryption/key tags, master-playlist forms, byte ranges, malformed or out-of-range durations;
- missing, extra, duplicate, non-contiguous, or unexpectedly named media segments;
- unexpected stream codecs/formats;
- segment audio/video timeline drift relative to the cumulative verified playlist timeline;
- frame/audio/index sequence disagreement;
- frame/audio/index digest disagreement;
- missing or modified canonical recipe bytes relative to the recipe SHA-256 declared by `bundle.json`;
- malformed canonical packet bytes;
- recomputed ALD1 hash-chain or terminal-root mismatch.

FFmpeg is invoked only through a bounded local subprocess boundary with argument vectors, `shell=False`, no stdin, and timeouts. The verifier parses and resolves local bundle paths itself rather than handing an untrusted HLS manifest to FFmpeg.

## Integrity versus optional Ed25519 bundle identity

Checksum/hash consistency and publisher identity are separate concerns.

Unsigned bundles are permitted by default. Their packet hash chain, redundant media records, bundle index, and canonical-recipe SHA-256 provide fail-closed **consistency and corruption detection**, but an unsigned bundle does not authenticate who created it; a party able to replace a whole unsigned bundle can construct new internally consistent hashes as well.

When `bundle.json` is signed, the Ed25519 signature covers the canonical unsigned index bytes. Because the index contains the packet/root metadata **and the SHA-256 of `recipe.canonical.json`**, a valid signature from a caller-trusted public key authenticates the exact recipe/configuration binding as well as the declared media metadata. `--require-signature` rejects unsigned bundles.

Install the optional signature dependency with the `signature` extra. Private keys are inputs to explicit signing operations; they are not embedded in bundles.

## Install for development

Python 3.10 or newer is required. Media compilation/verification also requires local `ffmpeg` and `ffprobe` binaries with H.264, AAC, MP4, and HLS support.

```bash
python -m pip install -e '.[test,signature]'
```

## Reproducible generic Al2O3 workflow

Validate the checked-in generic A/B simulation recipe:

```bash
ald-media-controller validate recipes/generic_al2o3.json
```

Run direct simulation:

```bash
ald-media-controller simulate recipes/generic_al2o3.json --seed 42 --output build/direct
```

Compile and verify the completed HLS/fMP4 bundle:

```bash
ald-media-controller compile recipes/generic_al2o3.json --output build/al2o3
ald-media-controller verify build/al2o3/stream.m3u8
```

Execute the verified media through the simulator:

```bash
ald-media-controller simulate-media build/al2o3/stream.m3u8 --seed 42 --output build/media
```

For the same canonical recipe, verified packet stream, controller implementation, and seed, direct and media modes are expected to produce byte-identical deterministic simulation reports. The CI acceptance workflow checks `cycles.csv` and `surface-final.json` directly.

Existing output directories are not replaced unless `--overwrite` is supplied.

## Procedural compaction and media size

The project reports two deliberately separate kinds of size information:

- `measure_procedural_compression(...)` compares the compact canonical packet stream with an **analytical** naive JSONL expansion in which repeated `ALD_CYCLE` operations are serialized individually. It also estimates a per-site, per-half-reaction event JSONL expansion arithmetically. The estimator never allocates that giant event stream.
- `measure_hls_bundle_bytes(...)` reports the physical bytes occupied by a flat verified HLS bundle and rejects symlinks/non-regular entries.

These numbers answer different questions. The compact procedural instruction representation can avoid enormous repeated instruction/event expansions; **HLS/fMP4 is a redundant transport and verification container, not claimed to be a compression gain over the canonical instruction bytes.** Encoded video/audio intentionally adds redundancy and media overhead.

For the checked-in demonstration recipe, one compact `ALD_CYCLE` packet represents 100 simulated cycles over an aggregate surface of 1,000,000 sites. The analytical potential half-reaction/site-event count is therefore 200,000,000 without materializing 200 million records.

A verified Ubuntu/FFmpeg acceptance run for this recipe measured 1,140 canonical instruction bytes versus 27,076 bytes for the analytical per-cycle instruction expansion, a 23.75x procedural instruction ratio. The analytical site-event JSONL estimate was 16.6 GB. The generated HLS/fMP4 bundle was 512,981 bytes in that run; physical media size is informational and can vary with encoder/tool versions.

## Tests and acceptance

Run the complete suite with:

```bash
python -m pytest -q
```

The HLS integration GitHub Actions workflow additionally installs FFmpeg and the signature extra, compiles all project modules, builds and verifies a real encoded bundle, runs direct and media simulations with seed 42, compares deterministic reports, and prints procedural-compaction and physical-bundle-size metrics.

The current acceptance suite includes explicit rejection of a canonical recipe whose simulation-affecting surface configuration is changed after bundle creation.

## Project documents

- `docs/specs/2026-09-03-ald-media-controller-design.md` — system design and protocol specification.
- `docs/superpowers/plans/2026-09-03-ald-core-simulator.md` — core compiler/simulator plan.
- `docs/superpowers/plans/2026-09-03-ald-media-codecs.md` — QR frame and BFSK codec plan.
- `docs/superpowers/plans/2026-09-03-ald-hls-integration.md` — HLS/fMP4 packaging, verification, and execution plan.

The repository remains simulation-only throughout these phases. Any future live-machine adapter would require a separate architecture, authentication/authorization model, independent safety analysis, staged hardware-in-the-loop validation, and deployment review rather than being enabled through this simulator path.
