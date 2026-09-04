# Majorana-Inspired Topological Stack Simulation Recipe

This document accompanies `recipes/majorana_topological_stack_sim.json`.

> **Simulation-only boundary**
>
> This is **not** a fabrication recipe for a functioning Majorana/topological-qubit chip. It does not encode real epitaxy, superconductor growth, lithography, etching, metallization, hazardous chemistry, equipment operation, or production process parameters. It exercises Substitute's existing generic A/B ALD simulator as an abstract dielectric/interface-deposition model.

## What the recipe represents

The recipe metadata describes four conceptual device regions:

- semiconductor interface;
- proximitized superconducting region;
- gate-dielectric region;
- isolation region.

Those names are descriptive only. The current simulator does not implement semiconductor band structure, superconductivity, topological phases, Majorana zero modes, electrostatics, cryogenics, lithography, or device transport. All four regions are represented only through the aggregate `site-binomial/1` surface model.

The declared precursor labels are intentionally generic:

- `A` → `interface-reactant-A-sim`
- `B` → `interface-reactant-B-sim`

No real precursor chemistry is implied.

## Run it directly

Validate the JSON recipe:

```bash
ald-media-controller validate recipes/majorana_topological_stack_sim.json
```

Run a deterministic direct simulation:

```bash
ald-media-controller simulate \
  recipes/majorana_topological_stack_sim.json \
  --seed 42 \
  --output build/majorana-direct
```

Inspect:

```text
build/majorana-direct/
├── audit.jsonl
├── cycles.csv
└── surface-final.json
```

If the virtual controller fails closed, `fault.json` is also published.

## Compile it into verified media

```bash
ald-media-controller compile \
  recipes/majorana_topological_stack_sim.json \
  --output build/majorana-media
```

Verify the completed HLS/fMP4 bundle:

```bash
ald-media-controller verify build/majorana-media/stream.m3u8
```

Execute the verified-media path:

```bash
ald-media-controller simulate-media \
  build/majorana-media/stream.m3u8 \
  --seed 42 \
  --output build/majorana-media-run
```

For the same recipe, seed, and controller implementation, direct and verified-media simulation are expected to produce the same deterministic reports.

## Recipe shape

The instruction stream uses the standard executable controller order:

```text
CONFIGURE
SET_TEMPERATURE
EVACUATE
STABILIZE
ALD_CYCLE × 32
MEASURE
SHUTDOWN
```

The 32 cycles remain represented by one compact `ALD_CYCLE` packet with `repeat: 32`; the cycle body is expanded procedurally only inside the simulator.

The measurement instruction requests the three currently supported aggregate outputs:

- `thickness_nm`
- `coverage`
- `defect_fraction`

## Surface abstraction

The recipe configures four aggregate regions with 250,000 modeled sites each, for a total of 1,000,000 simulated sites. Slightly different transport factors are used across the four regions to create a simple edge/interior variation in the generic surface model.

The model parameters are synthetic simulator inputs chosen to exercise deterministic surface behavior. They must not be interpreted as material constants or real process targets.

## Structural verification values

Against the current `ALD-MEDIA/1` authoring rules, the recipe has:

- 7 top-level instruction packets;
- 32 expanded simulated cycles;
- 456,400 ms of validation-time runtime accounting before temperature-ramp accounting;
- a largest canonical instruction packet of 241 bytes, below the 800-byte hard ceiling;
- ALD1 instruction-chain root `d447ebe8034070d0d115daff423335648861f2ead48bb34d87fd348de0fce62d`.

The media bundle additionally binds the exact canonical recipe bytes through the recipe SHA-256 recorded in `bundle.json`, so changes to metadata, limits, surface configuration, or instructions are detected by bundle verification even though the ALD1 packet chain itself covers the instruction packets.

## What this recipe can and cannot answer

It can be used to study the Substitute software path for:

- compact repeated instruction encoding;
- deterministic aggregate surface evolution;
- region-to-region transport-factor variation;
- QR/BFSK packet transport;
- HLS/fMP4 packaging;
- recipe binding and integrity verification;
- direct/media deterministic equivalence.

It cannot predict whether a physical device supports a topological phase or Majorana modes, and it cannot stand in for a semiconductor/superconductor fabrication model.

For general recipe syntax and validation rules, see `docs/recipe-authoring.md`.
