# Commercial-product surrogate recipes

These recipes are inputs to Substitute's **offline simulator**. They represent ALD-relevant portions of recognizable commercial semiconductor products, but they are not production recipes and do not encode real fabrication conditions.

All three use generic `A-sim` / `B-sim` chemistry, the current `site-binomial/1` aggregate surface model, and explicitly set `physical_fabrication_mapping` to `false` in metadata. Region names are conceptual labels used to interpret the simulator's transport-factor gradient.

## CMOS high-k gate dielectric

`cmos_high_k_gate_sim.json` represents a shallow three-region gate dielectric coating surrogate: top surface, sidewall, and channel-adjacent interface.

```bash
ald-media-controller validate recipes/products/cmos_high_k_gate_sim.json
ald-media-controller simulate recipes/products/cmos_high_k_gate_sim.json --seed 42 --output build/cmos-high-k
```

## DRAM MIM capacitor dielectric

`dram_mim_capacitor_sim.json` represents a five-region capacitor-depth surrogate from the feature opening to the capacitor bottom. Decreasing transport factors model progressively less accessible regions.

```bash
ald-media-controller validate recipes/products/dram_mim_capacitor_sim.json
ald-media-controller simulate recipes/products/dram_mim_capacitor_sim.json --seed 42 --output build/dram-mim
```

## 3D NAND conformal liner

`nand_3d_liner_sim.json` represents a seven-region high-aspect-ratio depth surrogate from the feature opening to the bottom. It is intended to exercise conformality and transport-limited coverage behavior in the existing aggregate model.

```bash
ald-media-controller validate recipes/products/nand_3d_liner_sim.json
ald-media-controller simulate recipes/products/nand_3d_liner_sim.json --seed 42 --output build/nand-3d-liner
```

The executable pulse, purge, temperature, pressure, cycle, transport, and growth values in these files are synthetic simulator parameters. They must not be interpreted as equipment setpoints, material recipes, or semiconductor manufacturing instructions.
