# Material identity catalog

Substitute maintains two deliberately separate catalogs:

1. `recipes/compounds/catalog.json` is the executable simulation-recipe index. It is generated from checked-in `multi-precursor/1` recipes and remains the source for recipe-backed compatibility evidence and candidate ranking.
2. `materials/catalog.json` is the provenance-backed material identity catalog. Its `ald-material-catalog/1` schema contains exactly 1,000 counted, unique, non-elemental fixed-stoichiometry reduced formulas for the current milestone.

A material appearing in `materials/catalog.json` is **not** a claim that Substitute has a validated ALD/MLD process for it. Most entries are identity-only. Only records whose `process_evidence.status` is `executable-recipe` link to checked-in Substitute recipe IDs and paths.

## Scientific boundary

The material catalog stores identity and high-level materials metadata only:

- canonical and reduced formulas;
- element sets;
- material classes;
- public source identifiers;
- crystallographic phase/source summaries;
- optional PubChem identity normalization;
- links to existing executable Substitute recipes when an exact fixed-formula match exists.

It does not add process temperatures, pulse/dose timing, flow, pressure, equipment settings, precursor-handling instructions, fabrication mappings, or live hardware controls.

Identity evidence is not compatibility evidence. If a catalog-only material is queried through `ald-master compatible material`, the CLI reports the identity as known while compatibility evidence remains `E0_UNKNOWN` / `UNKNOWN`.

## Counted milestone

For `ald-material-catalog/1`, CI requires exactly 1,000 counted records. A counted record must:

- have a fixed parseable chemical formula;
- contain at least two distinct elements;
- normalize to a unique reduced formula;
- have public provenance;
- pass the deterministic materials-relevance selection policy.

Polymorphs, multiple COD structures, and repeated literature structures merge under one reduced-formula material identity. Elemental and symbolic/nonstoichiometric records do not contribute to the 1,000 count.

## Provenance

The primary existence and structural-provenance source is the Crystallography Open Database (COD). The committed frozen source snapshot preserves normalized COD metadata, including COD identifiers and available phase/bibliographic fields, rather than mirroring CIF payloads.

The canonical snapshot for this milestone was acquired from a dated public mirror of COD metadata and retains COD as the provenance source. The mirror is transport only; it does not replace COD identity/provenance.

PubChem enrichment is optional. An enrichment is accepted only when the query resolves unambiguously and its returned molecular formula normalizes to the same reduced formula. Failure or ambiguity in PubChem does not invalidate a COD-backed material.

Materials Project is not required to build or use the canonical catalog.

## Offline deterministic build

Normal runtime and CI do not access external material databases. The committed normalized inputs are:

```text
materials/sources/cod-materials.json
materials/sources/pubchem-identities.json
```

The canonical outputs are:

```text
materials/catalog.json
materials/source-manifest.json
materials/build-audit.json
```

Rebuild them offline with:

```bash
python tools/build_material_catalog.py --target-count 1000
```

Verify that the checked-in artifacts are byte-identical to a rebuild from the frozen inputs with:

```bash
python tools/build_material_catalog.py --check --target-count 1000
```

`materials/build-audit.json` records the source candidate counts, exclusions, duplicate collapses, class and element distributions, PubChem enrichment coverage, recipe-link coverage, ordered final material IDs, and input/output digests.

## `ald-master` discovery commands

Search across formulas, canonical names, aliases, elements, classes, and source identifiers:

```bash
ald-master materials search hafnium
ald-master materials search HfO2 --json
```

Show one identity with provenance and linked process status:

```bash
ald-master materials show HfO2
ald-master materials show mat-hfo2-... --json
```

Filter the catalog deterministically:

```bash
ald-master materials list --class oxide --element Hf --limit 50
ald-master materials list --class nitride --json
```

Summarize the catalog:

```bash
ald-master materials report
ald-master materials report --json
```

Use a non-default catalog artifact with the global switch:

```bash
ald-master --materials-catalog path/to/catalog.json materials report
```

## Compatibility behavior

The exhaustive compatibility snapshot remains bounded to the executable recipe catalog. The 1,000 identity records are **not** expanded into a roughly one-million-edge mostly-unknown graph.

For a recipe-backed material, existing compatibility queries behave as before. For a catalog-only material, the CLI can resolve the identity but returns unavailable compatibility evidence explicitly as `UNKNOWN`; missing evidence is never treated as incompatibility.

Candidate ranking remains precursor/process based and is not enlarged simply because additional material identities are known.
