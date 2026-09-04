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

For the complete recipe schema and opcode reference, see `docs/recipe-authoring.md`.
