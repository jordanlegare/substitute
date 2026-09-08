# Exhaustive recipe-motif combinations

This index contains **397,811 distinct component sets**, representing
**48,534,764 ordered component sequences**, from the **59 recipes currently
marked `established` in the compound catalog**. Any represented order can be
exported as a validated simulator recipe.

These are **combinations of recognized component chemistries, not 397,811
experimentally established stack recipes**. The seed labels and references are
inherited from the repository; individual precursor-route claims have not all
been independently re-audited. In particular, a review citation is not proof
of a complete stack or of every specific route. Generated output is marked
`conceptual-multicomponent-surrogate` and `combination_evidence: not-established`.
No compatibility score, experimental process window, or interface evidence is
invented. The existing compatibility graph and 8,000-material identity catalog
are unchanged, so generated combinations cannot reinforce their own evidence.

## Coverage

| Distinct component recipes | Component sets | Ordered component sequences |
| --- | ---: | ---: |
| 2 | 1,711 | 3,422 |
| 3 | 32,177 | 193,062 |
| 4 | 175,430 | 4,210,320 |
| 5 | 152,645 | 18,317,400 |
| 6 | 35,848 | 25,810,560 |
| **Total** | **397,811** | **48,534,764** |

Enumeration is exhaustive within these explicit bounds:

- Two through six **distinct source recipe IDs**, each used once per supercycle.
- At most six unique precursors and twelve sequential exposures, as required by
  the existing simulator schema. Shared chemical identities merge even when
  their component roles differ, such as source and dopant.
- One full exposure motif from each component, preserving its internal order,
  doses and purges. Original whole-recipe repeat counts are not copied: this is
  a new equal-motif supercycle, not reproduction of source layer ratios.
- All cross-family sets fitting those structural limits are included. This is
  structural eligibility, not a finding of chemical or interface compatibility.
- Different precursor routes to the same material remain distinct components.
  Ordered sequence counts distinguish component order, not experimentally
  distinct products. They do not establish a lower bound on distinct outcomes.
- No arbitrary beam width, top-N cut-off, speculative identity-only seed,
  repeated component, additional mixing ratio, or fabricated new chemistry.

There is no finite exhaustive collection if arbitrary repetition and ratios are
allowed. This release fully enumerates the bounded space above.

## Files and provenance

`manifest.json` records source IDs, paths, SHA-256 hashes, chemical identities,
references, counting rules and a digest of the decompressed index.
`combinations.jsonl.gz` has one JSON array per component set; each integer is
a zero-based index into `manifest.json`'s `seeds` array. Ascending indices give
the canonical order; every permutation is exportable. The compressed index
avoids committing hundreds of thousands of repetitive full recipe files.

`examples/` contains ready-to-run exports across oxide, nitride, chalcogenide,
mixed-family and doped-oxide motifs, including the twelve-exposure boundary.

## Rebuild and verify

From the repository root, after installing the project:

```bash
python tools/build_recipe_combinations.py build
python tools/build_recipe_combinations.py check
python -m pytest tests/test_recipe_combinations.py -q
```

Enumeration uses monotone pruning: adding components cannot reduce precursor
or exposure counts. No eligible superset is lost. Output has deterministic seed
ordering, rows, manifest and gzip headers. The checked digest covers uncompressed
bytes so checks remain portable across compression-library versions.

For a smaller, separate exploration:

```bash
python tools/build_recipe_combinations.py build --max-components 3 --output build/small-combinations
```

## Export any order and run it

Use IDs from the manifest, in the desired component order:

```bash
python tools/build_recipe_combinations.py export \
  cat-oxid-al2o3_tma_water-001 \
  cat-oxid-tio2_ticl4_water-001 \
  cat-oxid-zno_dez_water-001 \
  --output build/al2o3-tio2-zno.json
ald-media-controller validate build/al2o3-tio2-zno.json
ald-media-controller simulate build/al2o3-tio2-zno.json --seed 42 --output build/combined-direct
```

The exporter preserves component-specific references and exposure ranges,
assigns shared precursor IDs, uses the existing generic simulator envelope,
and validates and compiles the result before writing it. Reversing component
order changes the sequence and recipe ID. References support component
recognition only. All exported numeric parameters remain synthetic.
