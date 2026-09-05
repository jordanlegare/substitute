# Compatibility Evidence Graph and Candidate Ranking Engine Design

## Purpose

Add a deterministic, auditable compatibility subsystem to Substitute that evaluates every unique catalog precursor/co-reactant pair and every directed base-material interface, preserves the evidence behind each assessment, and ranks 2–6 precursor candidate sets without claiming physical fabrication validation.

The engine is an R&D/simulation decision-support layer. It does **not** determine chemical storage compatibility, safe physical mixing, gas-line compatibility, reactor safety, equipment setpoints, or production readiness. A high score means "well supported inside this evidence model for sequential ALD-style simulation research," not "safe to combine in hardware."

## Architectural choice

Use an **evidence graph + deterministic verifier + candidate-ranking engine**.

The engine has four stages:

1. Normalize catalog precursor and target-material entities.
2. Exhaustively enumerate and score precursor pairs and directed material interfaces.
3. Serialize a deterministic compatibility snapshot with provenance and coverage metrics.
4. Generate and rank 2–6 precursor candidate sets from the frozen graph using bounded beam search.

Runtime remains offline. External or manually curated evidence enters only through a versioned JSON evidence-override file. The default engine therefore never changes because a remote service changed or became unavailable.

## Inputs

### Catalog

Primary input: `recipes/compounds/catalog.json` (`ald-compound-catalog/1`).

The engine consumes these catalog fields when present:

- `recipe_id`
- `path`
- `precursor_count`
- `precursors[].id`
- `precursors[].name`
- `precursors[].formula`
- `precursors[].role`
- `category`
- `chemistry_family`
- `chemistry_status`
- `product_family`
- `target_material`
- `target_formula`
- `exposure_signature`
- `source_references`

### Model

`compatibility/model-v1.json` contains all weights, evidence-level thresholds, verdict thresholds, beam-search defaults, chemistry-status reliability values, and the role-classification keyword map.

No scoring constant is buried only in Python.

### Curated evidence

`compatibility/evidence-overrides.json` uses schema `ald-compatibility-evidence/1` and may add positive, negative, or neutral evidence to a precursor pair or material interface.

Each record contains:

- `graph`: `precursor` or `material`
- `a`: formula/name/alias for the first entity
- `b`: formula/name/alias for the second entity
- `family`: evidence-family name
- `value`: number from -1.0 through +1.0
- `reliability`: number from 0.0 through 1.0
- `source`: structured provenance object
- optional `directional`: boolean for material evidence
- optional `note`

Missing external data is never converted into negative evidence.

## Entity normalization

### Precursor entities

A precursor is keyed by normalized formula when a formula exists, otherwise normalized name.

Normalization removes insignificant whitespace and Unicode presentation differences but does not perform speculative molecular identity resolution. Catalog records that normalize to the same key are aggregated into one entity with:

- canonical name
- canonical formula
- aliases
- observed roles
- recipe IDs
- chemistry statuses
- categories/families
- source references

Stable IDs use a deterministic SHA-256-derived prefix from the normalized entity key.

### Material entities

Base material nodes are created from ordinary target materials/formulas. Composite nanolaminate/supercycle targets with slash-separated formulas (for example `HfO2/Al2O3`) are treated as **evidence relating their resolved constituent materials**, not as proof of arbitrary interfaces.

Composite targets that cannot be resolved conservatively remain standalone material entities and do not create inferred constituent edges.

Material interfaces are directional: `A -> B` and `B -> A` are separate records. When a source only demonstrates co-membership in a stack without direction, the same evidence is attached to both directions with a provenance note that direction was not established.

## Role taxonomy

The model classifies observed role text into deterministic broad classes:

- `SOURCE`
- `OXIDANT`
- `REDUCTANT`
- `CHALCOGEN_REACTANT`
- `NITROGEN_REACTANT`
- `HALOGEN_REACTANT`
- `CARBON_REACTANT`
- `OTHER_REACTANT`
- `OTHER`

The classifier is intentionally coarse. It exists to distinguish source/reactant complementarity and to prevent candidate ranking from preferring nonsensical all-source or all-reactant sets. It is not a chemical hazard classifier.

## Precursor evidence graph

For `n` unique precursor entities the engine must emit exactly:

`n * (n - 1) / 2`

unordered pair records.

Each edge records individual evidence features, raw score, evidence coverage, evidence level, verdict, recipe co-occurrence, adjacent-exposure support, and provenance.

### Evidence families and default weights

- `exact_process`: 0.25
- `direct_literature`: 0.20
- `external_thermochemistry`: 0.15
- `role_complementarity`: 0.10
- `surface_sequence`: 0.10
- `physical_property`: 0.10
- `chemistry_analogue`: 0.10

`external_thermochemistry` and `physical_property` are unavailable unless supplied by curated evidence. They remain explicit schema fields so future NIST/Materials Project/Wolfram imports can be added without changing the scoring interface.

### Catalog-derived evidence

`exact_process`
: Positive when the exact pair co-occurs in one or more catalog recipes. Reliability depends on `chemistry_status`; direct established/literature-grounded entries carry more weight than conceptual surrogates.

`direct_literature`
: Positive when a co-occurring catalog recipe has one or more `source_references`. The engine records the identifiers. A catalog citation is evidence for the catalog's claimed chemistry context; it is not interpreted as proving every physical process detail.

`surface_sequence`
: Positive when both precursor IDs can be mapped into `exposure_signature`; adjacent appearances receive stronger evidence than non-adjacent co-occurrence.

`role_complementarity`
: Available for recognized role classes. Source/reactant pairings are supportive; source/source and reactant/reactant relations are weak/neutral unless stronger catalog evidence exists.

`chemistry_analogue`
: Computed only after the exact co-occurrence graph exists. It uses deterministic neighbor overlap and role-compatible shared partners. This is analogue evidence, never direct evidence.

### Negative evidence

The default catalog contains positive/surrogate process examples, not a complete incompatibility database. Therefore the engine does **not** infer chemical incompatibility merely because a pair is absent.

A `CONFLICTING` verdict requires explicit credible negative evidence from the curated override file or a future equivalent verified source.

## Material-interface graph

For `m` base material entities the engine must emit exactly:

`m * (m - 1)`

directed interface records.

Default evidence families:

- `direct_stack`: 0.30
- `direct_literature`: 0.20
- `external_thermodynamics`: 0.20
- `shared_precursors`: 0.10
- `family_analogue`: 0.10
- `surface_interface`: 0.10

### Catalog-derived material evidence

- Slash-delimited composite target formulas/materials create `direct_stack` evidence between successfully resolved constituents.
- Source references on those composite entries create `direct_literature` evidence.
- Shared precursor sets between two material recipes create weak `shared_precursors` evidence.
- Matching chemistry/category/product families create weak `family_analogue` evidence.
- No bulk thermodynamic or interface-stability claim is generated unless curated evidence supplies it.

## Feature representation

Every evidence feature is serialized as:

```json
{
  "family": "exact_process",
  "available": true,
  "value": 1.0,
  "reliability": 0.9,
  "sources": [],
  "note": "..."
}
```

`value` is in `[-1, +1]`.

`reliability` is in `[0, 1]`.

Unavailable features do not enter either numerator or denominator.

## Pair scoring

For available evidence features:

`R = sum(weight_i * reliability_i * value_i) / sum(weight_i * reliability_i)`

`score = 50 * (R + 1)`

The score is clamped to `[0, 100]`.

Coverage is calculated independently:

`coverage = sum(weight_i for available feature i) / sum(all configured family weights)`

This prevents sparse high-valued evidence from masquerading as comprehensive validation.

### Effective score for candidate ranking

Candidate ranking uses a coverage-shrunk pair score:

`effective = 50 + (pair_score - 50) * coverage`

Thus a poorly evidenced pair trends toward neutral rather than receiving the same influence as a well-supported pair.

## Evidence levels

Evidence level is independent from numerical compatibility score.

- `E4_DIRECT`: exact catalog process/stack evidence plus direct source references at an established or literature-grounded status.
- `E3_CORROBORATED`: exact catalog co-occurrence/stack evidence plus at least one additional independent evidence family.
- `E2_ANALOGUE`: meaningful graph-neighborhood/family analogue evidence without direct pair/process evidence.
- `E1_HEURISTIC`: role/family heuristic evidence only.
- `E0_UNKNOWN`: insufficient evidence.
- `E_CONFLICT`: explicit credible negative evidence materially conflicts with compatibility.

Evidence-level ordering used for filters is:

`E0_UNKNOWN < E1_HEURISTIC < E2_ANALOGUE < E3_CORROBORATED < E4_DIRECT`, with `E_CONFLICT` treated as a hard rejection state rather than part of the positive ordering.

## Pair verdicts

Default model thresholds:

- `CONFLICTING`: evidence level `E_CONFLICT`
- `UNKNOWN`: coverage below 0.15
- `LOW_SUPPORT`: score below 45
- `UNCERTAIN`: score 45 through <60
- `PLAUSIBLE`: score 60 through <75
- `SUPPORTED`: score 75 or above

Verdicts describe model support, not laboratory safety.

## Candidate generation

A full brute-force enumeration of every 2–6 combination becomes impractical as the entity count grows. Pair verification remains exhaustive, while candidate generation uses deterministic bounded beam search.

### Beam search

Defaults live in the model:

- minimum size: 2
- maximum size: 6
- beam width: 500
- final top results: 20

The algorithm:

1. Start with one-node candidates ordered by stable entity ID.
2. Expand in stable ID order to avoid duplicate sets.
3. Reject any expansion containing an `E_CONFLICT` pair.
4. Compute the partial candidate score.
5. Keep the best `beam_width` candidates per size using deterministic tie-breaking.
6. Final candidates must contain at least one `SOURCE` and at least one recognized reactant class.
7. Apply requested size/search/evidence/novelty filters.

## Candidate score

For a candidate containing at least two precursors:

- `H`: harmonic mean of all pair effective scores
- `M`: minimum pair effective score
- `E`: mean pair coverage scaled 0–100
- `R`: role-completeness score scaled 0–100
- `K`: known catalog-set support scaled 0–100

Default formula:

`candidate_score = 0.40*H + 0.20*M + 0.15*E + 0.15*R + 0.10*K`

Known catalog support is 100 for an exact precursor set present in a catalog recipe, 60 when all candidate precursors co-occur as a subset of at least one recipe, otherwise 0.

The harmonic mean and minimum term prevent one weak relation from disappearing inside several strong ones.

### Candidate evidence level

- Exact set in an established/literature-grounded referenced recipe: `E4_DIRECT`.
- Exact/subset catalog co-occurrence with corroborating pair evidence: `E3_CORROBORATED`.
- No direct set evidence but all material pairs at least analogue-supported: `E2_ANALOGUE`.
- Any heuristic-only pair: at most `E1_HEURISTIC`.
- Any unknown pair: at most `E0_UNKNOWN` unless exact catalog set evidence directly supersedes pair sparsity.
- Any conflicting pair: candidate rejected.

## Candidate IDs

Candidate IDs are deterministic hashes over the sorted stable precursor entity IDs. They are display/audit identifiers, not database primary keys that imply persistence.

## Snapshot

`ald-master compatibility-build` writes a canonical JSON snapshot, default:

`build/compatibility/snapshot.json`

Snapshot schema: `ald-compatibility-snapshot/1`.

It contains:

- model metadata and digest
- catalog digest
- evidence-override digest
- precursor entities
- material entities
- every precursor pair
- every directed material interface
- summary counts
- verdict/evidence-level histograms

Generated snapshots are build artifacts, not committed source-of-truth data.

## CLI

New global switches:

- `--compat-model PATH` default `compatibility/model-v1.json`
- `--compat-evidence PATH` default `compatibility/evidence-overrides.json`

New commands:

### Build snapshot

```bash
ald-master compatibility-build
ald-master compatibility-build --output build/custom/snapshot.json
```

### Query precursor compatibility

```bash
ald-master compatible precursor HfCl4
ald-master compatible precursor HfCl4 H2O
ald-master compatible precursor HfCl4 --top 20 --json
```

One entity lists best-supported partners. Two entities explain their pair edge.

### Query material compatibility

```bash
ald-master compatible material HfO2
ald-master compatible material HfO2 Al2O3
```

One entity lists directional interface partners. Two entities explain the requested `A -> B` interface.

### Candidate ranking

```bash
ald-master candidates
ald-master candidates --min-size 3 --max-size 6 --top 30
ald-master candidates --search hafnium --minimum-evidence E2_ANALOGUE
ald-master candidates --novel-only
ald-master candidates --json
```

### Explain

```bash
ald-master explain precursor HfCl4 H2O
ald-master explain material HfO2 Al2O3
ald-master explain candidate HfCl4 H2O ZrCl4 O3
```

### Report

```bash
ald-master compatibility-report
ald-master compatibility-report --json
```

## Interactive mode

Interactive mode is intentionally shortened.

Top menu:

1. Recipe workflow
2. Precursor compatibility
3. Material compatibility
4. Rank precursor candidates
5. Compatibility report

Compatibility flows ask for one search/entity input, then show a result menu. Candidate ranking defaults to size 2–6, top 20, and model thresholds; advanced filtering is performed through CLI flags rather than additional interactive questions.

Recipe workflow is shortened to:

`search -> recipe -> workflow -> Run / Dry run / Advanced / Cancel`

Defaults:

- seed 42
- log level INFO
- deterministic output path
- no overwrite
- no signing key
- no signature requirement

`Advanced` exposes the existing detailed prompts. This preserves power while reducing normal interaction substantially.

Arrow-key and number-key menu behavior remains unchanged.

## Error handling

The engine fails with a clear `ValueError`/CLI exit code 2 for:

- malformed model JSON
- malformed evidence JSON
- unsupported schema versions
- duplicate contradictory model definitions
- evidence records that cannot resolve either entity
- invalid evidence values/reliability
- impossible size ranges
- unknown query entities

Unknown scientific evidence is represented in the graph and does not cause execution failure.

## Determinism

For identical catalog, model, and override bytes:

- entity IDs are identical
- pair/interface IDs are identical
- JSON snapshot bytes are identical
- ranking order is identical
- candidate IDs are identical

JSON serialization uses sorted keys and compact deterministic separators for digests and canonical artifact writing.

## Safety and scientific labeling

Every report and CLI help page must state:

- compatibility is model/evidence support for offline sequential simulation research;
- it is not a chemical mixing/safety determination;
- it is not a physical fabrication recipe;
- it does not supply temperature, pressure, flow, dosing, purge, equipment, or hazard-control instructions;
- `UNKNOWN` means insufficient evidence, not incompatibility;
- `SUPPORTED` means supported by the configured evidence model, not experimentally validated unless the evidence explicitly says so.

## Files

Create:

- `ald_compatibility.py` — normalization, graph construction, scoring, snapshot, queries, beam ranking
- `compatibility/model-v1.json` — versioned deterministic model
- `compatibility/evidence-overrides.json` — curated evidence extension point
- `tests/test_ald_compatibility.py` — engine tests
- `tests/test_ald_master_compatibility.py` — CLI/integration tests
- `docs/compatibility-engine.md` — user-facing documentation and interpretation guide

Modify:

- `ald_master.py` — new commands and shortened interactive dispatcher
- `pyproject.toml` — package `ald_compatibility`
- `README.md` — compatibility/candidate examples and safety boundary
- `tests/test_ald_master_review.py` — update interactive expectation for the intentionally shortened flow

## Testing and acceptance

Unit tests must prove:

1. Formula/name normalization is deterministic.
2. Duplicate catalog appearances collapse to one entity.
3. Every precursor pair is emitted exactly once.
4. Every directed material interface is emitted exactly once.
5. Missing evidence does not become negative evidence.
6. Catalog co-occurrence creates direct positive evidence.
7. Exposure adjacency strengthens surface-sequence evidence.
8. Slash-delimited nanolaminate targets create material stack evidence only when constituents resolve.
9. Explicit negative override evidence can create `E_CONFLICT` and `CONFLICTING`.
10. Coverage is independent from score.
11. Candidate ranking rejects conflicting pairs.
12. Candidate ranking requires source/reactant role completeness.
13. Known catalog precursor sets receive support bonus.
14. Beam ranking is deterministic.
15. Candidate size is constrained to 2–6.
16. Snapshot serialization is byte-deterministic.
17. CLI pair/material/candidate/report commands parse and render.
18. JSON CLI output is valid machine-readable JSON.
19. Short interactive routing reaches compatibility and recipe modes.
20. Existing recipe launcher workflows continue to pass.

Repository CI acceptance remains the full existing `pytest` suite plus HLS/Product MP4 workflows. The compatibility engine itself must not require FFmpeg or network access.

## Scientific basis and extension points

The model deliberately separates precursor properties, reaction/process evidence, and thermodynamic/interface evidence because ALD precursor suitability depends on volatility, thermal/chemical stability, and efficient complementary self-limited surface reactivity; thermodynamic favorability alone cannot establish ALD kinetics or process suitability.

External evidence import is intentionally pluggable. NIST Chemistry WebBook data can later populate reaction/phase-change/thermophysical features, while Materials Project-style phase-diagram data can populate material thermodynamic features. Those sources remain distinct evidence families so computed bulk thermodynamics cannot silently become direct ALD-process evidence.

The initial release is comprehensive over the repository catalog but conservative about facts that are not actually present in the catalog or curated override file.
