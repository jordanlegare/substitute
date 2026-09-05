# Multi-Precursor ALD/MLD Recipe Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backward-compatible, deterministic 2–6 precursor deposition-cycle simulator and ship a curated 100+ recipe ALD/MLD chemistry catalog using real precursor identities with synthetic, non-operational execution values.

**Architecture:** Preserve the legacy `ALD_CYCLE` and `site-binomial/1` path byte-for-byte. Add `DEPOSITION_CYCLE` plus a focused `site-sequential/1` surface-model module, integrate it into the existing parser/controller/report/media trust chain, then add a data-first chemistry catalog under `recipes/compounds/` with machine-checked metadata, source references, precursor-count coverage, deterministic simulation, and media round-trip acceptance.

**Tech Stack:** Python 3.10+, NumPy, pytest, existing HLS/fMP4/FFmpeg stack, existing ALD1 SHA-256 packet chain, JSON recipe files.

**Spec:** `docs/superpowers/specs/2026-09-05-multi-precursor-recipe-catalog-design.md`

## Global Constraints

- Existing `ALD_CYCLE`, legacy precursor schema, `site-binomial/1`, packet bytes, and legacy output behavior must remain compatible.
- New recipes declare exactly 2–6 unique precursor chemicals using contiguous keys `A` through `F`.
- Every new precursor object contains exact keys `name`, `formula`, and `role`, each a non-empty string.
- `DEPOSITION_CYCLE` uses 2–12 ordered exposure steps; every declared precursor appears at least once; repeated precursor references are allowed.
- New recipes use `metadata.recipe_schema == "multi-precursor/1"` and `surface.model_version == "site-sequential/1"`.
- Real chemical identities and formulas are allowed and required in the catalog; literature process windows, equipment setpoints, chemical handling instructions, and calibrated physical parameters are excluded.
- Executable `dose`, purge timing, kinetic coefficients, growth scaling, temperature, pressure, and other controller values in catalog recipes are synthetic simulator inputs and must not be copied from literature process conditions.
- Canonical packet hard ceiling remains 800 bytes.
- Packet hashing remains `SHA256(b"ALD1" + previous_digest + canonical_packet_bytes)`.
- Direct simulation and verified HLS/Product-MP4 simulation must remain byte-equivalent for the same recipe and seed.
- First catalog milestone contains at least 100 unique recipes; implementation target is 120+ curated entries when chemistry/source quality supports them.
- First milestone coverage floors: 30 oxides, 10 nitrides, 10 chalcogenides, 10 metal/carbide/other-inorganic, 15 ternary/multicomponent/nanolaminate, 15 MLD/hybrid/research.
- Precursor-count floors: at least 15 recipes with 3 unique precursors, 8 with 4, 4 with 5, and 4 with exactly 6.
- `established` and `research-stage` entries require a credible public bibliographic basis for the target/precursor pairing; `conceptual-multicomponent-surrogate` entries must never be presented as validated physical synthesis routes.

## File Structure

### New runtime module

- `ald_sequential_surface.py` — owns `site-sequential/1` configuration, site-state chain, generalized residual inventories, deterministic RNG domain separation, event samples, and snapshots. It must not import CLI/media modules.

### Existing runtime integration points

- `ald_core.py` — owns recipe-schema dispatch, precursor validation, `DEPOSITION_CYCLE` packet validation, controller state transitions, model dispatch, execution, integrity checks, and report publication.
- `ald_hardened_core.py` — re-export new public sequential types only if callers need them; do not duplicate implementation.
- `ald_product_scene.py` — binds multi-precursor sequence metadata into surrogate product scenes/product JSON.
- `ald_product_svg.py` — renders precursor-sequence summaries without exposing process-window values.
- `ald_product_render.py` — renders generalized named-precursor sequence/status frames; remove the hard-coded "Generic A/B chemistry only" wording on multi-precursor scenes while preserving Majorana compatibility backend behavior.
- `pyproject.toml` — package `ald_sequential_surface`.

### New tests

- `tests/test_multi_precursor_schema.py` — schema, packet normalization, canonical hashing, legacy golden root.
- `tests/test_sequential_surface.py` — generalized stochastic state-chain and residual model.
- `tests/test_multi_precursor_controller.py` — controller execution, fail-closed behavior, reports, determinism.
- `tests/test_multi_precursor_media.py` — HLS/Product-MP4 compile/verify/simulate equivalence.
- `tests/test_compound_catalog.py` — catalog/index/source/precursor/count and full deterministic simulation acceptance.

### Catalog and tooling

- `recipes/compounds/README.md` — human guide and safety/status semantics.
- `recipes/compounds/catalog.json` — deterministic machine-readable index.
- `recipes/compounds/{oxides,nitrides,chalcogenides,metals,carbides_and_other_inorganics,ternary_and_multicomponent,nanolaminates_and_supercycles,molecular_layer_deposition,research}/**/*.json` — curated recipes.
- `tools/build_compound_catalog.py` — deterministic index builder/checker; reads recipes, validates them through `ald_core`, emits canonical `catalog.json`, and has a `--check` mode.
- `docs/recipe-authoring.md` — documents both legacy and multi-precursor schema/opcodes.
- `recipes/README.md` — points to the compound catalog.
- `.github/workflows/core-hardening.yml`, `.github/workflows/hls-integration.yml`, `.github/workflows/product-mp4.yml` — run new catalog and media acceptance gates.

---

### Task 1: Lock legacy behavior and define multi-precursor test fixtures

**Files:**
- Create: `tests/test_multi_precursor_schema.py`
- Read/verify: `recipes/generic_al2o3.json`
- Modify later tasks only: `ald_core.py`

**Interfaces:**
- Consumes: existing `load_recipe(path) -> Mapping`, `validate_recipe(raw) -> Recipe`, `compile_recipe(recipe) -> CompiledRecipe`.
- Produces: a local `multi_recipe()` fixture builder used by schema tests and a hard golden root assertion for the existing generic Al2O3 recipe.

- [ ] **Step 1: Write the legacy golden-root test before changing runtime code**

```python
from pathlib import Path
import ald_core as core


def test_generic_al2o3_root_is_legacy_golden():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    compiled = core.compile_recipe(recipe)
    assert compiled.root_hash.hex() == "ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0"
```

- [ ] **Step 2: Add a reusable three-precursor raw-recipe fixture**

```python
def multi_recipe():
    return {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": "multi-fixture-001",
        "metadata": {
            "recipe_schema": "multi-precursor/1",
            "target_material": "fixture-film",
            "target_formula": "fixture",
            "chemistry_family": "test",
            "chemistry_status": "research-stage",
            "product_family": "test film",
            "physical_fabrication_mapping": False,
            "simulation_notice": "Synthetic execution values; chemistry identity only.",
            "source_references": [{"type": "publication", "identifier": "fixture-source"}],
        },
        "precursors": {
            "A": {"name": "water", "formula": "H2O", "role": "co-reactant"},
            "B": {"name": "ammonia", "formula": "NH3", "role": "co-reactant"},
            "C": {"name": "hydrogen sulfide", "formula": "H2S", "role": "chalcogen source"},
        },
        "initial_conditions": {"temperature_c": 25.0, "pressure_pa": 101325.0},
        "limits": {
            "min_purge_ms": 1000,
            "max_temperature_c": 300.0,
            "max_pressure_pa": 200000.0,
            "max_cycles": 20,
            "max_runtime_ms": 1000000,
            "max_residual_fraction": 0.05,
            "max_packet_bytes": 800,
        },
        "surface": {
            "model_version": "site-sequential/1",
            "regions": 2,
            "sites_per_region": 1000,
            "transport_factors": [1.0, 0.8],
            "blocked_fraction": 0.01,
            "defect_fraction": 0.005,
            "reaction_factors": [1.4, 1.2, 1.0],
            "growth_nm_per_completion_fraction": 0.1,
            "purge_half_life_ms": 800,
            "max_event_samples": 8,
        },
        "instructions": [
            {"opcode": "CONFIGURE", "arguments": {}},
            {"opcode": "SET_TEMPERATURE", "arguments": {"target_c": 100.0, "ramp_c_per_min": 20.0, "tolerance_c": 1.0}},
            {"opcode": "EVACUATE", "arguments": {"target_pa": 100.0, "timeout_ms": 100000}},
            {"opcode": "STABILIZE", "arguments": {"duration_ms": 1000}},
            {"opcode": "DEPOSITION_CYCLE", "arguments": {
                "exposures": [
                    {"precursor": "A", "dose": 0.5, "purge_ms": 2000},
                    {"precursor": "B", "dose": 0.4, "purge_ms": 2000},
                    {"precursor": "C", "dose": 0.3, "purge_ms": 2000}
                ],
                "repeat": 2
            }},
            {"opcode": "MEASURE", "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]}},
            {"opcode": "SHUTDOWN", "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0}},
        ],
    }
```

- [ ] **Step 3: Add RED tests for new schema requirements**

Test exact contiguous precursor keys, 2–6 count, exact `name/formula/role`, every precursor used, 2–12 exposures, repeated precursor allowed, undeclared precursor rejected, unused declared precursor rejected, below-minimum purge rejected, non-finite dose rejected, and packet >800 bytes rejected.

- [ ] **Step 4: Run the focused tests and confirm only new-feature tests fail**

Run: `python -m pytest tests/test_multi_precursor_schema.py -q`

Expected: golden legacy root passes; multi-precursor tests fail because `DEPOSITION_CYCLE` / extended precursor schema are not implemented.

- [ ] **Step 5: Commit RED tests**

```bash
git add tests/test_multi_precursor_schema.py
git commit -m "test: specify multi-precursor recipe schema"
```

---

### Task 2: Extend recipe and packet validation without changing legacy normalization

**Files:**
- Modify: `ald_core.py`
- Test: `tests/test_multi_precursor_schema.py`

**Interfaces:**
- Produces: `_validate_precursors(metadata, raw)`, `_validate_deposition_cycle_arguments(arguments, limits, precursors)`, and `Packet` support for opcode `DEPOSITION_CYCLE`.
- Legacy: exact `ALD_CYCLE` normalized shape and canonical bytes remain unchanged.

- [ ] **Step 1: Add schema-dispatch helpers**

Implement constants and helpers conceptually equivalent to:

```python
_PRECURSOR_IDS = ("A", "B", "C", "D", "E", "F")
_MULTI_SCHEMA = "multi-precursor/1"


def _recipe_schema(metadata):
    value = metadata.get("recipe_schema")
    return value if value == _MULTI_SCHEMA else None


def _expected_precursor_prefix(count: int) -> tuple[str, ...]:
    return _PRECURSOR_IDS[:count]
```

Legacy metadata without `recipe_schema` must take the existing exact `{A:{label},B:{label}}` branch.

- [ ] **Step 2: Implement exact new precursor validation**

For multi recipes: require 2–6 keys, require `tuple(keys)` as a contiguous prefix after deterministic sort, require exact precursor object keys `name`, `formula`, `role`, and freeze normalized objects as `MappingProxyType`.

- [ ] **Step 3: Implement `DEPOSITION_CYCLE` recipe-level validation**

Normalized packet shape must be exactly:

```python
{
    "exposures": tuple(
        MappingProxyType({
            "precursor": str,
            "dose": float,
            "purge_ms": int,
        })
        for ...
    ),
    "repeat": int,
}
```

Runtime accounting is `repeat * sum(exposure["purge_ms"] for exposure in exposures)` because `dose` is dimensionless and has no operational pulse-time meaning. Count each `DEPOSITION_CYCLE.repeat` toward `max_cycles` exactly as `ALD_CYCLE.repeat` is counted.

- [ ] **Step 4: Implement direct packet validation for `DEPOSITION_CYCLE`**

`_validate_packet_arguments()` cannot consult a recipe, so it validates only exact field/type/range shape: 2–12 exposures, precursor identifier in `A`–`F`, finite non-negative float dose after normalization, positive purge, positive repeat. Recipe binding (declared/used precursors and min purge) remains in recipe validation.

- [ ] **Step 5: Extend `_is_exact_packet_arguments` for immutable trusted packets**

Require exact built-in tuple for `exposures`, exact `MappingProxyType` elements, exact string precursor IDs, exact finite floats for `dose`, exact positive ints for `purge_ms`, and exact positive int `repeat`.

- [ ] **Step 6: Run schema tests and the existing core suite**

Run:

```bash
python -m pytest tests/test_multi_precursor_schema.py tests/test_ald_media_controller.py tests/test_surface_model.py -q
```

Expected: all pass; golden legacy root remains `ba55931d...`.

- [ ] **Step 7: Commit**

```bash
git add ald_core.py tests/test_multi_precursor_schema.py
git commit -m "feat: add multi-precursor deposition packet schema"
```

---

### Task 3: Implement the isolated `site-sequential/1` surface model

**Files:**
- Create: `ald_sequential_surface.py`
- Create: `tests/test_sequential_surface.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces:
  - `SequentialSurfaceConfig`
  - `SequentialEventSample`
  - `SequentialSurfaceSnapshot`
  - `SequentialSurfaceModel`
  - `sequential_reaction_rng(...)`
- `SequentialSurfaceModel.expose_step(cycle: int, step_index: int, precursor: str, dose: float) -> ExposureResult`
- `SequentialSurfaceModel.purge(duration_ms: int) -> None`
- `SequentialSurfaceModel.snapshot() -> SequentialSurfaceSnapshot`

- [ ] **Step 1: Write RED conservation and progression tests**

Use a 3-step configuration and assert: sites are conserved; step 1 cannot move sites waiting for step 0; a complete A/B/C sequence increments completed deposition; fixed seed gives identical snapshots; different step index changes the RNG domain; repeated precursor identity at two positions does not collide.

- [ ] **Step 2: Define immutable config and snapshot types**

`SequentialSurfaceConfig` contains:

```python
model_version: str
regions: int
sites_per_region: int
transport_factors: tuple[float, ...]
blocked_fraction: float
defect_fraction: float
reaction_factors: tuple[float, ...]
growth_nm_per_completion_fraction: float
purge_half_life_ms: int
precursor_ids: tuple[str, ...]
exposure_signature: tuple[str, ...]
```

Snapshot includes per-region state-count tuples, `residuals: Mapping[str, float]`, `coverage`, `thickness_nm`, `utilization`, `defect_fraction`, and `completed_depositions`.

- [ ] **Step 3: Implement deterministic RNG domain separation**

Bind exact components with length prefixes: root hash, model version, seed, cycle, step index, precursor ID, region, and domain. Hash with SHA-256 and seed `np.random.PCG64` from the first 16 digest bytes, matching the legacy model's deterministic style.

- [ ] **Step 4: Implement the sequential transition chain**

Each region stores a tuple/list of state counts of length `N`; state `i` is eligible only at exposure position `i`. The final step returns reacted sites to state 0 and increments `completed_depositions`. Blocked and defect counts are separate and invariant.

- [ ] **Step 5: Implement one residual inventory per declared precursor**

`expose_step` adds the dose to that precursor's residual in each region; `purge` exponentially decays all precursor residuals using `purge_half_life_ms`. Provide `max_incompatible_residual(next_precursor)` returning the maximum mean residual among precursor IDs other than `next_precursor`.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_sequential_surface.py -q`

Expected: PASS.

- [ ] **Step 7: Package and commit**

Add `"ald_sequential_surface"` to `pyproject.toml` `py-modules`.

```bash
git add ald_sequential_surface.py tests/test_sequential_surface.py pyproject.toml
git commit -m "feat: add sequential multi-precursor surface model"
```

---

### Task 4: Integrate generalized execution into the virtual controller and reports

**Files:**
- Modify: `ald_core.py`
- Modify: `ald_hardened_core.py` only for required re-exports
- Create: `tests/test_multi_precursor_controller.py`

**Interfaces:**
- Consumes: `SequentialSurfaceModel` from Task 3 and normalized `DEPOSITION_CYCLE` packets from Task 2.
- Produces: controller execution for `site-sequential/1` and model-polymorphic `SimulationResult.surface` snapshots.

- [ ] **Step 1: Write RED end-to-end controller tests**

Tests must cover: three-precursor success; six-precursor success; repeated precursor in exposure sequence; deterministic seed-42 result; conservation; residual interlock fault; malformed reaction-factor length -> `INVALID_SURFACE_CONFIG`; changing exposure signature across two `DEPOSITION_CYCLE` instructions rejected at recipe validation; legacy generic Al2O3 reports unchanged.

- [ ] **Step 2: Add generalized controller states without replacing legacy states**

Add stable enum values `DEPOSITION_EXPOSURE` and `DEPOSITION_PURGE`. Extend transition table so `READY -> DEPOSITION_EXPOSURE -> DEPOSITION_PURGE -> (DEPOSITION_EXPOSURE | READY)`. Keep all existing A/B transition edges unchanged.

- [ ] **Step 3: Keep chamber compatibility while tracking active generalized precursor internally**

Add internal `VirtualChamber.active_precursor: str | None = None`, but do not add it to legacy `ChamberSnapshot.as_dict()`. Audit event `details` for generalized exposure/purge contains `cycle`, `step_index`, `precursor`, and real `precursor_name` from the recipe.

- [ ] **Step 4: Dispatch surface initialization by `model_version`**

`site-binomial/1` continues through existing `SurfaceModel`. `site-sequential/1` constructs `SequentialSurfaceConfig` from recipe surface plus the one recipe-wide exposure signature and declared precursor IDs.

- [ ] **Step 5: Implement `_execute_deposition_cycles`**

For each repeat and each exposure position: assert safe, set `active_precursor`, transition to exposure, call `expose_step`, clear active precursor, open purge, transition to purge, advance `purge_ms`, call generalized purge, close purge. After final step return to `READY` and append the existing generic `CycleMetric` fields from the generalized snapshot.

- [ ] **Step 6: Generalize residual interlock dispatch**

Legacy `incompatible_residual("A"|"B")` remains byte/behavior compatible. Sequential model calls `max_incompatible_residual(next_precursor)` and compares it with `max_residual_fraction`.

- [ ] **Step 7: Generalize report serialization only when model is sequential**

`surface-final.json` for `site-sequential/1` includes:

```json
{
  "model_version": "site-sequential/1",
  "states_by_region": [...],
  "residuals_by_region": [...],
  "coverage": 0.0,
  "thickness_nm": 0.0,
  "utilization": 0.0,
  "defect_fraction": 0.0,
  "completed_depositions": 0,
  "exposure_signature": ["A", "B", "C"]
}
```

Do not add keys to legacy `site-binomial/1` output. `cycles.csv` keeps its existing columns so media/direct comparison remains simple.

- [ ] **Step 8: Run focused and legacy tests**

```bash
python -m pytest tests/test_multi_precursor_controller.py tests/test_multi_precursor_schema.py tests/test_sequential_surface.py tests/test_ald_media_controller.py -q
```

- [ ] **Step 9: Commit**

```bash
git add ald_core.py ald_hardened_core.py tests/test_multi_precursor_controller.py
git commit -m "feat: execute multi-precursor deposition cycles"
```

---

### Task 5: Extend trusted HLS/Product-MP4 round trips and surrogate visuals

**Files:**
- Modify: `ald_product_scene.py`
- Modify: `ald_product_svg.py`
- Modify: `ald_product_render.py`
- Test: `tests/test_multi_precursor_media.py`
- Test existing: `tests/test_hls_integration.py`, `tests/test_product_cli.py`, `tests/test_product_verification.py`

**Interfaces:**
- Consumes: canonical `DEPOSITION_CYCLE` packet support and generalized simulation from Tasks 2–4.
- Produces: HLS/Product-MP4 compile -> verify -> simulate equivalence for multi-precursor recipes.

- [ ] **Step 1: Write RED media acceptance around one 3-precursor fixture file**

Check both modes:

```bash
ald-media-controller compile recipes/compounds/research/acceptance_three_precursor.json --output build/multi-hls
ald-media-controller verify build/multi-hls/stream.m3u8
ald-media-controller simulate-media build/multi-hls/stream.m3u8 --seed 42 --output build/multi-hls-sim

ald-media-controller compile-product recipes/compounds/research/acceptance_three_precursor.json --seed 42 --output build/multi-product
ald-media-controller verify-product build/multi-product/bundle.json
ald-media-controller simulate-product build/multi-product/bundle.json --seed 42 --output build/multi-product-sim
```

Compare `cycles.csv`, `surface-final.json`, and `audit.jsonl` against direct simulation.

- [ ] **Step 2: Ensure media codecs need no format fork**

Do not create a new media record version merely for the new opcode. Existing canonical packet bytes remain authoritative; `Packet` decoding in core supplies opcode validation. Add tests proving modified exposure order/dose/precursor causes integrity mismatch exactly as any other canonical packet change.

- [ ] **Step 3: Add multi-precursor scene metadata**

For surrogate scenes, bind `recipe_schema`, target material, precursor sequence labels/names, and `physical_fabrication_mapping=false`. Product JSON must hash-bind these values through the existing scene/product digest path.

- [ ] **Step 4: Update surrogate SVG/raster wording**

For multi-precursor recipes, show "Named precursor simulation sequence" plus identifiers/names and exposure step order. Do not display temperature, pressure, purge time, dose, kinetic coefficients, or literature process windows in product pixels. Legacy surrogate A/B wording remains for old product recipes.

- [ ] **Step 5: Run media tests with FFmpeg**

```bash
python -m pytest tests/test_multi_precursor_media.py tests/test_hls_integration.py tests/test_product_cli.py tests/test_product_verification.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ald_product_scene.py ald_product_svg.py ald_product_render.py tests/test_multi_precursor_media.py
git commit -m "feat: transport multi-precursor recipes through media"
```

---

### Task 6: Document the schema and add one maintained six-precursor acceptance recipe

**Files:**
- Modify: `docs/recipe-authoring.md`
- Modify: `recipes/README.md`
- Create: `recipes/compounds/README.md`
- Create: `recipes/compounds/research/acceptance_six_precursor_surrogate.json`
- Test: `tests/test_multi_precursor_schema.py`

**Interfaces:**
- Produces: a checked-in six-precursor executable example that exercises the maximum precursor count without claiming a validated physical synthesis route.

- [ ] **Step 1: Add authoring documentation**

Document legacy vs `multi-precursor/1`, exact precursor schema, `DEPOSITION_CYCLE`, 2–12 exposures, synthetic `dose`, sequential model fields, real-chemical identity policy, and status taxonomy.

- [ ] **Step 2: Add a six-unique-precursor conceptual multicomponent acceptance recipe**

Use six real chemical identities and mark `chemistry_status: "conceptual-multicomponent-surrogate"`. The target must be a clearly named multicomponent film/network surrogate; source references may document the constituent chemistry families but must not claim the exact six-source sequence is a published process.

- [ ] **Step 3: Add acceptance assertions**

Assert exact precursor keys `A`–`F`, each `name/formula/role`, all six used in the exposure signature, validation/compile success, seed-42 controller success, and packet <=800 bytes.

- [ ] **Step 4: Run docs/example acceptance**

```bash
ald-media-controller validate recipes/compounds/research/acceptance_six_precursor_surrogate.json
ald-media-controller simulate recipes/compounds/research/acceptance_six_precursor_surrogate.json --seed 42 --output build/six-precursor-acceptance
python -m pytest tests/test_multi_precursor_schema.py -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/recipe-authoring.md recipes/README.md recipes/compounds/README.md recipes/compounds/research/acceptance_six_precursor_surrogate.json tests/test_multi_precursor_schema.py
git commit -m "docs: add multi-precursor authoring contract"
```

---

### Task 7: Add deterministic catalog indexing and repository-level chemistry QA

**Files:**
- Create: `tools/build_compound_catalog.py`
- Create: `tests/test_compound_catalog.py`
- Create: `recipes/compounds/catalog.json`

**Interfaces:**
- `build_compound_catalog(root: Path) -> dict[str, object]`
- CLI: `python tools/build_compound_catalog.py [--check]`
- Index entries contain: path, recipe_id, target_material, target_formula, chemistry_family, chemistry_status, precursor_count, precursor names/formulas/roles, source reference identifiers.

- [ ] **Step 1: Write RED index/coverage tests against an initially incomplete catalog**

Require canonical sorted entries, unique recipe IDs, path existence, no duplicate target+precursor-signature route, exact status enum, `physical_fabrication_mapping is False`, real precursor metadata fields, source references for established/research entries, and category/precursor-count floors from Global Constraints.

- [ ] **Step 2: Implement deterministic discovery**

Walk only JSON files under the chemistry-category directories; exclude `catalog.json`; load+validate every recipe through `ald_core`; derive index fields from normalized recipe metadata/precursors; sort by repository-relative path.

- [ ] **Step 3: Implement `--check`**

Canonicalize the derived index with sorted keys/compact separators/LF and byte-compare with checked-in `recipes/compounds/catalog.json`. Exit nonzero on drift.

- [ ] **Step 4: Keep source validation semantic but non-operational**

`tests/test_compound_catalog.py` requires `source_references` objects with only bibliographic/public identifiers defined by the spec. It must reject recipe metadata fields named like `process_temperature`, `pulse_time`, `flow_sccm`, `process_pressure`, `growth_window`, `dose_time`, or `handling_notes`.

- [ ] **Step 5: Commit tooling/test harness before bulk data**

```bash
git add tools/build_compound_catalog.py tests/test_compound_catalog.py recipes/compounds/catalog.json
git commit -m "test: add compound catalog integrity checks"
```

The coverage test is expected to remain RED until Tasks 8–11 populate the catalog.

---

### Task 8: Curate oxide and nitride recipes

**Files:**
- Create: `recipes/compounds/oxides/*.json` (target at least 36)
- Create: `recipes/compounds/nitrides/*.json` (target at least 12)
- Update: `recipes/compounds/catalog.json`
- Test: `tests/test_compound_catalog.py`

**Interfaces:**
- Each recipe is directly executable with `DEPOSITION_CYCLE` and `site-sequential/1`.

- [ ] **Step 1: Build the oxide source matrix**

Curate chemically defensible routes spanning at least these target families where public sources support them: Al, Hf, Zr, Ti, Zn, Si, Ta, Nb, V, W, Mo, Sn, In, Ga, Y, La, Ce, Mg, Ca, Sr, Ba, Fe, Co, Ni, Cu, Mn, Cr, Sc, Er, Gd, Dy, Lu, Bi, Ru, and Ir oxides. Multiple routes for the same target are allowed only when precursor chemistry is materially different and each route has its own source basis.

- [ ] **Step 2: Build the nitride source matrix**

Cover at least AlN, TiN, TaN, HfN, ZrN, VN, NbN, WN, MoN, SiNx, BN, and GaN where the target/precursor pairing is publicly documented. Mark less mature routes `research-stage`.

- [ ] **Step 3: For each entry, record real precursor identities only from credible public sources**

Store chemical `name`, `formula`, `role`, chemistry status, and source identifier. Do not copy source temperature, pressure, pulse, flow, or purge values. Assign synthetic simulator values from a small fixed internal profile set (for example low/medium/high dimensionless doses and standard synthetic purge constants), independent of literature conditions.

- [ ] **Step 4: Validate every file and run seed-42 simulation**

Use a loop in `tests/test_compound_catalog.py` so failures identify the exact path. Assert no controller fault and deterministic identical second run.

- [ ] **Step 5: Rebuild index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/oxides recipes/compounds/nitrides recipes/compounds/catalog.json
git commit -m "feat: add oxide and nitride recipe catalog"
```

---

### Task 9: Curate chalcogenide, metal, carbide, and other inorganic recipes

**Files:**
- Create: `recipes/compounds/chalcogenides/*.json` (target at least 16)
- Create: `recipes/compounds/metals/*.json` (target at least 10)
- Create: `recipes/compounds/carbides_and_other_inorganics/*.json` (target at least 8)
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate chalcogenide targets**

Cover representative sulfide/selenide families such as ZnS, CdS, PbS, SnS/SnS2, In2S3, TiS2, MoS2, WS2, Cu sulfides, ZnSe, CdSe, SnSe, MoSe2, and WSe2 when credible precursor pairings are publicly documented.

- [ ] **Step 2: Curate elemental metal targets**

Cover representative ALD metal routes such as Pt, Ru, Ir, Pd, Rh, Co, Ni, Cu, W, and Mo where public precursor/reductant chemistry is documented; accurately mark research-stage routes.

- [ ] **Step 3: Curate carbides/other inorganic films**

Include documented carbide, boride, phosphate, fluoride, or related ALD/MLD inorganic film families where chemistry identity is credible. Do not force category count with speculative routes; use research-stage only when a real source exists.

- [ ] **Step 4: Validate, simulate seed 42, rebuild index, commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/chalcogenides recipes/compounds/metals recipes/compounds/carbides_and_other_inorganics recipes/compounds/catalog.json
git commit -m "feat: add chalcogenide metal and inorganic recipes"
```

---

### Task 10: Curate ternary, multicomponent, nanolaminate, and 3–6 precursor recipes

**Files:**
- Create: `recipes/compounds/ternary_and_multicomponent/*.json` (target at least 16)
- Create: `recipes/compounds/nanolaminates_and_supercycles/*.json` (target at least 16)
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate literature-backed multicomponent/supercycle systems**

Prioritize meaningful systems such as Hf-Al-O, Hf-Si-O, Zr-Al-O, Al-Ti-O, Sr-Ti-O, Ba-Ti-O, La-Al-O, Li-Al-O, and published battery/dielectric multicomponent ALD families. Represent supercycles as ordered `DEPOSITION_CYCLE` exposures only when a single stable exposure signature can model the intended simulator cycle.

- [ ] **Step 2: Add nanolaminate/supercycle surrogates with accurate status labels**

For compositions that are simulator combinations of individually grounded chemistries rather than a directly published exact sequence, use `conceptual-multicomponent-surrogate` and cite only constituent chemistry sources.

- [ ] **Step 3: Satisfy precursor-count floors without filler chemicals**

Across Tasks 8–10, ensure at least 15 three-precursor and 8 four-precursor recipes. In this task specifically add at least 4 five-precursor and 4 exactly-six-precursor recipes. Each declared chemical must participate in the exposure sequence and have a meaningful compositional/reaction role.

- [ ] **Step 4: Add tests preventing fake six-precursor padding**

For every 5/6 precursor entry, assert all unique precursor names are used, no duplicate chemical name is declared under two IDs, and `chemistry_status` is `conceptual-multicomponent-surrogate` unless the exact multi-source route has a direct credible source.

- [ ] **Step 5: Validate/simulate/index/commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/ternary_and_multicomponent recipes/compounds/nanolaminates_and_supercycles recipes/compounds/catalog.json tests/test_compound_catalog.py
git commit -m "feat: add multicomponent and six-precursor recipes"
```

---

### Task 11: Curate MLD, hybrid, and research-stage molecular-layer systems

**Files:**
- Create: `recipes/compounds/molecular_layer_deposition/*.json` (target at least 18)
- Create: `recipes/compounds/research/*.json` (additional target at least 12, excluding acceptance fixtures)
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate established/research MLD hybrid families**

Cover meaningful metal-organic molecular-layer families such as alucone, zincone, titanicone, zirconicone, hafnicone, and additional documented organic-inorganic networks using real named metal precursors and bifunctional organic co-reactants. Use the literature's film/network name; do not claim isolated molecule synthesis when the source describes a film.

- [ ] **Step 2: Add research-stage chemistries across underrepresented families**

Use credible publications/public sources to extend oxynitrides, complex oxides, 2D chalcogenides, hybrid networks, battery coatings, and other ALD/MLD research systems while preserving chemistry-status accuracy.

- [ ] **Step 3: Re-run catalog floors and target 120+ total recipes**

If credible chemistry supports more than 120 entries, continue adding non-duplicate routes. Stop adding entries when additional count would require fabricated precursor pairings, duplicate routes, or unsupported chemistry claims.

- [ ] **Step 4: Rebuild index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/molecular_layer_deposition recipes/compounds/research recipes/compounds/catalog.json
git commit -m "feat: add MLD and research recipe catalog"
```

---

### Task 12: Add CI gates and full-system verification

**Files:**
- Modify: `.github/workflows/core-hardening.yml`
- Modify: `.github/workflows/hls-integration.yml`
- Modify: `.github/workflows/product-mp4.yml`
- Modify: `recipes/compounds/README.md`
- Test: all new and existing tests

**Interfaces:**
- Produces: mandatory CI proof that catalog drift, bad chemistry metadata, multi-precursor execution regressions, legacy hash regressions, and media-equivalence regressions fail the build.

- [ ] **Step 1: Add core catalog checks**

Run in `core-hardening.yml`:

```bash
python tools/build_compound_catalog.py --check
python -m pytest -q
python -m py_compile ald_core.py ald_sequential_surface.py ald_hardened_core.py
```

- [ ] **Step 2: Add one 3-precursor HLS acceptance path**

Compile/verify/direct-simulate/media-simulate a maintained catalog recipe and byte-compare `cycles.csv`, `surface-final.json`, and `audit.jsonl`.

- [ ] **Step 3: Add one 6-precursor Product-MP4 acceptance path**

Compile-product, verify-product, direct simulate, simulate-product, and compare the same reports. Probe exactly the existing 3-stream H264/AAC/bin_data-gpmd profile; no new stream type is introduced.

- [ ] **Step 4: Run the complete local verification matrix**

```bash
python tools/build_compound_catalog.py --check
python -m pytest -q
python -m py_compile ald_core.py ald_sequential_surface.py ald_hardened_core.py ald_media_codecs.py ald_media_cli.py ald_product_scene.py ald_product_svg.py ald_product_render.py ald_product_verify.py
```

Then run the two CLI acceptance paths from Steps 2–3 with FFmpeg installed.

Expected: all tests green; generic Al2O3 root remains `ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0`; catalog floors pass; direct/media outputs match exactly.

- [ ] **Step 5: Update the catalog README with generated counts**

Document total recipe count, counts by chemistry family/status/precursor count, index regeneration command, and the explicit rule that source references support chemical identity only—not executable process conditions.

- [ ] **Step 6: Commit CI and final documentation**

```bash
git add .github/workflows/core-hardening.yml .github/workflows/hls-integration.yml .github/workflows/product-mp4.yml recipes/compounds/README.md
git commit -m "ci: verify multi-precursor catalog and media paths"
```

---

## Final Review Gate

Before merging implementation:

1. Compare legacy `recipes/generic_al2o3.json` compiled root against the hard golden value.
2. Verify all new recipe files contain 2–6 contiguous precursor IDs with real names/formulas/roles.
3. Verify no catalog entry contains copied operational process windows or handling instructions.
4. Verify established/research-stage source references actually support the target/precursor pairing.
5. Verify all 5/6 precursor recipes use every unique precursor and are not padded.
6. Verify full pytest, py_compile, catalog `--check`, HLS acceptance, Product-MP4 acceptance, signed-product regression, and legacy Majorana safety binding all pass on the exact PR head.
7. Review the PR diff for accidental modifications to legacy Majorana compatibility backends or unrelated code.
