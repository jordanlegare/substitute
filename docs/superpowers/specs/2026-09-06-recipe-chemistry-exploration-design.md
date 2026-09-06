# Recipe Chemistry Exploration Design

## Status

Approved extension to `2026-09-06-recipe-evidence-expansion-design.md`. The user delegated the remaining product decisions so the repository is usable for chemistry exploration without requiring knowledge of the evidence-ledger or recipe-file layout.

## Goal

Make every existing and newly onboarded recipe chemistry easy to discover from `ald-master` while preserving the separation between material identity, literature-backed chemistry evidence, and synthetic simulator execution.

## Product decision: one chemistry exploration namespace

Add a top-level `ald-master chemistry` namespace. It is the canonical read-only user surface for recipe chemistry and process provenance.

`materials` remains the identity-catalog surface. Existing `list` / `run` and interactive recipe workflow remain the execution surface. `chemistry` sits between them and answers: what chemistry is known, why is it recipe-backed, and where did that evidence come from?

Commands:

```text
ald-master chemistry search TEXT [--limit N] [--json]
ald-master chemistry show MATERIAL_OR_RECIPE [--json]
ald-master chemistry list [filters] [--limit N] [--json]
ald-master chemistry sources MATERIAL_OR_RECIPE [--json]
ald-master chemistry report [--json]
```

## Search behavior

`chemistry search` searches normalized, case-insensitive text across:

- target material name and formula;
- recipe ID;
- precursor/co-reactant names and formulas;
- precursor/co-reactant roles;
- chemistry family;
- process family;
- evidence grade;
- DOI and other stable source identifiers.

Results are deterministic and recipe-level. If one target has historical chemistry variants, each variant is visible as a separate result. Expansion-generated materials have at most one new recipe by design.

Default result ordering:

1. exact target formula;
2. exact target/material name;
3. exact precursor formula/name;
4. substring/alias/source matches;
5. evidence grade (`R3` before `R2`, then historical recipes without expansion grading);
6. target reduced formula;
7. recipe ID.

## `chemistry show`

The argument may be a recipe ID, target formula, target name, or material ID.

If it resolves uniquely, show one chemistry record. If a material has multiple preserved historical recipe variants, show all variants rather than silently choosing one.

Human-readable output includes only non-operational information:

```text
target material / formula
recipe id / path
status: historical | expansion-selected
process family
chemistry family
precursors and co-reactants: name, formula, role
evidence grade where applicable
source references
material-catalog linkage
simulation-only notice
```

Do not print synthetic simulator dose, purge, pressure, temperature, timing, hardware, or limit fields from recipe JSON.

## `chemistry list`

Supported filters:

```text
--process-family thermal-ald|plasma-ald|mld|hybrid
--chemistry-family TEXT
--element SYMBOL
--precursor TEXT
--evidence R2|R3|historical
--origin historical|expansion
--limit N
--json
```

Filters compose with logical AND. Ordering is deterministic by target reduced formula then recipe ID.

## `chemistry sources`

This command provides the shortest path from chemistry to provenance. It prints the selected recipe/chemistry and its DOI or stable publication identifiers, evidence grade, discovery source, and corroborating direct-publication identifiers where present.

It never fetches the network. It reads only checked-in evidence and recipe metadata.

## `chemistry report`

Report:

- total executable recipes;
- unique recipe-backed target materials;
- historical recipe count;
- expansion-generated recipe count;
- process-family counts;
- evidence-grade counts;
- unique precursor/co-reactant identities;
- unique publication identifiers;
- recipe-backed share of the 8,000 material identities;
- remaining identity-only material count.

## Data architecture

Create `ald_chemistry.py` as a focused read-only projection layer over:

- `recipes/compounds/catalog.json`;
- `recipes/evidence/process-evidence.json` when present;
- `materials/catalog.json` for material identity linkage.

The module must not parse simulator instructions except where needed to validate consistency with catalog precursor metadata. It does not execute recipes and does not access the network.

Recommended public interfaces:

```python
load_chemistry_catalog(recipe_catalog_path, evidence_path=None, material_catalog_path=None) -> list[dict[str, object]]
search_chemistries(entries, text, *, limit=20) -> list[dict[str, object]]
resolve_chemistries(entries, query) -> list[dict[str, object]]
filter_chemistries(entries, *, process_family=None, chemistry_family=None, element=None, precursor=None, evidence=None, origin=None, limit=50) -> list[dict[str, object]]
chemistry_sources(entries, query) -> list[dict[str, object]]
chemistry_report(entries, material_count=8000) -> dict[str, object]
```

## Evidence linkage

Expansion-generated recipes must have a stable evidence-record identifier in both the selected evidence record and generated recipe metadata. The chemistry projection uses that identifier instead of fuzzy matching.

Historical recipes remain valid without a new evidence-record ID. Their `metadata.source_references` are exposed as provenance with `origin=historical` and `evidence=historical` unless an exact audited evidence linkage is added later.

No historical recipe is retroactively upgraded to `R2`/`R3` merely because its DOI appears in the new evidence ledger.

## Material browsing integration

`ald-master materials show X` continues to show identity metadata. When recipe links exist, human-readable output additionally prints a one-line hint:

```text
chemistry: N recipe-backed chemistry variant(s); use `ald-master chemistry show <formula>`
```

JSON output remains structured and backward compatible; additional chemistry-summary fields may be additive only.

## Interactive UX

Add `Explore recipe chemistries` to the interactive `ald-master` top menu before compatibility operations.

Flow:

```text
Explore recipe chemistries
→ search target / precursor / DOI (blank = browse)
→ select chemistry
→ view non-operational chemistry + provenance
→ optional next action: Run recipe workflow | Back
```

The run action delegates to the existing recipe workflow using the selected recipe path. The chemistry screen itself never exposes or edits simulator parameters.

## Global path overrides

Add global inputs:

```text
--recipe-evidence PATH
```

Existing `--catalog` remains the compound recipe catalog and `--materials-catalog` remains the identity catalog. There is no second recipe-catalog flag.

## Failure behavior

- unknown chemistry query: exit 2 with a concise error;
- empty search/list result: exit 1;
- malformed evidence linkage: exit 2;
- missing optional evidence ledger: historical chemistry browsing still works; expansion-specific evidence fields are unavailable;
- generated expansion recipe with missing selected evidence record: audit/build failure, never silently downgraded.

## Safety boundary

Chemistry exploration is bibliographic/process-identity exploration for an offline simulator. It must not present literature or synthetic operating conditions, chemical-handling instructions, hardware-control values, or fabrication readiness claims.

## Documentation

README and `docs/material-catalog.md` will show a simple three-layer workflow:

```text
ald-master materials ...   # what materials are known
ald-master chemistry ...   # what literature-backed recipe chemistry is known
ald-master run ...         # execute the synthetic simulator workflow
```

Examples should lead with `chemistry search`, `chemistry show`, and `chemistry sources`, because those are the fastest paths for a user exploring the newly onboarded recipes.
