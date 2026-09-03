# substitute

Research and simulation artifacts for a media-encoded atomic layer deposition (ALD) instruction controller.

> **Safety boundary:** this project is an offline recipe compiler and simulated controller. It does not control industrial hardware, initiate network control, or replace PLC, hardwired, or vendor safety interlocks. The generic precursor names and Al2O3 mapping are simulation labels, not operational handling instructions.

## Phase-one capabilities

The current core provides:

- strict `ALD-MEDIA/1` recipe validation;
- deterministic canonical instruction packets;
- the chained integrity formula `H_i = SHA-256("ALD1" || H_(i-1) || P_i)`;
- compact repeated `ALD_CYCLE` packets without cycle unrolling;
- a deterministic region/site surface model with bounded atom-event samples;
- a simulated ALD controller state machine with interlocks and fail-closed fault handling;
- deterministic direct-mode `validate` and `simulate` commands;
- transactional publication of `audit.jsonl`, `cycles.csv`, `surface-final.json`, and `fault.json` when a simulated fault occurs.

QR/BFSK media codecs and HLS/fMP4 bundle execution are the next implementation phases; the plans are already checked in under `docs/superpowers/plans/`.

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

Run the complete core suite with:

```bash
python -m pytest -q
```

## Project documents

- `docs/specs/2026-09-03-ald-media-controller-design.md` — system design and protocol specification.
- `docs/superpowers/plans/2026-09-03-ald-core-simulator.md` — core compiler/simulator plan.
- `docs/superpowers/plans/2026-09-03-ald-media-codecs.md` — QR frame and BFSK codec plan.
- `docs/superpowers/plans/2026-09-03-ald-hls-integration.md` — HLS/fMP4 packaging and verification plan.

The repository remains simulation-only throughout these phases. Any future live-machine adapter would require a separate architecture, authentication/authorization model, safety analysis, and deployment review rather than being enabled through this simulator path.
