# 1,000-Material Catalog Design

Date: 2026-09-05
Status: approved design
Branch: `feature/material-catalog-1000`

## Goal

Extend Substitute with a deterministic, provenance-backed catalog of exactly 1,000 counted real, non-elemental, thin-film/materials-relevant compounds while preserving the existing executable ALD/MLD recipe catalog and its safety boundary.

The 1,000-material milestone is a materials-identity catalog, not a claim that 1,000 experimentally established ALD/MLD processes exist. Only materials with defensible process evidence may link to executable Substitute recipes.

## Non-goals

This work does not:

- invent or infer ALD/MLD process conditions for materials that lack process evidence;
- convert catalog-only materials into executable recipes;
- add operational fabrication parameters, hardware control, process-network integration, or equipment instructions;
- treat material identity as evidence of precursor compatibility, interface compatibility, deposition feasibility, or fabrication readiness;
- make normal Substitute CLI execution depend on external network services;
- replace the existing `recipes/compounds/catalog.json` recipe index.

## Milestone counting rule

The milestone count is exactly 1,000 unique non-elemental reduced formulas.

Counted records must:

1. represent a real compound with fixed stoichiometry;
2. contain at least two distinct elements;
3. have a parseable formula that can be normalized to a reduced formula;
4. have at least one verifiable public identity/provenance source;
5. pass the deterministic materials-relevance filter;
6. be unique by reduced formula within the counted set.

Elemental materials may exist in the material catalog for linkage/backward compatibility but do not contribute to the 1,000 count. Variable-composition or symbolic formulas such as `CoSx` may also exist as supplemental records when needed to link existing recipe metadata, but do not contribute to the 1,000 fixed-stoichiometry count.

Polymorphs, space groups, duplicate literature structures, and repeated source records do not increase the count. They are merged beneath the material identified by the reduced formula.

For this milestone, CI asserts `counted_non_elemental_reduced_formula_count == 1000`. A future catalog-version change may deliberately raise this number.

## Existing recipe catalog remains authoritative for executable processes

`recipes/compounds/catalog.json` remains the deterministic executable-recipe index generated from checked-in recipe JSON files.

Its semantics remain unchanged:

- each entry refers to a validated `multi-precursor/1` recipe;
- every recipe remains simulation-only with `physical_fabrication_mapping=false`;
- source references remain mandatory;
- existing `ald-master`, compatibility, HLS, Product MP4, and recipe tests continue to consume the recipe catalog as before.

The new materials catalog is additive and must not weaken these invariants.

## New material catalog

Add a separate deterministic artifact:

- `materials/catalog.json`
- schema: `ald-material-catalog/1`

Supporting committed artifacts:

- `materials/source-manifest.json`
- `materials/build-audit.json`
- a frozen normalized source snapshot under `materials/sources/` sufficient to rebuild the exact committed catalog without network access

The frozen source snapshot stores only the normalized source fields needed by the builder and provenance audit, not a wholesale mirror of COD or PubChem.

### Material record

Each record has a stable schema similar to:

```json
{
  "material_id": "mat-hfo2",
  "name": "hafnium dioxide",
  "formula": "HfO2",
  "reduced_formula": "HfO2",
  "elements": ["Hf", "O"],
  "counted": true,
  "material_classes": ["oxide", "dielectric"],
  "identifiers": {
    "cod_ids": ["..."] ,
    "pubchem_cid": "...",
    "inchikey": "..."
  },
  "phases": [
    {
      "source": "cod",
      "source_id": "...",
      "space_group": "..."
    }
  ],
  "provenance": [
    {
      "source": "cod",
      "source_id": "...",
      "evidence": "crystallographic_identity"
    }
  ],
  "process_evidence": {
    "status": "executable-recipe",
    "recipe_ids": ["..."]
  }
}
```

Fields that are not available from a source are omitted or null according to the schema; they are never guessed.

### Stable IDs

For counted fixed-stoichiometry records, `material_id` is derived deterministically from the normalized reduced formula through a collision-safe slugging function. The reduced formula remains the milestone identity key.

Supplemental non-counted records that cannot use a fixed reduced formula receive deterministic IDs derived from normalized formula/name plus an explicit supplemental namespace.

## Source architecture

### Primary source: Crystallography Open Database

COD is the primary existence and structural-provenance anchor for counted solid materials. COD states that its data and database are dedicated to the public domain under CC0 while asking users to acknowledge original structural authors.

Reference: https://www.crystallography.net/cod/

The refresh tool records COD identifiers and, where present, bibliographic metadata and structural fields needed for phase subrecords.

### Identity normalization: PubChem

PubChem is used as optional identity normalization/enrichment where a reliable match exists. PUG REST supports programmatic retrieval by formula and identifiers and exposes properties including molecular formula, CID, InChI, InChIKey, IUPAC name, and title.

Reference: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest

A valid COD-backed material is not rejected merely because PubChem has no unique/usable match. An unresolved PubChem lookup is recorded as missing enrichment, not negative evidence.

### Optional enrichment: Materials Project

Materials Project may enrich records when credentials are available, but it is not a dependency for the canonical committed build. Its supported `mp-api` client requires an API key tied to a Materials Project account.

Reference: https://docs.materialsproject.org/downloading-data/using-the-api/getting-started

Canonical CI and normal CLI operation must succeed without a Materials Project API key.

## Provenance policy

Every counted material requires public identity evidence. Direct ALD/MLD literature is required only when Substitute claims process evidence or links an executable recipe.

Evidence classes are kept distinct:

- `chemical_identity`: public chemical identity record;
- `crystallographic_identity`: COD structure/phase record;
- `materials_identity`: other vetted public materials record;
- `process_literature`: direct deposition/process literature already associated with an executable recipe;
- `optional_enrichment`: non-canonical additional metadata.

Identity evidence never automatically becomes process evidence.

## Ingestion and normalization pipeline

The refresh pipeline is network-capable and separate from the offline deterministic builder.

```text
COD candidates
   -> source-field extraction
   -> formula parser
   -> reject elemental-only for counted set
   -> reject variable/ambiguous formulas for counted set
   -> reduced-formula normalization
   -> merge duplicate reduced formulas
   -> deterministic materials-relevance classification
   -> optional PubChem normalization
   -> merge phase/source records
   -> link existing Substitute recipe materials
   -> deterministic scoring/selection
   -> freeze normalized source snapshot

frozen normalized source snapshot
   -> offline deterministic builder
   -> materials/catalog.json
   -> materials/source-manifest.json
   -> materials/build-audit.json
```

### Formula normalization

Implement a deterministic formula parser suitable for inorganic/material formulas in the selected source set. It must handle conventional element/count notation and parentheses needed by accepted records, normalize integer stoichiometry by greatest common divisor, and return a canonical reduced formula.

The parser rejects formulas it cannot interpret unambiguously. The builder does not repair or guess malformed formulas.

The counted set excludes symbolic stoichiometry (`x`, `y`, ranges, occupancies without a fixed resolved composition) and elemental-only formulas.

### Deduplication

The counted identity key is reduced formula. If multiple COD entries normalize to the same reduced formula:

- create one material record;
- merge unique source IDs;
- merge phase/polymorph records deterministically;
- preserve source-specific names as aliases only when useful and non-conflicting;
- choose the canonical display name by a deterministic source-precedence rule;
- never count duplicates more than once.

### Materials relevance

The catalog is materials/thin-film focused rather than a generic chemical database.

Eligible classes include:

- oxides;
- nitrides;
- sulfides, selenides, and tellurides;
- fluorides and other inorganic halides;
- carbides;
- borides;
- silicides;
- phosphides and arsenides;
- intermetallics;
- perovskites and related complex oxides;
- spinels;
- transparent conductors;
- ionic and battery materials;
- semiconductors;
- catalysts;
- dielectrics;
- magnetic materials;
- refractory ceramics;
- selected layered/2D materials;
- a limited, explicitly classified MLD/hybrid-material section.

Organic molecules are excluded unless they belong to the explicitly allowed MLD/hybrid-material class.

Classification and relevance selection must be deterministic and based on explicit composition/source metadata. No LLM decision participates in the canonical selection.

### Deterministic selection

After validation, normalization, deduplication, and relevance filtering, candidates receive a deterministic relevance score derived only from documented composition/classes/source coverage. Stable lexical/source-ID tie-breaking determines order where scores are equal.

The builder selects exactly 1,000 counted records. The selection algorithm and weighting are versioned in source control so catalog changes are explainable.

## Frozen source snapshot and rebuildability

Normal runtime and CI are offline.

The network refresh tool:

1. retrieves candidate/source data;
2. applies rate limits/retries appropriate to each public service;
3. records retrieval metadata;
4. emits a normalized frozen source snapshot;
5. records unresolved enrichments without inventing replacements.

The offline builder consumes the frozen snapshot and repository recipes only.

`materials/source-manifest.json` records at least:

- schema/version;
- source names;
- source endpoints or dataset identifiers;
- retrieval timestamp for refresh provenance;
- refresh parameters;
- source/snapshot hashes;
- builder version/model version;
- target counted size (1,000).

The retrieval timestamp belongs in the manifest, not in canonical material records, so rebuilding from the same snapshot remains byte-identical.

Two builds from identical frozen inputs must produce byte-identical `catalog.json`, `source-manifest.json` (for the frozen snapshot), and `build-audit.json`.

## Build audit

`materials/build-audit.json` is deterministic and contains at least:

- raw candidate count;
- parseable candidate count;
- elemental exclusions;
- variable/ambiguous-formula exclusions;
- materials-relevance exclusions;
- duplicate reduced-formula collapses;
- provenance failures;
- PubChem enrichment success/unresolved counts;
- accepted candidate count before final selection;
- exact counted catalog size;
- class distribution;
- element distribution summary;
- number of materials linked to executable recipes;
- exact ordered final 1,000 material IDs;
- hashes of the frozen source inputs and final catalog.

No nondeterministic timestamps are written into the audit.

## Recipe linkage

The material builder reads `recipes/compounds/catalog.json` and links existing executable recipes to material records where normalization is unambiguous.

For recipe target formulas that are fixed and normalize cleanly, link by normalized reduced formula.

For existing symbolic/nonstoichiometric target formulas, link only through an explicit reviewed mapping or a supplemental non-counted material record. Do not force such formulas into the counted fixed-stoichiometry set.

A material record may therefore have:

- zero executable recipes;
- one executable recipe;
- multiple executable recipe variants.

The absence of a recipe means only that Substitute has no executable process representation for that material.

## CLI integration

Add material-discovery commands to `ald-master`:

```text
ald-master materials search TEXT [--limit N] [--json]
ald-master materials show MATERIAL [--json]
ald-master materials list [--class CLASS] [--element ELEMENT] [--limit N] [--json]
ald-master materials report [--json]
```

### `materials search`

Searches deterministically across:

- formula;
- reduced formula;
- canonical name;
- aliases where present;
- elements;
- material classes;
- source identifiers.

Ranking is deterministic and favors exact formula/ID matches, then exact names, then prefix/substring metadata matches.

### `materials show`

Shows identity, formula, elements, classes, provenance, phase/source summaries, optional normalized identifiers, counted status, and linked executable recipes.

### `materials list`

Supports deterministic filtering by class and/or element. Default ordering is stable and documented.

### `materials report`

Reports:

- total material records;
- exactly 1,000 counted non-elemental reduced formulas;
- supplemental/elemental record counts;
- class distribution;
- provenance coverage;
- PubChem enrichment coverage;
- recipe-linked material count.

## Compatibility integration

The existing compatibility engine remains evidence-bearing and anchored to the executable recipe catalog.

Do not expand the exhaustive directed material graph to all 1,000 catalog-only materials merely because their identities are known. At 1,000 nodes this would create roughly 999,000 directed interfaces dominated by missing evidence and would blur the distinction between identity and compatibility evidence.

Behavior for catalog-only materials:

- the CLI recognizes the material identity from `materials/catalog.json`;
- if no evidence-bearing compatibility node exists, report explicitly that the identity is known but compatibility evidence is unavailable/`UNKNOWN`;
- never interpret missing compatibility evidence as incompatibility;
- never synthesize compatibility edges from identity/classification alone.

Existing precursor candidate ranking remains process/precursor based and therefore remains anchored to executable recipes.

A future separately designed change may add sparse evidence-bearing compatibility nodes from direct literature without changing this milestone architecture.

## Safety boundary

The expanded catalog remains research/simulation infrastructure.

The material catalog contains identity, provenance, classification, and high-level materials metadata only. It must not introduce:

- process temperature/windows;
- pulse/dose timing;
- gas flow;
- pressure;
- equipment settings;
- precursor handling instructions;
- live hardware control;
- inferred fabrication mappings.

Executable recipes keep the repository's existing safety assertions and simulation notices.

## Tests and acceptance criteria

### Material catalog unit tests

Add tests that prove:

- schema is valid and canonical;
- counted fixed-stoichiometry record count is exactly 1,000;
- counted reduced formulas are unique;
- every counted record is non-elemental;
- every counted record has a parseable fixed reduced formula;
- every counted record has non-empty provenance;
- stable material IDs are unique;
- deterministic sorting is enforced;
- duplicate source formulas collapse into one record;
- phases/source IDs are merged without changing count;
- elemental and symbolic records are excluded from the milestone counter;
- no prohibited process/operational metadata appears in material records.

### Determinism tests

Given identical frozen source snapshots and recipe catalog inputs:

- two builder runs produce byte-identical `materials/catalog.json`;
- two builder runs produce byte-identical `materials/source-manifest.json`;
- two builder runs produce byte-identical `materials/build-audit.json`.

Checked-in artifacts must equal freshly generated canonical bytes.

### Recipe-link tests

Prove that:

- every unambiguously fixed-formula recipe target that has a matching material resolves to its recipe ID/path;
- no catalog-only material is treated as executable;
- symbolic/nonstoichiometric recipe targets are handled only by explicit supplemental mapping when needed.

### CLI tests

Cover text and JSON output for:

- `materials search`;
- exact formula lookup;
- exact material ID lookup;
- `materials show`;
- `materials list --class ...`;
- `materials list --element ...`;
- combined filters;
- `materials report`;
- not-found behavior.

### Compatibility regression tests

Prove that:

- existing compatibility snapshot semantics remain unchanged for recipe-backed nodes;
- querying a known catalog-only material returns known identity plus `UNKNOWN`/unavailable evidence;
- missing evidence is not reported as incompatible;
- precursor candidate ranking does not automatically expand to catalog-only material identities.

### Repository-wide verification

Before the feature is ready for review:

- full pytest suite passes;
- Python modules compile;
- existing compound-recipe catalog canonical check passes;
- material catalog canonical check passes;
- Product MP4 acceptance remains green;
- HLS integration remains green.

## Expected implementation structure

Exact filenames may be adjusted to follow repository conventions, but the implementation should remain separated into focused units similar to:

- `ald_materials/` or `ald_materials.py` — offline material catalog model/query functions;
- `tools/refresh_material_sources.py` — network-capable source refresh/enrichment;
- `tools/build_material_catalog.py` — offline deterministic builder;
- `materials/sources/` — normalized frozen source inputs;
- `materials/catalog.json` — canonical 1,000-counted-material catalog;
- `materials/source-manifest.json` — source/rebuild provenance;
- `materials/build-audit.json` — deterministic selection audit;
- `tests/test_material_catalog.py` — schema/count/determinism tests;
- `tests/test_material_cli.py` — discovery CLI tests;
- compatibility regression coverage in the existing compatibility/master test modules.

The refresh and offline build responsibilities must remain separate so network behavior cannot leak into CI/runtime code paths.

## Delivery strategy

Implementation follows TDD on `feature/material-catalog-1000`.

Recommended sequence:

1. add failing schema/count/formula-normalization tests;
2. implement offline material schema/parser/builder against a minimal fixture;
3. add deterministic source normalization and audit generation;
4. build the frozen real-material source snapshot and exact 1,000 record selection;
5. add recipe linkage;
6. add CLI discovery commands;
7. add compatibility known-identity/unknown-evidence behavior;
8. regenerate canonical artifacts;
9. run full repository verification, Product MP4, and HLS acceptance;
10. open a PR with source/audit statistics and verification evidence.

No merge is part of this design unless separately requested.