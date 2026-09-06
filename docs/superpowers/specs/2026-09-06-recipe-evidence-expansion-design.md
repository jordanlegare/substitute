# Recipe Evidence Expansion Design

## Status

Approved design for maximizing distinct recipe-backed materials in Substitute without fabricating ALD/MLD chemistry.

## Goal

Expand the executable compound-recipe catalog to the maximum defensible number of **distinct target materials** supported by real ALD, plasma-enhanced ALD (PEALD), molecular layer deposition (MLD), or hybrid-process literature, while preserving Substitute's simulation-only safety boundary and all existing recipe paths.

There is no arbitrary recipe-count target. The stopping condition is evidence exhaustion across the 8,000-material identity catalog and the configured public literature sources.

## Locked product decisions

1. **One best new recipe per material.** Different precursor/co-reactant chemistries for the same newly supported target do not produce multiple new recipes.
2. **Existing duplicate target recipes remain untouched.** The one-best rule applies only to expansion recipes, preserving backward compatibility.
3. **Literature must support chemistry, not operating conditions.** A source must explicitly support the target material plus precursor/co-reactant chemistry. Substitute continues to use synthetic simulator timing, dose, purge, temperature, pressure, and other executable values.
4. **Process scope:** thermal ALD, PEALD, MLD, and hybrid cyclic deposition processes.
5. **Hybrid evidence funnel:** AtomicLimits is the primary process-discovery index; direct scholarly metadata/search is the fallback for unmatched materials.
6. **No inferred analogue chemistry.** Similarity to another material or precursor family never creates an executable recipe.

## Scientific and safety boundary

The expansion distinguishes three layers:

- **Material identity evidence** — the 8,000-material catalog establishes that a fixed-stoichiometry compound identity is known.
- **Process chemistry evidence** — direct literature establishes that a target was deposited using explicit precursor/co-reactant chemistry.
- **Synthetic simulator execution** — Substitute supplies non-physical simulator parameters needed by `multi-precursor/1` recipes.

Only the second layer can upgrade a material from identity-only to recipe-backed. The generated recipe must continue to state `physical_fabrication_mapping: false` and use the repository's simulation-only notice.

The acquisition/generation system must not copy or operationalize literature values for process temperature, pressure, dose/pulse timing, purge duration, plasma power, plasma bias, gas flow, hardware configuration, reactor geometry, or handling instructions. These values are not selection criteria and are not accepted evidence fields.

## Evidence architecture

Every candidate passes through a staged record before any recipe file can be generated:

```text
8,000 material identities
        |
        v
already recipe-backed? ---- yes ---> preserve existing recipe(s), record covered
        |
        no
        v
AtomicLimits process match
        |
        v
publication / DOI resolution
        |
        v
extract target + precursor(s) + co-reactant(s)
        |
        v
evidence validator
        |
        v
rank competing chemistries
        |
        v
select one best chemistry per material
        |
        v
generate Substitute-safe simulator recipe
        |
        v
compile/validate + compound catalog rebuild + CI
```

A candidate is eligible only when a real publication or stable publication record explicitly supports both:

- the deposited target material; and
- every precursor/co-reactant identity required to characterize the reported cyclic chemistry.

If either side is ambiguous, the candidate is rejected rather than guessed.

## Evidence record schema

The normalized evidence ledger lives at:

```text
recipes/evidence/process-evidence.json
```

Each candidate record stores only non-operational chemistry/provenance information:

- target material name;
- target formula and normalized reduced formula;
- material catalog ID where available;
- process family: `thermal-ald`, `plasma-ald`, `mld`, or `hybrid`;
- precursor/co-reactant names;
- precursor/co-reactant formulas where resolvable;
- precursor/co-reactant roles;
- DOI or another stable publication identifier;
- publication title/year/journal metadata when available;
- discovery source (`atomiclimits`, `crossref`, `openalex`, or fallback search source);
- evidence grade;
- selection status;
- deterministic rejection reason where rejected.

Operational process conditions are forbidden from this ledger.

## Evidence grades

### R3 — corroborated

A direct publication explicitly supports target plus full chemistry, and the chemistry is independently corroborated by at least one of:

- AtomicLimits indexing;
- another independent direct publication reporting the same normalized chemistry.

### R2 — direct

A resolvable direct publication explicitly reports the target and all required precursor/co-reactant identities.

### R1 — discovery only

A review, database mention, abstract-only match, ambiguous process description, unresolved reactant identity, or other secondary evidence that is useful for discovery but insufficient for generation.

**Only R2 and R3 can generate recipes. R1 never generates a recipe.**

## Deterministic best-chemistry selector

For each material without an existing recipe, all R2/R3 candidates are sorted by the following tuple, lowest value wins after normalizing booleans/counts appropriately:

1. stronger evidence grade (`R3` before `R2`);
2. complete normalized precursor/co-reactant identities before partial-name-only records;
3. more independent direct supporting publications;
4. fewer distinct reactants/precursors;
5. stable DOI/publication identifiers present;
6. deterministic normalized chemistry lexical key;
7. deterministic source/publication identifier tie-break.

The selector never uses reported temperature, pressure, dose, purge, growth rate, plasma power, or other operating conditions.

If two candidates remain genuinely indistinguishable after normalization and stable tie-break keys cannot be constructed, the material is rejected with `ambiguous-best-chemistry` rather than selected arbitrarily.

## Generated recipe policy

For every selected new material, generation produces exactly one `multi-precursor/1` recipe under the existing category directories used by `tools/build_compound_catalog.py`.

Literature controls only:

- target material;
- target formula;
- precursor identities;
- co-reactant identities;
- process-family label;
- source references.

Executable values remain synthetic simulator defaults/templates. Generated recipes must not contain copied literature operating conditions.

Recipe IDs and filenames are deterministic from the target reduced formula plus the normalized selected chemistry, so repeated generation cannot create duplicate paths or rename stable recipes.

Every generated recipe must satisfy the repository's existing hard gates:

- `metadata.recipe_schema == "multi-precursor/1"`;
- `metadata.physical_fabrication_mapping is false`;
- non-empty `metadata.source_references`;
- `surface.model_version == "site-sequential/1"`;
- all declared precursors are used by the deposition-cycle exposure list;
- precursor chemical names are unique within the recipe;
- `ald_core.validate_recipe(...)` succeeds;
- `ald_core.compile_recipe(...)` succeeds;
- forbidden operational metadata keys remain absent.

## Existing-recipe compatibility rule

The expansion is based on `feature/material-catalog-8000` and does not delete, rename, or rewrite existing recipe files.

Before acquisition/generation, existing recipe targets from `recipes/compounds/catalog.json` are normalized by reduced formula. Those materials are marked `already-recipe-backed` in the coverage audit and skipped for new generation even if additional literature chemistries are discovered.

This preserves existing CLI behavior, compatibility evidence, candidate ranking, recipe paths, and historical process variants.

## Acquisition source policy

### Primary process index — AtomicLimits

AtomicLimits is the primary discovery source for reported ALD processes and their literature references. It is used to identify candidate target/precursor/co-reactant combinations and associated publications.

### DOI normalization — Crossref

Crossref is the preferred DOI metadata authority for resolving DOI-linked bibliographic metadata and canonical publication identifiers.

### Secondary scholarly resolver — OpenAlex

OpenAlex is used for title/DOI resolution, related-work discovery, and fallback scholarly metadata when AtomicLimits records or publication metadata are incomplete.

### Fallback literature discovery

Fallback search runs only for material identities that remain unbacked after AtomicLimits resolution. Search terms combine canonical target names/formulas with process phrases such as:

- `atomic layer deposition`;
- `plasma-enhanced atomic layer deposition`;
- `PEALD`;
- `molecular layer deposition`;
- relevant hybrid cyclic-deposition terminology.

A fallback hit must still resolve to an R2/R3 direct chemistry record before it can generate a recipe.

## Network/runtime boundary

Network access is confined to an explicit refresh workflow/tool. Normal runtime, normal tests, deterministic builders, and canonical CI checks consume only frozen checked-in evidence artifacts.

Proposed files:

```text
recipes/evidence/
├── process-evidence.json
├── source-manifest.json
└── acquisition-audit.json

tools/
├── refresh_recipe_evidence.py
├── build_recipe_expansion.py
└── audit_recipe_evidence.py
```

`refresh_recipe_evidence.py` is the only network-capable component. It should support durable caching/resume so an interrupted 8,000-material sweep does not restart completed scholarly lookups.

`build_recipe_expansion.py` is deterministic and offline. It reads frozen evidence and writes/validates only expansion recipe files plus any deterministic generated indexes needed for auditing.

`audit_recipe_evidence.py` validates evidence schema, selection invariants, source references, and recipe/evidence linkage without network access.

## Automatic rejection rules

A candidate is rejected if any of the following applies:

- target formula is variable, symbolic, ambiguous, or cannot normalize to one fixed material identity;
- target does not map to a material in the 8,000-material catalog unless it is already present in the existing recipe catalog for backward compatibility;
- publication cannot be resolved to a DOI or another stable publication identifier;
- precursor identity is missing or ambiguous;
- required co-reactant identity is missing or ambiguous;
- the paper only mentions the material but does not report that deposition chemistry;
- the process is CVD, PVD, solution growth, sputtering, evaporation, or another non-cyclic deposition process rather than ALD/PEALD/MLD/hybrid;
- source evidence is only a review/database mention with no sufficiently resolved direct chemistry evidence;
- chemistry depends on an inferred precursor analogue or family substitution;
- target material already has an existing executable recipe;
- evidence remains R1;
- multiple candidates cannot be deterministically distinguished at the evidence level.

Every rejection is recorded with a deterministic reason code.

## Acquisition audit

`recipes/evidence/acquisition-audit.json` reports at minimum:

- total 8,000 material identities examined;
- existing recipe-backed material count;
- remaining identity-only material count before refresh;
- AtomicLimits candidate count;
- fallback-literature candidate count;
- direct publication records resolved;
- R3 accepted candidate count;
- R2 accepted candidate count;
- R1/rejected candidate count;
- ambiguous chemistry rejection count;
- non-ALD rejection count;
- unresolved publication rejection count;
- duplicate/already-backed material count;
- new distinct materials selected;
- additions by process family (`thermal-ald`, `plasma-ald`, `mld`, `hybrid`);
- final executable recipe count;
- remaining identity-only material count after expansion.

## Repository integration

The feature is implemented on `feature/recipe-evidence-expansion`, stacked on `feature/material-catalog-8000`.

The existing compound-catalog builder remains authoritative for `recipes/compounds/catalog.json`. New generated recipes are ordinary validated recipe files, so existing downstream compatibility/candidate logic sees them through the same catalog interface rather than through a special parallel execution path.

No existing recipe is removed or modified solely to satisfy the one-best-new-recipe rule.

## Canonicality and CI invariants

CI adds the following invariants:

1. `recipes/evidence/process-evidence.json` is canonical and schema-valid.
2. Every generated expansion recipe maps to exactly one selected R2/R3 evidence record.
3. No R1 or rejected candidate maps to a generated recipe.
4. No newly generated target reduced formula appears more than once.
5. No newly generated target duplicates a material that was already recipe-backed before expansion.
6. Every generated recipe source reference is present in its selected evidence record.
7. Expansion rebuild from frozen evidence is byte-identical to checked-in generated recipe files.
8. `recipes/compounds/catalog.json` is byte-identical to `tools/build_compound_catalog.py` output after expansion.
9. `materials/catalog.json` remains byte-identical to its frozen-source rebuild.
10. All generated recipes validate and compile under `ald_core`.
11. Full repository pytest remains green.
12. Existing HLS and Product MP4 acceptance workflows remain green.

The verification sequence is:

```text
recipe evidence audit
→ deterministic recipe expansion --check
→ compound catalog --check
→ material catalog --check
→ generated recipe validation/compile tests
→ full pytest suite
→ HLS integration acceptance
→ Product MP4 acceptance
```

## Stopping condition

There is deliberately no round-number target such as 500, 1,000, or 8,000 executable recipes.

The expansion is complete for a frozen source refresh when the pipeline has:

1. examined every material not already recipe-backed;
2. exhausted AtomicLimits candidates;
3. run fallback scholarly discovery over all remaining identities;
4. normalized and deduplicated every candidate chemistry;
5. selected every R2/R3 material with complete explicit chemistry;
6. recorded deterministic rejection reasons for everything else;
7. generated one best recipe for each newly supported material;
8. passed every canonicality and repository verification gate.

The resulting recipe count is therefore the maximum distinct-material coverage justified by that evidence snapshot, not a padded file-count objective.

## User-facing reporting

The expansion adds or extends reporting so users can see:

```text
existing recipe-backed materials
new distinct materials added
thermal ALD additions
plasma ALD additions
MLD/hybrid additions
R3 selected count
R2 selected count
rejections by reason
final executable recipe count
remaining identity-only materials
```

The report must preserve the distinction between `identity-only` material coverage and `executable-recipe` process evidence.

## Non-goals

This project does not:

- fabricate recipe chemistry for all 8,000 materials;
- infer process chemistry from composition similarity;
- reproduce literature process windows or operating conditions;
- provide hardware-control instructions;
- remove historical recipe variants;
- claim physical-process qualification, reproducibility, safety, or manufacturability;
- turn compatibility `UNKNOWN` into evidence solely because a material identity or recipe exists.
