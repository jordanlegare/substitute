# Simulation Recipes

All recipes in this directory are inputs to Substitute's **offline simulator**. They are not machine-operation instructions or production fabrication recipes.

## `generic_al2o3.json`

The checked-in acceptance recipe for the generic A/B ALD simulation mapping. It is used by CI to exercise direct simulation, media compilation, verification, and direct/media equivalence.

Run:

```bash
ald-media-controller validate recipes/generic_al2o3.json
ald-media-controller simulate recipes/generic_al2o3.json --seed 42 --output build/al2o3-direct
```

## `majorana_topological_stack_sim.json`

A **Majorana-inspired topological-device interface simulation** built from the same generic A/B controller and `site-binomial/1` surface model.

It does **not** describe fabrication of a real Majorana device. Real epitaxy, superconducting-film growth, lithography, etching, metallization, cryogenic device physics, hazardous chemistry, and equipment operation are intentionally outside the recipe.

Run:

```bash
ald-media-controller validate recipes/majorana_topological_stack_sim.json
ald-media-controller simulate \
  recipes/majorana_topological_stack_sim.json \
  --seed 42 \
  --output build/majorana-direct
```

For its conceptual mapping, structural verification values, and media commands, see `docs/majorana-topological-stack-sim.md`.

## `majorana2_public_specs_reference_sim.json`

A **public-spec reference model for Microsoft's 2026 Majorana 2 InAs-Pb tetron platform**. It carries publicly reported material-stack, tetron-geometry, gate/quantum-dot, and selected device-characterization values as recipe metadata while keeping the executable process explicitly generic and simulation-only.

Public reference metadata includes the reported GaSb / InAs / InAs0.8Sb0.2 / Pb material platform, 10 nm Pb, the H-shaped two-wire tetron dimensions, the three functional gate layers, five-QD readout architecture, and selected reported gap/parity-lifetime values. Missing or undisclosed process details are not guessed.

The executable A/B pulse/purge cycles, aggregate surface parameters, temperature, pressure, timing, and cycle count are **synthetic simulator inputs with no fabrication mapping**.

Run:

```bash
ald-media-controller validate recipes/majorana2_public_specs_reference_sim.json
ald-media-controller simulate \
  recipes/majorana2_public_specs_reference_sim.json \
  --seed 42 \
  --output build/majorana2-reference-direct
```

For the source mapping, public values, scientific-status caveat, and explicit non-modeled fields, see `docs/majorana2-public-spec-reference.md`.

For the complete recipe schema and opcode reference, see `docs/recipe-authoring.md`.
