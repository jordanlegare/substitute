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
- Real chemical identities and formulas are required in the catalog; literature process windows, equipment setpoints, chemical handling instructions, and calibrated physical parameters are excluded.
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
- `ald_sequential_surface.py` — owns `site-sequential/1` configuration, site-state chain, generalized residual inventories, deterministic RNG domain separation, event samples, and snapshots.

### Existing runtime integration points
- `ald_core.py` — recipe-schema dispatch, precursor validation, `DEPOSITION_CYCLE` packet validation, controller state transitions, model dispatch, execution, integrity checks, and report publication.
- `ald_hardened_core.py` — re-export new public sequential types only if required by current facade behavior.
- `ald_product_scene.py` — bind multi-precursor sequence metadata into surrogate product scenes/product JSON.
- `ald_product_svg.py` — render precursor-sequence summaries without process-window values.
- `ald_product_render.py` — render generalized named-precursor sequence/status frames while preserving the Majorana compatibility backend.
- `pyproject.toml` — package `ald_sequential_surface`.

### New tests
- `tests/test_multi_precursor_schema.py`
- `tests/test_sequential_surface.py`
- `tests/test_multi_precursor_controller.py`
- `tests/test_multi_precursor_media.py`
- `tests/test_compound_catalog.py`

### Catalog and tooling
- `recipes/compounds/README.md`
- `recipes/compounds/catalog.json`
- `recipes/compounds/oxides/*.json`
- `recipes/compounds/nitrides/*.json`
- `recipes/compounds/chalcogenides/*.json`
- `recipes/compounds/metals/*.json`
- `recipes/compounds/carbides_and_other_inorganics/*.json`
- `recipes/compounds/ternary_and_multicomponent/*.json`
- `recipes/compounds/nanolaminates_and_supercycles/*.json`
- `recipes/compounds/molecular_layer_deposition/*.json`
- `recipes/compounds/research/*.json`
- `tools/build_compound_catalog.py`
- `docs/recipe-authoring.md`
- `recipes/README.md`
- `.github/workflows/core-hardening.yml`
- `.github/workflows/hls-integration.yml`
- `.github/workflows/product-mp4.yml`

---

### Task 1: Lock legacy behavior and specify the new recipe contract

**Files:**
- Create: `tests/test_multi_precursor_schema.py`
- Read: `recipes/generic_al2o3.json`

**Interfaces:**
- Consumes: `load_recipe(path)`, `validate_recipe(raw)`, `compile_recipe(recipe)`.
- Produces: a reusable raw-recipe builder and hard compatibility assertions.

- [ ] **Step 1: Add the legacy golden-root test**

```python
from copy import deepcopy
from pathlib import Path
import math
import pytest
import ald_core as core


def test_generic_al2o3_root_is_legacy_golden():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    compiled = core.compile_recipe(recipe)
    assert compiled.root_hash.hex() == "ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0"
```

- [ ] **Step 2: Add a reusable three-precursor fixture builder**

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

- [ ] **Step 3: Add parameterized RED schema tests**

```python
@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda r: r["precursors"].pop("B"), "2 to 6"),
        (lambda r: r["precursors"].update({"D": {"name": "oxygen", "formula": "O2", "role": "oxidant"}}), "contiguous"),
        (lambda r: r["precursors"]["A"].pop("formula"), "formula"),
        (lambda r: r["instructions"][4]["arguments"]["exposures"].pop(), "every declared precursor"),
        (lambda r: r["instructions"][4]["arguments"]["exposures"].append({"precursor": "F", "dose": 0.2, "purge_ms": 2000}), "declared precursor"),
        (lambda r: r["instructions"][4]["arguments"]["exposures"][0].update({"purge_ms": 999}), "min_purge_ms"),
        (lambda r: r["instructions"][4]["arguments"]["exposures"][0].update({"dose": math.inf}), "finite"),
    ],
)
def test_multi_precursor_schema_rejects_invalid_forms(mutator, message):
    raw = multi_recipe()
    mutator(raw)
    with pytest.raises(core.ALDError, match=message):
        core.validate_recipe(raw)


def test_multi_precursor_schema_allows_repeated_precursor_position():
    raw = multi_recipe()
    exposures = raw["instructions"][4]["arguments"]["exposures"]
    exposures.insert(2, {"precursor": "A", "dose": 0.2, "purge_ms": 2000})
    raw["surface"]["reaction_factors"] = [1.4, 1.2, 1.1, 1.0]
    recipe = core.validate_recipe(raw)
    assert len(recipe.instructions[4]["arguments"]["exposures"]) == 4
```

- [ ] **Step 4: Run RED tests**

Run: `python -m pytest tests/test_multi_precursor_schema.py -q`

Expected: golden legacy test passes; new multi-precursor tests fail because the schema/opcode are unsupported.

- [ ] **Step 5: Commit**

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
- Produces: `_validate_precursors(metadata, raw)`, `_validate_deposition_cycle_arguments(arguments, limits, precursors)`, and trusted-packet support for `DEPOSITION_CYCLE`.

- [ ] **Step 1: Add schema-dispatch constants and helpers**

```python
_PRECURSOR_IDS = ("A", "B", "C", "D", "E", "F")
_MULTI_SCHEMA = "multi-precursor/1"


def _is_multi_recipe(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("recipe_schema") == _MULTI_SCHEMA


def _expected_precursor_prefix(count: int) -> tuple[str, ...]:
    return _PRECURSOR_IDS[:count]
```

Legacy metadata without the exact schema tag must stay on the existing `{A:{label},B:{label}}` branch.

- [ ] **Step 2: Implement exact multi-precursor validation**

```python
def _validate_precursors(metadata: Mapping[str, Any], raw: Any):
    if not _is_multi_recipe(metadata):
        values = _require_exact_keys(raw, frozenset({"A", "B"}), "precursors")
        return MappingProxyType({
            key: MappingProxyType({
                "label": _require_string(
                    _require_exact_keys(values[key], frozenset({"label"}), f"precursors.{key}")["label"],
                    f"precursors.{key}.label",
                )
            })
            for key in ("A", "B")
        })

    values = _require_mapping(raw, "precursors")
    keys = tuple(sorted(values))
    if not 2 <= len(keys) <= 6:
        raise RecipeError("multi-precursor recipes require 2 to 6 precursors")
    if keys != _expected_precursor_prefix(len(keys)):
        raise RecipeError("multi-precursor keys must be a contiguous A-F prefix")
    normalized = {}
    for key in keys:
        item = _require_exact_keys(values[key], frozenset({"name", "formula", "role"}), f"precursors.{key}")
        normalized[key] = MappingProxyType({
            field: _require_string(item[field], f"precursors.{key}.{field}")
            for field in ("name", "formula", "role")
        })
    return MappingProxyType(normalized)
```

- [ ] **Step 3: Implement recipe-level `DEPOSITION_CYCLE` validation**

```python
def _validate_deposition_cycle_arguments(arguments, limits, precursors):
    values = _require_exact_keys(arguments, frozenset({"exposures", "repeat"}), "DEPOSITION_CYCLE arguments")
    exposures = values["exposures"]
    if not isinstance(exposures, list) or not 2 <= len(exposures) <= 12:
        raise RecipeError("DEPOSITION_CYCLE exposures must contain 2 to 12 steps")
    normalized = []
    used = set()
    for index, raw_exposure in enumerate(exposures):
        item = _require_exact_keys(raw_exposure, frozenset({"precursor", "dose", "purge_ms"}), f"exposures[{index}]")
        precursor = _require_string(item["precursor"], f"exposures[{index}].precursor")
        if precursor not in precursors:
            raise RecipeError("DEPOSITION_CYCLE references undeclared precursor")
        dose = _require_finite_number(item["dose"], f"exposures[{index}].dose")
        purge_ms = _require_integer(item["purge_ms"], f"exposures[{index}].purge_ms", minimum=1)
        if dose < 0:
            raise RecipeLimitError("DEPOSITION_CYCLE dose must be non-negative")
        if purge_ms < limits.min_purge_ms:
            raise RecipeLimitError("DEPOSITION_CYCLE purge below min_purge_ms")
        used.add(precursor)
        normalized.append(MappingProxyType({"precursor": precursor, "dose": dose, "purge_ms": purge_ms}))
    if used != set(precursors):
        raise RecipeError("DEPOSITION_CYCLE must use every declared precursor")
    repeat = _require_integer(values["repeat"], "repeat", minimum=1)
    runtime_ms = repeat * sum(item["purge_ms"] for item in normalized)
    return MappingProxyType({"exposures": tuple(normalized), "repeat": repeat}), runtime_ms
```

- [ ] **Step 4: Extend `_validate_instruction`, cycle counting, and direct packet validation**

Add a `DEPOSITION_CYCLE` branch that calls the helper above. Count `normalized["arguments"]["repeat"]` toward `max_cycles` for both `ALD_CYCLE` and `DEPOSITION_CYCLE`. In `_validate_packet_arguments`, validate exact packet field/type/range shape without recipe-dependent precursor/min-purge checks.

- [ ] **Step 5: Extend `_is_exact_packet_arguments`**

Require `type(exposures) is tuple`; every item must be exact `MappingProxyType` with keys `precursor,dose,purge_ms`; precursor exact `str` in `_PRECURSOR_IDS`; dose exact finite `float >= 0`; purge exact positive `int`; repeat exact positive `int`.

- [ ] **Step 6: Add canonical packet-size and exposure-signature tests**

```python
def test_multi_precursor_packet_round_trip_is_canonical():
    recipe = core.validate_recipe(multi_recipe())
    compiled = core.compile_recipe(recipe)
    packet = compiled.packets[4]
    assert packet.packet.opcode == "DEPOSITION_CYCLE"
    assert len(packet.canonical_bytes) <= 800
    assert core.canonical_packet_bytes(packet.packet) == packet.canonical_bytes


def test_all_deposition_cycles_require_same_exposure_signature():
    raw = multi_recipe()
    second = deepcopy(raw["instructions"][4])
    second["arguments"]["exposures"][0]["precursor"] = "B"
    second["arguments"]["exposures"][1]["precursor"] = "A"
    raw["instructions"].insert(5, second)
    with pytest.raises(core.RecipeError, match="exposure signature"):
        core.validate_recipe(raw)
```

- [ ] **Step 7: Run and commit**

```bash
python -m pytest tests/test_multi_precursor_schema.py tests/test_ald_media_controller.py tests/test_surface_model.py -q
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
- `SequentialSurfaceModel(config, root_hash, user_seed, max_event_samples=0)`
- `expose_step(cycle, step_index, precursor, dose) -> SequentialExposureResult`
- `purge(duration_ms) -> None`
- `snapshot() -> SequentialSurfaceSnapshot`
- `max_incompatible_residual(next_precursor) -> float`

- [ ] **Step 1: Write RED progression/conservation tests**

```python
from ald_sequential_surface import SequentialSurfaceConfig, SequentialSurfaceModel


def config(signature=("A", "B", "C")):
    return SequentialSurfaceConfig(
        model_version="site-sequential/1",
        regions=2,
        sites_per_region=1000,
        transport_factors=(1.0, 0.8),
        blocked_fraction=0.01,
        defect_fraction=0.005,
        reaction_factors=tuple(1.0 for _ in signature),
        growth_nm_per_completion_fraction=0.1,
        purge_half_life_ms=800,
        precursor_ids=tuple(sorted(set(signature))),
        exposure_signature=signature,
    )


def test_three_step_sequence_is_deterministic_and_conserves_sites():
    root = bytes.fromhex("11" * 32)
    first = SequentialSurfaceModel(config(), root, 42)
    second = SequentialSurfaceModel(config(), root, 42)
    for model in (first, second):
        model.expose_step(1, 0, "A", 0.5)
        model.purge(2000)
        model.expose_step(1, 1, "B", 0.4)
        model.purge(2000)
        model.expose_step(1, 2, "C", 0.3)
        model.purge(2000)
    assert first.snapshot() == second.snapshot()
    assert first.snapshot().completed_depositions > 0
    assert all(sum(region.state_counts) + region.blocked + region.defects == 1000 for region in first.snapshot().regions)
```

- [ ] **Step 2: Define concrete immutable types**

Create `SequentialSurfaceConfig`, `SequentialRegionSnapshot`, `SequentialEventSample`, `SequentialExposureResult`, and `SequentialSurfaceSnapshot` dataclasses. `SequentialSurfaceSnapshot.as_dict()` must emit exact JSON-ready keys used by Task 4.

- [ ] **Step 3: Implement deterministic RNG**

Length-prefix root hash, model version, seed, cycle, step index, precursor, region, and domain into `b"ALD-SEQUENTIAL-RNG/1"`, hash with SHA-256, then seed `np.random.PCG64(int.from_bytes(digest[:16], "big"))`.

- [ ] **Step 4: Implement sequential state transitions**

For N exposure positions, each region stores `state_counts` length N. Exposure `i` can only react sites in state `i`; non-final success moves them to state `i+1`; final-step success returns them to state 0 and increments completed depositions. Blocked/defect counts never enter the state vector.

- [ ] **Step 5: Implement residual inventories**

Track a residual float per declared precursor per region. `expose_step` increments only the selected precursor residual; `purge` decays all inventories by `exp(-ln(2)*duration_ms/purge_half_life_ms)`. `max_incompatible_residual(next_precursor)` returns the largest region-mean residual among all other precursor IDs, or 0.0 when none exist.

- [ ] **Step 6: Add repeated-precursor RNG-domain test**

```python
def test_repeated_precursor_positions_use_distinct_rng_domains():
    model = SequentialSurfaceModel(config(("A", "B", "A")), bytes.fromhex("22" * 32), 42)
    first = model._reaction_rng_material(1, 0, "A", 0, "reaction")
    third = model._reaction_rng_material(1, 2, "A", 0, "reaction")
    assert first != third
```

If the implementation keeps RNG material helper private under another exact name, expose a deterministic pure helper instead of testing NumPy internals.

- [ ] **Step 7: Run, package, commit**

```bash
python -m pytest tests/test_sequential_surface.py -q
# add "ald_sequential_surface" to pyproject.toml py-modules
git add ald_sequential_surface.py tests/test_sequential_surface.py pyproject.toml
git commit -m "feat: add sequential multi-precursor surface model"
```

---

### Task 4: Integrate generalized execution into controller and reports

**Files:**
- Modify: `ald_core.py`
- Modify: `ald_hardened_core.py` only if public facade re-export is required
- Create: `tests/test_multi_precursor_controller.py`

**Interfaces:**
- Consumes Task 2 packets and Task 3 model.
- Produces deterministic controller execution and model-specific `surface-final.json`.

- [ ] **Step 1: Write RED controller tests**

```python
def execute(raw, seed=42):
    recipe = core.validate_recipe(raw)
    return core.SimulatedALDController().execute(core.compile_recipe(recipe), seed)


def test_three_precursor_controller_completes():
    result = execute(multi_recipe())
    assert result.fault is None
    assert result.final_state is core.ControllerState.IDLE
    assert result.surface.completed_depositions > 0


def test_seed_42_is_reproducible():
    first = execute(multi_recipe(), 42)
    second = execute(multi_recipe(), 42)
    assert first.surface.as_dict() == second.surface.as_dict()
    assert first.cycles == second.cycles


def test_bad_reaction_factor_length_fails_closed():
    raw = multi_recipe()
    raw["surface"]["reaction_factors"] = [1.0, 1.0]
    result = execute(raw)
    assert result.fault.code == "INVALID_SURFACE_CONFIG"
```

Add a six-precursor success case by extending the fixture with D/E/F and six reaction factors.

- [ ] **Step 2: Add generalized controller states**

Add `DEPOSITION_EXPOSURE` and `DEPOSITION_PURGE` to `ControllerState`. Extend transitions exactly: `READY -> DEPOSITION_EXPOSURE`; `DEPOSITION_EXPOSURE -> DEPOSITION_PURGE`; `DEPOSITION_PURGE -> DEPOSITION_EXPOSURE | READY | FAULT`. Keep existing A/B edges unchanged.

- [ ] **Step 3: Add internal active-precursor tracking without changing legacy chamber JSON**

Add `VirtualChamber.active_precursor: str | None = None`; do not add it to `ChamberSnapshot.as_dict()`. Generalized audit details contain exact keys `cycle`, `step_index`, `precursor`, `precursor_name`.

- [ ] **Step 4: Dispatch surface initialization by model version**

`site-binomial/1` continues through existing `SurfaceModel`. `site-sequential/1` constructs `SequentialSurfaceConfig` from the recipe-wide exposure signature, precursor IDs, and sequential surface fields.

- [ ] **Step 5: Implement `_execute_deposition_cycles`**

```python
def _execute_deposition_cycles(self, arguments, sequence):
    if self.state is not ControllerState.READY:
        raise ControllerFault("INVALID_TRANSITION")
    exposures = arguments["exposures"]
    for _ in range(int(arguments["repeat"])):
        self._cycle_index += 1
        cycle = self._cycle_index
        for step_index, exposure in enumerate(exposures):
            precursor = exposure["precursor"]
            self.assert_precursor_safe(precursor)
            self.chamber.active_precursor = precursor
            self.transition(ControllerState.DEPOSITION_EXPOSURE, packet_sequence=sequence,
                            details=self._deposition_details(cycle, step_index, precursor))
            self._require_sequential_surface().expose_step(cycle, step_index, precursor, float(exposure["dose"]))
            self.chamber.active_precursor = None
            self.chamber.inert_purge_open = True
            self.transition(ControllerState.DEPOSITION_PURGE, packet_sequence=sequence,
                            details=self._deposition_details(cycle, step_index, precursor))
            self._advance_time(int(exposure["purge_ms"]))
            self._require_sequential_surface().purge(int(exposure["purge_ms"]))
            self.chamber.inert_purge_open = False
        self.transition(ControllerState.READY, packet_sequence=sequence, details={"cycle": cycle})
        self._append_cycle_metric(cycle)
```

- [ ] **Step 6: Dispatch residual interlocks**

Legacy model keeps current A/B residual logic. Sequential model uses `max_incompatible_residual(next_precursor)` and the existing `max_residual_fraction` threshold.

- [ ] **Step 7: Emit concrete sequential surface JSON without changing legacy JSON**

A 3-step snapshot serializes as:

```json
{
  "model_version": "site-sequential/1",
  "states_by_region": [[950, 20, 15], [940, 25, 20]],
  "residuals_by_region": [{"A": 0.01, "B": 0.02, "C": 0.01}, {"A": 0.02, "B": 0.01, "C": 0.01}],
  "coverage": 0.015,
  "thickness_nm": 0.004,
  "utilization": 0.02,
  "defect_fraction": 0.005,
  "completed_depositions": 40,
  "exposure_signature": ["A", "B", "C"]
}
```

The numbers above illustrate shape only; tests compare deterministic runtime output rather than these literal values. `cycles.csv` keeps existing columns.

- [ ] **Step 8: Run and commit**

```bash
python -m pytest tests/test_multi_precursor_controller.py tests/test_multi_precursor_schema.py tests/test_sequential_surface.py tests/test_ald_media_controller.py -q
git add ald_core.py ald_hardened_core.py tests/test_multi_precursor_controller.py
git commit -m "feat: execute multi-precursor deposition cycles"
```

---

### Task 5: Extend HLS/Product-MP4 round trips and surrogate visuals

**Files:**
- Modify: `ald_product_scene.py`
- Modify: `ald_product_svg.py`
- Modify: `ald_product_render.py`
- Create: `tests/test_multi_precursor_media.py`

**Interfaces:**
- Existing canonical packet bytes remain authoritative in media.
- Product scene adds sequence identity only; it does not expose operational values.

- [ ] **Step 1: Write RED media equivalence tests using a maintained 3-precursor recipe**

```python
@pytest.mark.requires_ffmpeg
def test_multi_precursor_product_round_trip_matches_direct(tmp_path):
    recipe = Path("recipes/compounds/research/acceptance_three_precursor.json")
    direct = tmp_path / "direct"
    bundle = tmp_path / "bundle"
    media_run = tmp_path / "media"
    assert cli.main(["simulate", str(recipe), "--seed", "42", "--output", str(direct)]) == 0
    assert product_cli.main(["compile-product", str(recipe), "--seed", "42", "--output", str(bundle)]) == 0
    assert product_cli.main(["simulate-product", str(bundle / "bundle.json"), "--seed", "42", "--output", str(media_run)]) == 0
    for name in ("cycles.csv", "surface-final.json", "audit.jsonl"):
        assert (direct / name).read_bytes() == (media_run / name).read_bytes()
```

Add equivalent HLS compile/verify/simulate-media coverage in the same file.

- [ ] **Step 2: Keep media packet format unchanged**

No new ALDP/HLS record version. Add a tamper test that changes one exposure `precursor` or `dose`, recomputes neither digest nor bundle metadata, and assert verification raises `IntegrityError`.

- [ ] **Step 3: Bind multi-precursor product-scene metadata**

Surrogate scene/product JSON adds exact fields `recipe_schema`, `target_material`, and `precursor_sequence`, where `precursor_sequence` is a tuple of objects containing `id`, `name`, and `formula`. Do not include dose, purge, temperature, pressure, flow, or kinetic values.

- [ ] **Step 4: Update SVG/raster text**

For `multi-precursor/1`, render "Named precursor simulation sequence" plus identifier/name/formula in exposure order. For legacy product recipes retain current generic A/B wording. Majorana compatibility modules remain unchanged.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/test_multi_precursor_media.py tests/test_hls_integration.py tests/test_product_cli.py tests/test_product_verification.py -q
git add ald_product_scene.py ald_product_svg.py ald_product_render.py tests/test_multi_precursor_media.py
git commit -m "feat: transport multi-precursor recipes through media"
```

---

### Task 6: Document schema and add maintained 3- and 6-precursor acceptance recipes

**Files:**
- Modify: `docs/recipe-authoring.md`
- Modify: `recipes/README.md`
- Create: `recipes/compounds/README.md`
- Create: `recipes/compounds/research/acceptance_three_precursor.json`
- Create: `recipes/compounds/research/acceptance_six_precursor_surrogate.json`

- [ ] **Step 1: Document legacy and multi-precursor authoring contracts**

Document exact precursor object shape, contiguous A–F rule, `DEPOSITION_CYCLE`, 2–12 exposure rule, repeated precursor semantics, synthetic dimensionless `dose`, sequential surface fields, status taxonomy, and source-reference policy.

- [ ] **Step 2: Add the 3-precursor maintained media fixture**

Use three real named chemicals with a literature-grounded target/precursor pairing. Mark operational values synthetic. Keep packet <=800 bytes.

- [ ] **Step 3: Add the 6-precursor maintained maximum-width fixture**

Use six distinct real chemical identities, all used in the sequence, and mark `chemistry_status: "conceptual-multicomponent-surrogate"` unless the exact six-source route has a direct credible source. The target name must explicitly say `surrogate` when conceptual.

- [ ] **Step 4: Verify both examples**

```bash
ald-media-controller validate recipes/compounds/research/acceptance_three_precursor.json
ald-media-controller simulate recipes/compounds/research/acceptance_three_precursor.json --seed 42 --output build/three-precursor-acceptance
ald-media-controller validate recipes/compounds/research/acceptance_six_precursor_surrogate.json
ald-media-controller simulate recipes/compounds/research/acceptance_six_precursor_surrogate.json --seed 42 --output build/six-precursor-acceptance
```

- [ ] **Step 5: Commit**

```bash
git add docs/recipe-authoring.md recipes/README.md recipes/compounds/README.md recipes/compounds/research/acceptance_three_precursor.json recipes/compounds/research/acceptance_six_precursor_surrogate.json
git commit -m "docs: add multi-precursor authoring contract"
```

---

### Task 7: Add deterministic catalog indexing and repository chemistry QA

**Files:**
- Create: `tools/build_compound_catalog.py`
- Create: `tests/test_compound_catalog.py`
- Create: `recipes/compounds/catalog.json`

**Interfaces:**
- `build_compound_catalog(root: Path) -> dict[str, object]`
- CLI: `python tools/build_compound_catalog.py` writes index; `--check` byte-compares generated canonical JSON with checked-in index.

- [ ] **Step 1: Write RED index integrity tests**

```python
FORBIDDEN_METADATA_KEYS = {
    "process_temperature", "pulse_time", "flow_sccm", "process_pressure",
    "growth_window", "dose_time", "handling_notes"
}


def test_catalog_entries_are_unique_and_non_operational():
    entries = load_catalog_entries()
    assert len({entry["recipe_id"] for entry in entries}) == len(entries)
    for entry in entries:
        raw = json.loads(Path(entry["path"]).read_text())
        assert raw["metadata"]["physical_fabrication_mapping"] is False
        assert not FORBIDDEN_METADATA_KEYS.intersection(raw["metadata"])
        names = [value["name"] for value in raw["precursors"].values()]
        assert len(names) == len(set(names))
```

- [ ] **Step 2: Add explicit coverage-floor test**

```python
def test_catalog_meets_coverage_floors():
    entries = load_catalog_entries()
    family = Counter(entry["chemistry_family"] for entry in entries)
    counts = Counter(entry["precursor_count"] for entry in entries)
    assert len(entries) >= 100
    assert family["oxide"] >= 30
    assert family["nitride"] >= 10
    assert family["chalcogenide"] >= 10
    assert sum(family[name] for name in ("metal", "carbide", "other-inorganic")) >= 10
    assert counts[3] >= 15
    assert counts[4] >= 8
    assert counts[5] >= 4
    assert counts[6] >= 4
```

Also assert combined ternary/multicomponent/nanolaminate count >=15 and combined MLD/hybrid/research count >=15 using catalog classification fields.

- [ ] **Step 3: Implement deterministic index builder**

Discover JSON recipe files only in category directories, exclude `catalog.json`, validate each through `ald_core`, derive fields from normalized recipe metadata/precursors, sort entries by repository-relative path, and serialize with `ensure_ascii=False`, `allow_nan=False`, `sort_keys=True`, `separators=(",", ":")`, plus one LF.

- [ ] **Step 4: Implement `--check`**

Generate bytes in memory and compare exactly with `recipes/compounds/catalog.json`; print a concise drift error and exit 1 when different.

- [ ] **Step 5: Commit RED catalog harness**

```bash
git add tools/build_compound_catalog.py tests/test_compound_catalog.py recipes/compounds/catalog.json
git commit -m "test: add compound catalog integrity checks"
```

Coverage-floor test remains RED until bulk data tasks are complete.

---

### Task 8: Curate oxide and nitride recipes

**Files:**
- Create: at least 36 `recipes/compounds/oxides/*.json`
- Create: at least 12 `recipes/compounds/nitrides/*.json`
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate oxide targets from credible public sources**

Cover at least these families when precursor pairings are publicly documented: Al2O3, HfO2, ZrO2, TiO2, ZnO, SiO2, Ta2O5, Nb2O5, vanadium oxides, WO3, MoOx, SnO2, In2O3, Ga2O3, Y2O3, La2O3, CeO2, MgO, CaO, SrO, BaO, FeOx, CoOx, NiO, CuOx, MnOx, Cr2O3, Sc2O3, Er2O3, Gd2O3, Dy2O3, Lu2O3, BiOx, RuO2, and IrOx. Multiple routes for one target require materially different precursor chemistry and separate source support.

- [ ] **Step 2: Curate nitride targets**

Cover at least AlN, TiN, TaN, HfN, ZrN, VN, NbN, WN, MoN, SiNx, BN, and GaN where target/precursor pairings are documented. Mark less mature routes `research-stage`.

- [ ] **Step 3: Populate each recipe consistently**

Each file must contain real precursor `name/formula/role`, target metadata, status, source identifiers, contiguous A–F IDs, one stable exposure signature, `site-sequential/1`, and synthetic controller/surface parameters drawn from a small fixed set of internal simulator profiles rather than literature conditions.

- [ ] **Step 4: Validate/simulate/index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/oxides recipes/compounds/nitrides recipes/compounds/catalog.json
git commit -m "feat: add oxide and nitride recipe catalog"
```

---

### Task 9: Curate chalcogenide, metal, carbide, and other inorganic recipes

**Files:**
- Create: at least 16 `recipes/compounds/chalcogenides/*.json`
- Create: at least 10 `recipes/compounds/metals/*.json`
- Create: at least 8 `recipes/compounds/carbides_and_other_inorganics/*.json`
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate chalcogenide targets**

Prioritize ZnS, CdS, PbS, SnS, SnS2, In2S3, TiS2, MoS2, WS2, copper sulfides, ZnSe, CdSe, SnSe, MoSe2, WSe2, and other documented sulfide/selenide ALD routes.

- [ ] **Step 2: Curate metal targets**

Prioritize Pt, Ru, Ir, Pd, Rh, Co, Ni, Cu, W, and Mo where public precursor/reductant chemistry is documented.

- [ ] **Step 3: Curate carbide/other-inorganic targets**

Add documented carbide, boride, phosphate, fluoride, and related inorganic ALD/MLD systems. Do not fill counts with unsupported chemistry.

- [ ] **Step 4: Validate/simulate/index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/chalcogenides recipes/compounds/metals recipes/compounds/carbides_and_other_inorganics recipes/compounds/catalog.json
git commit -m "feat: add chalcogenide metal and inorganic recipes"
```

---

### Task 10: Curate ternary, multicomponent, nanolaminate, and 3–6 precursor recipes

**Files:**
- Create: at least 16 `recipes/compounds/ternary_and_multicomponent/*.json`
- Create: at least 16 `recipes/compounds/nanolaminates_and_supercycles/*.json`
- Update: `recipes/compounds/catalog.json`
- Modify: `tests/test_compound_catalog.py`

- [ ] **Step 1: Curate grounded multicomponent families**

Prioritize Hf-Al-O, Hf-Si-O, Zr-Al-O, Al-Ti-O, Sr-Ti-O, Ba-Ti-O, La-Al-O, Li-Al-O, and documented battery/dielectric multicomponent families.

- [ ] **Step 2: Use conceptual status for simulator supercycles not directly published as exact routes**

When a recipe combines grounded constituent chemistries but the exact multi-source sequence lacks a direct source, set `chemistry_status` to `conceptual-multicomponent-surrogate`, make the target name explicitly include `surrogate`, and cite constituent chemistry sources only.

- [ ] **Step 3: Satisfy the 3–6 precursor floors without filler chemicals**

Across the catalog, reach >=15 three-precursor, >=8 four-precursor, >=4 five-precursor, and >=4 six-precursor recipes. Every declared chemical must have a distinct name and be used at least once in the exposure sequence.

- [ ] **Step 4: Add exact anti-padding test**

```python
def test_five_and_six_precursor_recipes_are_not_padded():
    for path, raw in iter_catalog_recipe_json():
        if len(raw["precursors"]) < 5:
            continue
        names = [item["name"] for item in raw["precursors"].values()]
        assert len(names) == len(set(names)), path
        used = {item["precursor"] for item in deposition_exposures(raw)}
        assert used == set(raw["precursors"]), path
        if raw["metadata"]["chemistry_status"] != "conceptual-multicomponent-surrogate":
            assert raw["metadata"]["source_references"], path
```

- [ ] **Step 5: Validate/simulate/index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/ternary_and_multicomponent recipes/compounds/nanolaminates_and_supercycles recipes/compounds/catalog.json tests/test_compound_catalog.py
git commit -m "feat: add multicomponent and six-precursor recipes"
```

---

### Task 11: Curate MLD, hybrid, and research-stage molecular-layer systems

**Files:**
- Create: at least 18 `recipes/compounds/molecular_layer_deposition/*.json`
- Create: at least 12 additional `recipes/compounds/research/*.json`
- Update: `recipes/compounds/catalog.json`

- [ ] **Step 1: Curate documented MLD/hybrid families**

Cover alucone, zincone, titanicone, zirconicone, hafnicone, and other documented organic-inorganic molecular-layer networks using real named metal precursors and bifunctional organic co-reactants. Use the literature's film/network terminology; do not claim isolated molecule synthesis when the source describes a film.

- [ ] **Step 2: Extend research-stage coverage**

Add credible research systems in oxynitrides, complex oxides, 2D chalcogenides, hybrid networks, battery coatings, and other underrepresented ALD/MLD families.

- [ ] **Step 3: Reach 120+ total when source quality permits**

Continue adding non-duplicate routes beyond 100 until additional count would require unsupported precursor pairings, duplicate routes, or misleading chemistry claims.

- [ ] **Step 4: Validate every recipe twice at seed 42**

`tests/test_compound_catalog.py` loops over every path, validates/compiles, executes twice at seed 42, asserts no controller fault, and compares `surface.as_dict()` and `cycles` between runs.

- [ ] **Step 5: Rebuild index and commit**

```bash
python tools/build_compound_catalog.py
python -m pytest tests/test_compound_catalog.py -q
git add recipes/compounds/molecular_layer_deposition recipes/compounds/research recipes/compounds/catalog.json
git commit -m "feat: add MLD and research recipe catalog"
```

---

### Task 12: Add CI gates and final full-system verification

**Files:**
- Modify: `.github/workflows/core-hardening.yml`
- Modify: `.github/workflows/hls-integration.yml`
- Modify: `.github/workflows/product-mp4.yml`
- Modify: `recipes/compounds/README.md`

- [ ] **Step 1: Add core catalog checks**

Add exact commands:

```bash
python tools/build_compound_catalog.py --check
python -m pytest -q
python -m py_compile ald_core.py ald_sequential_surface.py ald_hardened_core.py
```

- [ ] **Step 2: Add one 3-precursor HLS acceptance path**

Compile, verify, direct-simulate, simulate-media, then `cmp` `cycles.csv`, `surface-final.json`, and `audit.jsonl`.

- [ ] **Step 3: Add one 6-precursor Product-MP4 acceptance path**

Compile-product, verify-product, direct simulate, simulate-product, compare the same three reports, and ffprobe exactly the existing H264/AAC/bin_data-gpmd three-stream profile.

- [ ] **Step 4: Run the complete local verification matrix**

```bash
python tools/build_compound_catalog.py --check
python -m pytest -q
python -m py_compile ald_core.py ald_sequential_surface.py ald_hardened_core.py ald_media_codecs.py ald_media_cli.py ald_product_scene.py ald_product_svg.py ald_product_render.py ald_product_verify.py
```

Then run both FFmpeg acceptance paths. Confirm the legacy root is exactly `ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0`.

- [ ] **Step 5: Update README generated counts**

Document exact totals by family, chemistry status, and precursor count from `catalog.json`, the index regeneration command, and the rule that references support chemical identity only, not executable process conditions.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/core-hardening.yml .github/workflows/hls-integration.yml .github/workflows/product-mp4.yml recipes/compounds/README.md
git commit -m "ci: verify multi-precursor catalog and media paths"
```

---

## Final Review Gate

Before merging implementation:

1. Legacy generic Al2O3 root equals `ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0`.
2. Every new recipe contains 2–6 contiguous precursor IDs with real `name`, `formula`, and `role`.
3. No catalog entry contains copied operational process windows or chemical-handling instructions.
4. Every `established`/`research-stage` source reference supports the target/precursor pairing.
5. Every 5/6 precursor recipe uses all unique precursors and is not padded.
6. Full pytest, py_compile, catalog `--check`, HLS acceptance, Product-MP4 acceptance, signed-product regression, and legacy Majorana safety binding pass on the exact PR head.
7. PR diff contains no unintended modification to Majorana compatibility backends or unrelated code.
