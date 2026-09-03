# substitute

Research and simulation artifacts for a media-encoded atomic layer deposition (ALD) instruction controller.

> **Safety boundary:** this project is an offline recipe compiler and simulated controller. It does not control industrial hardware, initiate network control, or replace PLC, hardwired, or vendor safety interlocks. The generic precursor names and Al2O3 mapping are simulation labels, not operational handling instructions.

## Core capabilities

The deterministic core provides:

- strict `ALD-MEDIA/1` recipe validation;
- deterministic canonical instruction packets;
- the chained integrity formula `H_i = SHA-256("ALD1" || H_(i-1) || P_i)`;
- compact repeated `ALD_CYCLE` packets without cycle unrolling;
- a deterministic region/site surface model with bounded atom-event samples;
- a simulated ALD controller state machine with interlocks and fail-closed fault handling;
- deterministic direct-mode `validate` and `simulate` commands;
- transactional publication of `audit.jsonl`, `cycles.csv`, `surface-final.json`, and `fault.json` when a simulated fault occurs.

## Media codec capabilities

The local media layer now provides:

- a fixed three-second `MediaProfile` for 1920x1080 QR frames and 48 kHz checksum audio;
- a strict binary QR envelope carrying sequence, chained packet digest, and canonical packet bytes;
- deterministic QR-Q instruction PNG rendering with at least eight encoded pixels per module;
- raw-byte QR decoding through ZXing, with zero/multiple-code ambiguity rejected and no OCR execution path;
- a 49-byte checksum record containing the 64-bit alternating preamble, protocol version, big-endian sequence, 256-bit packet digest, and CRC-32;
- Manchester coding with `0 -> 01` and `1 -> 10`;
- phase-continuous 1200/2400 Hz BFSK at 1200 symbols/second, mono 48 kHz PCM, with three record copies per interval;
- correlation decoding that requires at least two matching CRC-valid audio copies;
- deterministic `packet-000000.png` / `packet-000000.wav` staging with immediate post-write frame/audio verification.

HLS/fMP4 packaging, manifest verification, and bundle execution remain the next implementation phase under `docs/superpowers/plans/2026-09-03-ald-hls-integration.md`.

## Install for development

Python 3.10 or newer is required.

```bash
python -m pip install -e '.[test]'
```

## Reproducible generic Al2O3 simulation

Validate the checked-in generic A/B recipe:

```bash
ald-media-controller validate recipes/generic_al2o3.json
```

The command emits one JSON object including the protocol, recipe identifier, packet count, and 64-character root hash.

Run the deterministic simulator:

```bash
ald-media-controller simulate recipes/generic_al2o3.json --seed 42 --output build/direct
```

The successful direct-mode output directory contains:

- `audit.jsonl` — ordered state transitions, packet provenance, and controller events;
- `cycles.csv` — per-cycle coverage, thickness, utilization, and defect metrics;
- `surface-final.json` — deterministic final aggregate surface state and reproducibility metadata.

A faulted simulation additionally emits `fault.json` and exits with the controller error code. Existing output directories are not replaced unless `--overwrite` is supplied.

Run the complete suite with:

```bash
python -m pytest -q
```

## Project documents

- `docs/specs/2026-09-03-ald-media-controller-design.md` — system design and protocol specification.
- `docs/superpowers/plans/2026-09-03-ald-core-simulator.md` — core compiler/simulator plan.
- `docs/superpowers/plans/2026-09-03-ald-media-codecs.md` — QR frame and BFSK codec plan.
- `docs/superpowers/plans/2026-09-03-ald-hls-integration.md` — HLS/fMP4 packaging and verification plan.

The repository remains simulation-only throughout these phases. Any future live-machine adapter would require a separate architecture, authentication/authorization model, safety analysis, and deployment review rather than being enabled through this simulator path.
