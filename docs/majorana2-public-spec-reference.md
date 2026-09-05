# Majorana 2 Public-Spec Reference Recipe

This document accompanies `recipes/majorana2_public_specs_reference_sim.json`.

> **Reference model, not a fabrication recipe**
>
> The recipe records publicly reported Majorana 2 device dimensions, materials, architecture, and measured/reported device metrics as **reference metadata**. Substitute does not model the real epitaxial heterostructure, superconductivity, Majorana zero modes, lithography, etching, quantum-dot electrostatics, cryogenic operation, or equipment recipes. The executable instruction stream remains the existing generic A/B offline simulator.

## Why this recipe exists

`majorana_topological_stack_sim.json` is intentionally abstract. This second recipe is for cases where a simulation artifact should carry a much closer description of the **public Majorana 2 reference device** while remaining honest about the limits of the current simulator.

The public device information is therefore separated into two layers:

1. **Reference metadata** — published materials, dimensions, gate/QD architecture, and reported device metrics.
2. **Executable simulator data** — synthetic A/B deposition and aggregate `site-binomial/1` surface parameters with no claimed physical mapping to the Majorana 2 fabrication process.

## Public reference target

The reference target is the InAs-Pb tetron platform reported by Microsoft Quantum in June 2026 in *20 Second Parity Lifetime in an InAs-Pb Tetron Device*.

The paper describes an H-shaped superconducting island consisting of two parallel proximitized semiconductor nanowires connected by a narrower superconducting backbone. The public dimensions recorded in the recipe are:

| Public reference field | Value recorded in recipe |
| --- | ---: |
| Horizontal proximitized nanowires | 2 |
| Each horizontal nanowire length | 3.5 µm |
| Each horizontal nanowire width | 35 nm |
| Backbone length | 1 µm |
| Backbone width | 20 nm |
| Target MZMs per tetron in the topological regime | 4 |

These dimensions are metadata only. The aggregate Substitute surface model does not treat them as deposition geometry or derive process settings from them. Product-MP4 mode uses them only to render a deterministic schematic reference view.

## Public material stack

The public paper reports the device on a GaSb substrate and describes a composite semiconductor quantum well with a Pb superconductor. The recipe records:

| Layer / material | Public value represented |
| --- | --- |
| Substrate | GaSb |
| Composite quantum well | 6 nm InAs + 2 nm InAs0.8Sb0.2 |
| Superconductor | Pb, 10 nm |
| Top barrier | Present, but composition/thickness not filled in because it is not specified in the cited public paper text used for this recipe |
| Bottom barrier | Present, but composition/thickness not filled in because it is not specified in the cited public paper text used for this recipe |
| Buffer | Present in the heterostructure description, but composition is not filled in here when not explicitly specified by the cited source text |

The recipe deliberately uses `null` or an explicit `not publicly specified` string where public information is absent. It does not infer proprietary process details.

## Gate and readout architecture

The public device description uses three functional gate layers:

1. electrostatic gates for nanowire carrier-density tuning;
2. junction/cutter gates for tunnel-coupling and interferometric-loop control;
3. gate-defined quantum dots for dispersive parity readout.

The recipe also records the reported five quantum dots coupled to each H-shaped island, with three shared with vertical neighbors in the scalable layout.

Reported QD reference values captured in metadata include:

- plunger lever arms: 0.4–0.45 meV/mV;
- charging energies: greater than 60 µeV;
- level spacings: greater than 30 µeV;
- long quantum-dot length: approximately 3.2 µm;
- representative linear gate extents: QD1 2.1 µm, QD2 2.4 µm, QD3 0.9 µm, QD4 1.2 µm.

None of these values are interpreted as ALD process parameters by Substitute.

## Reported material/device metrics carried as metadata

The recipe records selected public values so a bundle can remain self-describing:

| Reported reference metric | Value represented |
| --- | ---: |
| Pb parent superconducting gap | ~1.3 meV |
| Nanowire induced gap at zero field | ~570 µeV |
| Top-quintile reported topological gap | ~70 µeV |
| Spin-orbit coupling, text range | ~12–16 meV·nm |
| Extracted spin-orbit coupling example | 12 ± 2 meV·nm |
| 2D density | (0.49 ± 0.02) × 10^12 cm^-2 |
| Quantum lifetime | 0.37 ± 0.14 ps |
| Buried-QW mobility | >350,000 cm²/(V·s) |
| Representative TGP-region product | >1.1 mV·T |
| Representative opposite-end zero-bias-peak field span | >0.5 T |
| Reported localization length | >1 µm |
| Experimental Majorana-splitting resolution bound | ~1 µeV |
| Fitted Z-parity lifetime | 22 ± 1 s |
| Typical qubit-operation timescale referenced by the paper | on the order of microseconds |

These entries describe published measurements, fits, estimates, or device-characterization results. They are not generated by the Substitute simulator.

## Scientific-status caveat

The repository does not treat the phrase “Majorana” as independent experimental validation of a topological qubit. Microsoft reports the device in a topological/Majorana interpretation, while external researchers continue to debate whether the available measurements uniquely establish that interpretation.

For this reason, metadata labels the quantities as **reported reference values**, and the recipe does not contain a simulated `majorana_probability`, `topological_certainty`, or other invented validation metric.

## How the public device maps into the current simulator

The current aggregate surface model has four equal regions. They are assigned descriptive roles only:

| Simulator region | Reference role |
| ---: | --- |
| 0 | upper proximitized horizontal nanowire |
| 1 | lower proximitized horizontal nanowire |
| 2 | superconducting backbone |
| 3 | gate and quantum-dot readout interface |

All four use a transport factor of `1.0`. This is intentional: no public device-physics result is converted into an invented deposition nonuniformity.

The region site counts, A/B reaction-rate constants, synthetic growth scalar, virtual process temperature/pressure/timing, and 32-cycle surrogate are software-test parameters. The recipe explicitly states that the cycle count has **no fabrication mapping**.

## What is intentionally not encoded

This recipe does not invent or encode:

- epitaxial growth temperatures, pressures, rates, or fluxes;
- undisclosed barrier composition or thickness;
- precursor chemistry;
- lithography resist stacks, doses, masks, or exposure conditions;
- etch chemistry, plasma conditions, timing, or endpoint procedures;
- Pb deposition conditions;
- gate-metal or dielectric fabrication conditions not explicitly represented by public source data;
- annealing or cleaning recipes;
- wire-bonding/packaging procedures;
- cryogenic operating setpoints;
- magnetic-field operating recipes;
- production calibration or equipment-specific instructions.

## Run the reference recipe

Validate and run the generic simulator representation:

```bash
ald-media-controller validate recipes/majorana2_public_specs_reference_sim.json

ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/majorana2-reference-direct
```

The legacy QR/HLS media mode remains supported:

```bash
ald-media-controller compile \
  recipes/majorana2_public_specs_reference_sim.json \
  --output build/majorana2-reference-media

ald-media-controller verify build/majorana2-reference-media/stream.m3u8

ald-media-controller simulate-media \
  build/majorana2-reference-media/stream.m3u8 \
  --seed 42 \
  --output build/majorana2-reference-media-run
```

### Product-MP4 mode

Product mode produces one human-facing MP4 whose video track shows the product/reference stage rather than a QR code:

```bash
ald-media-controller compile-product \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/majorana2-product

ald-media-controller verify-product build/majorana2-product/bundle.json

ald-media-controller simulate-product \
  build/majorana2-product/bundle.json \
  --seed 42 \
  --output build/majorana2-product-run
```

The bundle contains:

```text
product.mp4
product.json
product-top.svg
product-stack.svg
product-final.svg
recipe.canonical.json
bundle.json
```

The MP4 has exactly three transport streams in the supported profile:

1. **H.264 video** — deterministic public-reference product-stage visualization. It shows the material stack, H-shaped tetron, three functional gate layers, five quantum dots (three shared), simulation status, and final composed reference view.
2. **AAC audio** — the existing redundant Manchester/BFSK sequence-and-ALD1-digest witness.
3. **`bin_data` / `gpmd` data** — authoritative timed ALDP v1 instruction records. Each real sample carries one bounded canonical packet plus sequence, timing, chained digest, CRC-32, and zero padding.

`gpmd` is used only as an FFmpeg/MOV/MP4 transport fourcc for the binary data stream. The payload is **Substitute's ALDP v1 format**, not GoPro GPMF telemetry.

The product video pixels are never parsed as instructions. There is no QR/OCR fallback in product verification. Executable `HashedPacket` objects are returned only after the binary data track, ALD1 hash chain/root, BFSK witness, canonical recipe, product JSON, deterministic SVG views, artifact digests, timing/profile constraints, and any requested Ed25519 signature all agree.

`product.json` is canonical JSON and explicitly contains:

```json
"physical_fabrication_mapping": false
```

The three-second per-packet media interval is transport framing only; it is not a real or simulated fabrication-step duration.

### Mode comparison

| Mode | Human-facing visual | Authoritative instruction source | Independent witness | Container |
| --- | --- | --- | --- | --- |
| Direct | reports only | canonical recipe/ALD1 packets | none | none |
| QR media | QR instruction frames | decoded QR canonical packet | BFSK sequence/digest audio | local HLS/fMP4 |
| Product MP4 | Majorana 2 public-reference schematic | ALDP v1 timed `bin_data/gpmd` samples | BFSK sequence/digest audio | single MP4 bundle |

Both media modes converge to the same verified canonical packet objects before simulator execution. For the same recipe and simulation seed, direct and product-MP4 execution are required by CI to produce byte-identical `cycles.csv` and `surface-final.json`.

The public metadata is preserved in `recipe.canonical.json` and bound into the bundle through SHA-256. The ALD1 packet chain continues to cover the executable instruction packets independently of the display representation.

## Verification in this repository

`tests/test_phase_one_acceptance.py` requires this checked-in recipe to:

- exist;
- pass `ald-media-controller validate`;
- run twice with seed 42 without a fault artifact;
- produce byte-identical `audit.jsonl`, `cycles.csv`, and `surface-final.json` across the two runs.

Product-specific tests and `.github/workflows/product-mp4.yml` additionally require:

- a real H.264/AAC/`bin_data(gpmd)` product MP4;
- byte-exact ALDP data-track round-trip;
- BFSK sequence/digest agreement;
- deterministic public-reference JSON/SVG binding;
- `physical_fabrication_mapping=false`;
- visible H-tetron/gate/QD/stack reference structure;
- rejection of audio, manifest, artifact, recipe, view, and signature tampering;
- byte-identical direct/product simulation reports for seed 42.

These checks verify deterministic use by Substitute. They do **not** validate the physical Majorana 2 device claims or reproduce the real device fabrication process.

## Public sources

Primary reference:

- M. Aghaee et al., **“20 Second Parity Lifetime in an InAs-Pb Tetron Device”**, arXiv:2606.03884, submitted 2 June 2026: https://arxiv.org/abs/2606.03884
- Microsoft Quantum, **“Majorana 2 – Microsoft’s scalable quantum processor with reliable, long-lasting qubits”**, 2 June 2026: https://quantum.microsoft.com/en-us/insights/blogs/majorana-2-scalable-quantum-processor

Independent context on the scientific debate:

- D. Castelvecchi, **“Microsoft upgrades controversial quantum chip — researchers are still sceptical”**, *Nature* 654, 308–309 (2026): https://www.nature.com/articles/d41586-026-01788-y
- H. F. Legg, **“On the robustness of topological gap detection via transport”**, *Nature* 654, E22–E26 (2026): https://www.nature.com/articles/s41586-026-10567-8
- Microsoft Quantum, **Reply to: “On the robustness of topological gap detection via transport”**, *Nature* 654, E27–E28 (2026): https://www.nature.com/articles/s41586-026-10568-7

Use the primary technical paper as the source of record for numerical device fields in this recipe. External news/commentary is included only to make the scientific-status caveat explicit.