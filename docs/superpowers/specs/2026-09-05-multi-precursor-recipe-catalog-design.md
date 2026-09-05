# Multi-Precursor ALD/MLD Recipe Catalog Design

Date: 2026-09-05
Status: approved design, implementation pending
Repository: `jordanlegare/substitute`

## 1. Purpose

Extend Substitute from its current legacy two-precursor A/B deposition model to a backward-compatible multi-precursor simulation model that can execute ordered deposition cycles using between two and six **real, named chemical precursors**.

The extension will support a large curated recipe catalog spanning established and research-stage ALD/MLD chemistries. The catalog will identify real precursor chemical names and formulas while keeping all executable process values explicitly synthetic and simulation-only.

The project remains an offline simulator. The catalog is not a source of manufacturing instructions, equipment recipes, precursor handling procedures, or calibrated physical process windows.

## 2. Goals

1. Preserve existing `ALD_CYCLE` behavior and existing A/B recipe compatibility.
2. Add a new `DEPOSITION_CYCLE` opcode for ordered multi-precursor execution.
3. Allow each new recipe to declare exactly 2–6 unique precursor chemicals using contiguous identifiers `A` through `F`.
4. Require every precursor declaration to identify a real chemical name, molecular/empirical formula, and conceptual role.
5. Allow an ordered deposition cycle to reference a declared precursor more than once when the chemistry requires repeated co-reactant or modifier exposures.
6. Make every exposure step participate in the stochastic surface-state transition model; C–F must never be metadata-only decorations.
7. Preserve deterministic execution, canonical packet hashing, ALD1 hash-chain integrity, HLS/MP4 transport, signature verification, and direct/media simulation equivalence.
8. Add a broad curated catalog of chemically defensible target materials and molecular-layer systems, including research-stage entries.
9. Clearly distinguish established, research-stage, and conceptual multicomponent surrogate recipes.
10. Keep operational values synthetic and explicitly non-calibrated.

## 3. Non-goals

- Reproducing vendor or laboratory process windows.
- Providing real chamber pressure, substrate temperature, pulse duration, flow rate, purge duration, or precursor dose recommendations from literature.
- Providing precursor handling, storage, delivery, safety, or abatement instructions.
- Inferring undisclosed industrial fabrication recipes.
- Simulating detailed gas-phase chemistry, plasma kinetics, nucleation chemistry, transport CFD, epitaxy, or device electrical behavior.
- Claiming that an ALD/MLD film recipe synthesizes isolated discrete molecules when the literature describes a film or molecular-layer network.

## 4. Backward compatibility

### 4.1 Legacy recipes

Existing recipes continue to use:

```json
"precursors": {
  "A": {"label": "..."},
  "B": {"label": "..."}
}
```

and the existing `ALD_CYCLE` opcode.

The legacy parser, normalized packet shape, legacy `SurfaceModel`, controller state transitions, canonical packet bytes, and hash-chain outputs must remain unchanged for these recipes.

### 4.2 New recipes

New multi-precursor recipes retain top-level protocol `ALD-MEDIA/1` and identify the extended schema through metadata:

```json
"metadata": {
  "recipe_schema": "multi-precursor/1"
}
```

Old tool versions may reject new recipes because they do not recognize the new opcode. New tool versions must continue to accept and reproduce legacy behavior.

No migration of existing checked-in A/B recipes is required.

## 5. Extended precursor schema

A `multi-precursor/1` recipe declares a contiguous prefix of `A` through `F`.

Valid key sets are exactly:

- `A`, `B`
- `A`, `B`, `C`
- `A`, `B`, `C`, `D`
- `A`, `B`, `C`, `D`, `E`
- `A`, `B`, `C`, `D`, `E`, `F`

Each precursor object has exactly:

```json
{
  "name": "real chemical name",
  "formula": "chemical formula",
  "role": "conceptual chemistry role"
}
```

Requirements:

- `name`, `formula`, and `role` are non-empty UTF-8 strings.
- Chemical names represent real named reagents used or reported for the referenced chemistry.
- Formula strings are descriptive metadata and are not parsed as executable chemistry.
- A recipe may not declare unused precursors.
- Repeated use of one precursor in multiple exposure steps references the same identifier; duplicate declarations for the same chemical are not used merely to pad precursor count.
- The catalog must not add fictitious precursor chemicals to force a recipe to use six precursors.

## 6. Recipe chemistry metadata

Every new catalog recipe includes at least these metadata fields:

```json
{
  "recipe_schema": "multi-precursor/1",
  "target_material": "human-readable target",
  "target_formula": "formula or network description",
  "chemistry_family": "oxide | nitride | chalcogenide | metal | ...",
  "chemistry_status": "established | research-stage | conceptual-multicomponent-surrogate",
  "product_family": "human-readable film/product family",
  "physical_fabrication_mapping": false,
  "simulation_notice": "...",
  "source_references": [
    {
      "type": "doi | publication | public-source",
      "identifier": "bibliographic identifier only"
    }
  ]
}
```

`source_references` establish the chemical basis for the target/precursor pairing. They must not embed extracted process windows or equipment setpoints.

`chemistry_status` semantics:

- `established`: widely documented ALD/MLD chemistry or mature literature route.
- `research-stage`: published or otherwise credibly documented but less mature, specialized, or still under active research.
- `conceptual-multicomponent-surrogate`: a chemically motivated simulator composition or supercycle representation that must not be presented as a validated physical synthesis route.

## 7. New `DEPOSITION_CYCLE` opcode

### 7.1 Packet shape

The generalized opcode uses an ordered exposure array and an integer repeat count:

```json
{
  "opcode": "DEPOSITION_CYCLE",
  "arguments": {
    "exposures": [
      {
        "precursor": "A",
        "dose": 0.75,
        "purge_ms": 4000
      },
      {
        "precursor": "B",
        "dose": 0.90,
        "purge_ms": 4000
      },
      {
        "precursor": "C",
        "dose": 0.60,
        "purge_ms": 4000
      }
    ],
    "repeat": 100
  }
}
```

### 7.2 Synthetic execution parameters

The new opcode deliberately uses a dimensionless `dose` rather than operational flow/pulse pairs.

- `dose`: finite non-negative synthetic exposure scalar.
- `purge_ms`: positive synthetic simulator timing used for residual-decay and runtime accounting.
- `repeat`: positive integer bounded by recipe limits.

These values are simulator inputs only. Catalog values must not be copied from literature process conditions.

### 7.3 Validation

A `DEPOSITION_CYCLE` must satisfy all of the following:

- Recipe uses `metadata.recipe_schema == "multi-precursor/1"`.
- Recipe declares 2–6 unique precursors.
- `exposures` contains at least 2 and at most 12 steps.
- Every exposure references one declared precursor key.
- Every declared precursor appears at least once in `exposures`.
- Exposure order is preserved exactly.
- Repeated precursor references are allowed.
- `dose` is finite and non-negative.
- `purge_ms` satisfies the recipe minimum purge limit.
- Expanded repeats remain within `max_cycles`.
- Expanded synthetic runtime remains within `max_runtime_ms`.
- Canonical packet size remains within the existing 800-byte hard ceiling.

## 8. Sequential surface model

### 8.1 Model version

New recipes use:

```json
"model_version": "site-sequential/1"
```

Legacy recipes continue to use `site-binomial/1` unchanged.

### 8.2 State chain

For a cycle with `N` ordered exposure steps, each reactive site belongs to one of `N` sequential reaction states.

Initial state:

```text
ready-for-step-0
```

Exposure step `i` stochastically moves eligible sites from state `i` to state `(i + 1) mod N`.

The final exposure step returns successfully reacted sites to the ready state and increments the completed-deposition counter.

Example with six ordered steps:

```text
ready
  -> after-A
  -> after-B
  -> after-C
  -> after-D
  -> after-E
  -> completed-by-F / ready for next cycle
```

If a chemical is reused in more than one exposure position, the surface states still follow exposure position, not unique chemical identity.

### 8.3 Reaction probability

Each exposure step uses the existing stable binomial probability form:

```text
p = 1 - exp(-k_step * dose * transport_factor_region)
```

`k_step` is a synthetic, non-calibrated simulator coefficient.

### 8.4 Sequential surface configuration

`site-sequential/1` uses:

```json
{
  "model_version": "site-sequential/1",
  "regions": 4,
  "sites_per_region": 250000,
  "transport_factors": [1.0, 0.9, 0.8, 0.7],
  "blocked_fraction": 0.01,
  "defect_fraction": 0.005,
  "reaction_factors": [1.4, 1.3, 1.2],
  "growth_nm_per_completion_fraction": 0.10,
  "purge_half_life_ms": 800,
  "max_event_samples": 100
}
```

Requirements:

- `reaction_factors` length exactly equals exposure-step count.
- Values are finite and non-negative.
- `growth_nm_per_completion_fraction` is a synthetic visualization/reporting scalar, not a calibrated growth-per-cycle value.
- Existing region transport semantics remain aggregate and dimensionless.

## 9. Generalized residual model

The sequential model tracks one residual inventory per declared precursor key and per region.

For exposure of precursor `P`:

1. Increase residual inventory for `P` by the synthetic dose.
2. Apply the stochastic transition for that exposure position.
3. Apply purge decay to every precursor residual inventory during the step purge.

Residual interlock checks consider the maximum residual fraction across all declared precursor inventories.

This replaces the hard-coded A/B residual pair only for `site-sequential/1`; the legacy model remains unchanged.

## 10. Deterministic RNG and event samples

The generalized RNG domain must bind:

- compiled recipe root hash,
- model version,
- user seed,
- deposition-cycle iteration,
- exposure-step index,
- precursor identifier,
- region index,
- RNG domain (`reaction` or `sample`).

This prevents collisions between repeated chemical identities in different exposure positions and preserves deterministic results for a fixed recipe and seed.

Event samples record at least:

- cycle,
- exposure-step index,
- precursor identifier,
- region,
- source state,
- destination state,
- sample identifier.

## 11. Controller state machine

Legacy controller states remain unchanged for `ALD_CYCLE`.

The generalized path adds stable controller states:

- `DEPOSITION_EXPOSURE`
- `DEPOSITION_PURGE`

Audit records include exposure-step index and precursor identifier/name. Controller state names do not dynamically encode chemical names.

Failure remains fail-closed. Invalid precursor references, malformed sequential-state configuration, residual-limit violations, cycle/runtime limit violations, or impossible state conservation raise the existing typed error families.

## 12. Canonical packets and integrity

`DEPOSITION_CYCLE` becomes a first-class packet opcode.

Required integrity behavior:

- Canonical JSON remains sorted, compact, UTF-8, and finite-number-only.
- Packet hard limit remains 800 bytes.
- Hashing remains `SHA256(b"ALD1" + previous_digest + canonical_packet_bytes)`.
- Existing `HashedPacket` and `CompiledRecipe` structures remain usable.
- Existing recipe roots for unchanged legacy recipes must not change.
- Verification rejects a modified exposure order, precursor key, dose, purge, repeat, or opcode.

## 13. HLS and Product-MP4 integration

The media layer does not infer chemistry from pixels.

For `DEPOSITION_CYCLE` packets:

- canonical packet bytes are transported through the existing trusted media channels,
- ALDP data records continue to carry the authoritative product-MP4 packet stream,
- BFSK audio continues to witness packet sequence/digest,
- QR/HLS mode continues to carry canonical packet payloads/digests,
- signature behavior is unchanged,
- direct simulation and verified-media simulation must produce byte-identical reports for the same recipe and seed.

Product visualization may show target material, precursor sequence, conceptual reaction stages, region coverage, and completion progress. It must not infer undisclosed physical process parameters.

## 14. Recipe catalog structure

New recipes live under:

```text
recipes/compounds/
  oxides/
  nitrides/
  chalcogenides/
  metals/
  carbides_and_other_inorganics/
  ternary_and_multicomponent/
  nanolaminates_and_supercycles/
  molecular_layer_deposition/
  research/
```

A machine-readable index is maintained at:

```text
recipes/compounds/catalog.json
```

and a human-readable guide at:

```text
recipes/compounds/README.md
```

## 15. Catalog breadth requirement

The first implementation milestone must add **at least 100 unique curated recipes**. There is no upper cap; additional chemically defensible recipes should be included when they satisfy the inclusion rules.

Minimum coverage for the first milestone:

- at least 30 oxide recipes,
- at least 10 nitride recipes,
- at least 10 chalcogenide recipes,
- at least 10 metal/carbide/other-inorganic recipes,
- at least 15 ternary/multicomponent or nanolaminate/supercycle recipes,
- at least 15 MLD/hybrid/research recipes.

The same chemistry route may not be duplicated merely to increase count.

Precursor-count coverage across the catalog:

- 2-precursor recipes: unrestricted,
- at least 15 recipes using 3 unique precursors,
- at least 8 recipes using 4 unique precursors,
- at least 4 recipes using 5 unique precursors,
- at least 4 recipes using exactly 6 unique precursors.

If credible literature does not support enough genuine 5- or 6-unique-precursor routes, the implementation must use `conceptual-multicomponent-surrogate` status for clearly labeled simulator compositions rather than fabricate false literature claims.

## 16. Catalog inclusion rules

A recipe is eligible when:

1. The target material, film class, or molecular-layer network is meaningful in ALD/MLD research or practice.
2. The precursor identities are real chemicals.
3. For `established` or `research-stage`, the target/precursor pairing has a credible public bibliographic basis.
4. The recipe does not reproduce operational conditions from the source.
5. The executable sequence is represented with synthetic dose, purge, surface, and kinetic values.
6. Chemistry maturity is labeled accurately.
7. The recipe passes validation, compilation, and deterministic simulation.
8. No undeclared or unused precursor exists.

## 17. Catalog index

`catalog.json` contains one entry per recipe with:

- repository-relative path,
- recipe ID,
- target material,
- target formula/network,
- chemistry family,
- chemistry status,
- precursor count,
- ordered precursor names,
- source-reference identifiers.

The index is generated deterministically from recipe files and checked in CI for drift.

## 18. Validation and testing

### 18.1 Legacy regression

Tests must prove unchanged legacy behavior by checking existing canonical packet bytes/root hashes and direct/media execution for current fixtures.

### 18.2 Schema tests

Cover:

- valid precursor counts 2 through 6,
- rejection of 1 or 7+ precursors,
- rejection of non-contiguous keys,
- rejection of mixed legacy/extended precursor object formats,
- rejection of missing name/formula/role,
- rejection of unused declared precursors,
- repeated precursor exposure references,
- exposure-list bounds,
- malformed dose/purge/repeat values,
- packet-size enforcement.

### 18.3 Sequential surface tests

Cover:

- deterministic N-step state transitions,
- site conservation for 2–12 exposure positions,
- final-step completion counting,
- repeated chemical identifiers at multiple positions,
- independent residual inventories,
- purge decay,
- region transport variation,
- deterministic event sampling,
- seed divergence,
- failure on invalid state configuration.

### 18.4 Controller tests

Cover:

- exposure/purge state progression,
- audit records with precursor identity and step index,
- residual interlocks,
- runtime/cycle limits,
- fail-closed behavior.

### 18.5 Media tests

Cover representative 2-, 3-, 4-, 5-, and 6-precursor recipes through:

- compile,
- direct simulation,
- HLS/QR package and verify,
- Product-MP4 package and verify,
- signed Product-MP4 verification,
- direct/media byte-equivalence.

The full 100+ recipe catalog is validated, compiled, and simulated in CI without requiring MP4 generation for every recipe.

### 18.6 Catalog quality tests

CI enforces:

- at least 100 catalog entries,
- category minimums,
- precursor-count minimums,
- unique recipe IDs and paths,
- index/repository consistency,
- required chemistry metadata,
- real non-placeholder precursor names,
- `physical_fabrication_mapping == false`,
- successful compile and deterministic seed-42 simulation for every catalog recipe.

## 19. Documentation

Update:

- `docs/recipe-authoring.md` with legacy and extended schemas,
- `recipes/README.md` with catalog navigation,
- `README.md` with multi-precursor capability,
- `recipes/compounds/README.md` with chemistry-status definitions and safety/simulation boundary.

Examples must clearly state that chemical identities are real but executable conditions are synthetic.

## 20. Safety and scientific-boundary wording

Every catalog recipe must state that:

- it is simulation-only,
- real precursor names identify chemistry but do not constitute handling or process guidance,
- executable values are synthetic and non-calibrated,
- the recipe is not suitable for equipment control or physical fabrication,
- research-stage status does not imply reproducibility or industrial readiness.

No recipe should contain real operating windows copied from a paper, patent, vendor process note, or fab recipe.

## 21. Acceptance criteria

The implementation is complete when all of the following are true:

1. Existing legacy recipes produce unchanged canonical packet roots and pass all existing tests.
2. `DEPOSITION_CYCLE` accepts and executes 2–6 unique named precursors and 2–12 ordered exposure steps.
3. C–F exposures modify the generalized surface state and are not metadata-only.
4. A representative six-precursor recipe completes deterministic simulation and media round-trip verification.
5. Every new recipe names all real precursor chemicals and formulas.
6. At least 100 curated recipes are checked in and indexed.
7. Catalog category and precursor-count minimums are met.
8. Every catalog recipe validates, compiles, and simulates at seed 42.
9. Representative recipes across precursor counts pass HLS and Product-MP4 equivalence tests.
10. Existing Product-MP4 Majorana and surrogate-product behavior remains green.
11. All executable operating values in the new catalog are explicitly synthetic and non-calibrated.
12. Documentation clearly separates real chemical identity from simulated process execution.
