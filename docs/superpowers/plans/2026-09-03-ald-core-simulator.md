# ALD Core Recipe Compiler and Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, simulation-only ALD recipe compiler, hash-chain generator, controller state machine, surface model, and direct-mode CLI.

**Architecture:** `ald_media_controller.py` is the standalone entrypoint and contains isolated dataclasses and services for recipes, packets, hashing, surface reactions, controller execution, reporting, and CLI dispatch. This phase has no media encoder, network client, or hardware adapter; later phases consume its `CompiledRecipe` and `HashedPacket` interfaces.

**Tech Stack:** Python 3.10+, standard library, NumPy, pytest

**Spec:** `docs/specs/2026-09-03-ald-media-controller-design.md`

## Global Constraints

- Support Python 3.10 or newer.
- Keep the program simulation-only: no external machine, network, valve, heater, pump, door, robot, or precursor-control path.
- Use canonical UTF-8 JSON with sorted keys, no insignificant whitespace, finite numbers only, and schema-controlled strings.
- Compute `H_i = SHA-256(ASCII("ALD1") || H_(i-1) || P_i)` with `H_0` equal to 32 zero bytes.
- Preserve repeated processing as one `ALD_CYCLE` packet with `repeat`; do not unroll cycles into instruction packets.
- Fail closed on malformed recipes, limit violations, invalid state transitions, and interlock failures.
- Keep A and B precursor valves mutually exclusive and enforce minimum purge intervals structurally.
- Derive surface random streams from recipe root hash, model version, user seed, cycle, half-reaction, and region.
- Treat aggregate site counts as authoritative and bound optional site-event samples.
- Use distinct CLI exit codes for recipe, limit, controller, surface, dependency, and output failures.

---

## File Map

- Create `pyproject.toml`: Python floor, runtime dependency, pytest configuration, and console entrypoint.
- Create `ald_media_controller.py`: errors, dataclasses, parser, compiler, hash chain, surface model, controller, reporting, and CLI.
- Create `recipes/generic_al2o3.json`: safe generic A/B demonstration recipe with TMA/water labels.
- Create `tests/test_ald_media_controller.py`: all core unit and direct-mode integration tests.
- Modify `README.md`: installation, simulation-only boundary, and direct-mode examples.

### Task 1: Project shell and deterministic CLI boundary

**Files:**
- Create: `pyproject.toml`
- Create: `ald_media_controller.py`
- Create: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: command-line `Sequence[str]`.
- Produces: `ExitCode`, `ALDError`, `build_parser() -> argparse.ArgumentParser`, and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing CLI tests**

```python
from ald_media_controller import ExitCode, main


def test_main_without_command_returns_usage_error(capsys):
    assert main([]) == ExitCode.USAGE
    assert "usage:" in capsys.readouterr().err.lower()


def test_cli_has_no_live_or_network_command():
    source = Path("ald_media_controller.py").read_text(encoding="utf-8")
    assert "live-control" not in source
    assert "socket." not in source
    assert "requests." not in source
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'main_without or no_live' -v`

Expected: collection fails because `ald_media_controller` does not exist.

- [ ] **Step 3: Add packaging and the minimal CLI shell**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ald-media-controller"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["numpy>=1.24,<3"]

[project.optional-dependencies]
test = ["pytest>=8,<10"]

[project.scripts]
ald-media-controller = "ald_media_controller:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```python
class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    RECIPE = 3
    LIMIT = 4
    MEDIA = 5
    FRAME = 6
    AUDIO = 7
    SYNC = 8
    INTEGRITY = 9
    CONTROLLER = 10
    SURFACE = 11
    OUTPUT = 12
    DEPENDENCY = 13


class ALDError(Exception):
    exit_code = ExitCode.USAGE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ald-media-controller")
    parser.add_subparsers(dest="command", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit:
        return int(ExitCode.USAGE)
    return int(ExitCode.OK)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'main_without or no_live' -v`

Expected: 2 passed.

- [ ] **Step 5: Commit the project shell**

```bash
git add pyproject.toml ald_media_controller.py tests/test_ald_media_controller.py
git commit -m "build: add ALD simulator project shell"
```

### Task 2: Strict recipe schema, canonical packets, and hash chain

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: `load_recipe(path: Path) -> Mapping[str, Any]` and validated recipe mappings.
- Produces: `Recipe`, `Packet`, `HashedPacket`, `CompiledRecipe`, `validate_recipe(raw: Mapping[str, Any]) -> Recipe`, `canonical_packet_bytes(packet: Packet) -> bytes`, and `compile_recipe(recipe: Recipe) -> CompiledRecipe`.

- [ ] **Step 1: Write failing parser and canonicalization tests**

```python
def test_duplicate_json_key_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"protocol":"ALD-MEDIA/1","protocol":"other"}')
    with pytest.raises(RecipeError, match="duplicate key: protocol"):
        load_recipe(path)


def test_cycle_repeat_remains_one_packet(valid_recipe_dict):
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 500
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))
    cycle = next(p for p in compiled.packets if p.packet.opcode == "ALD_CYCLE")
    assert cycle.packet.arguments["repeat"] == 500
    assert sum(p.packet.opcode == "ALD_CYCLE" for p in compiled.packets) == 1


def test_hash_chain_matches_formula(valid_recipe_dict):
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))
    previous = bytes(32)
    for item in compiled.packets:
        expected = hashlib.sha256(b"ALD1" + previous + item.canonical_bytes).digest()
        assert item.digest == expected
        previous = expected
    assert compiled.root_hash == previous
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'duplicate_json or cycle_repeat or hash_chain' -v`

Expected: tests fail because recipe and packet interfaces are missing.

- [ ] **Step 3: Implement immutable recipe and packet types**

```python
@dataclass(frozen=True)
class ProcessLimits:
    min_purge_ms: int
    max_temperature_c: float
    max_pressure_pa: float
    max_cycles: int
    max_runtime_ms: int
    max_residual_fraction: float
    max_packet_bytes: int = 800


JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class Recipe:
    protocol: str
    recipe_id: str
    metadata: Mapping[str, JSONValue]
    precursors: Mapping[str, Mapping[str, JSONValue]]
    initial_conditions: Mapping[str, float]
    limits: ProcessLimits
    surface: Mapping[str, JSONValue]
    instructions: tuple[Mapping[str, JSONValue], ...]


@dataclass(frozen=True)
class Packet:
    protocol: str
    recipe_id: str
    sequence: int
    opcode: str
    arguments: Mapping[str, JSONValue]


@dataclass(frozen=True)
class HashedPacket:
    packet: Packet
    canonical_bytes: bytes
    previous_digest: bytes
    digest: bytes


@dataclass(frozen=True)
class CompiledRecipe:
    recipe: Recipe
    packets: tuple[HashedPacket, ...]
    root_hash: bytes
```

Implement duplicate-key rejection with `json.load(..., object_pairs_hook=reject_duplicates)`. Validate exact top-level and opcode-specific key sets, `protocol == "ALD-MEDIA/1"`, integer millisecond fields, finite floats, contiguous generated sequence numbers, `repeat >= 1`, expanded cycles within `max_cycles`, purge durations at least `min_purge_ms`, and all targets within global limits.

- [ ] **Step 4: Implement canonical bytes and the exact hash-chain formula**

```python
def canonical_packet_bytes(packet: Packet) -> bytes:
    payload = {
        "arguments": dict(packet.arguments),
        "opcode": packet.opcode,
        "protocol": packet.protocol,
        "recipe_id": packet.recipe_id,
        "sequence": packet.sequence,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 800:
        raise RecipeLimitError("canonical packet exceeds 800 bytes")
    return encoded


def hash_packet(previous: bytes, payload: bytes) -> bytes:
    return hashlib.sha256(b"ALD1" + previous + payload).digest()
```

- [ ] **Step 5: Run all recipe/hash tests and verify GREEN**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'recipe or packet or hash or repeat' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the recipe compiler**

```bash
git add ald_media_controller.py tests/test_ald_media_controller.py
git commit -m "feat: compile canonical ALD recipe packets"
```

### Task 3: Deterministic region-based surface model

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: `SurfaceConfig`, recipe root hash, user seed, cycle index, half-reaction, dose, and region.
- Produces: `SurfaceModel.expose_a(...) -> ExposureResult`, `SurfaceModel.expose_b(...) -> ExposureResult`, `SurfaceModel.purge(...) -> None`, and `SurfaceModel.snapshot() -> SurfaceSnapshot`.

- [ ] **Step 1: Write failing conservation and reproducibility tests**

```python
def test_surface_counts_are_conserved(surface_config):
    model = SurfaceModel(surface_config, root_hash=b"r" * 32, user_seed=42)
    before = model.total_sites
    model.expose_a(cycle=1, dose=1.5)
    model.purge(duration_ms=5000, half_life_ms=800)
    model.expose_b(cycle=1, dose=1.2)
    assert model.total_sites == before


def test_surface_seed_is_reproducible_and_sampling_independent(surface_config):
    a = SurfaceModel(surface_config, b"h" * 32, 42, max_event_samples=0)
    b = SurfaceModel(surface_config, b"h" * 32, 42, max_event_samples=100)
    for model in (a, b):
        model.expose_a(cycle=7, dose=1.5)
        model.expose_b(cycle=7, dose=1.2)
    assert a.snapshot() == b.snapshot()
```

- [ ] **Step 2: Run surface tests and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py -k surface -v`

Expected: tests fail because `SurfaceModel` is missing.

- [ ] **Step 3: Implement region state and deterministic generators**

```python
@dataclass(frozen=True)
class SurfaceConfig:
    model_version: str
    regions: int
    sites_per_region: int
    transport_factors: tuple[float, ...]
    blocked_fraction: float
    defect_fraction: float
    k_a: float
    k_b: float
    growth_nm_per_reaction_fraction: float
    purge_half_life_ms: int


@dataclass
class SurfaceRegion:
    vacant: int
    a_terminated: int
    b_reacted: int
    blocked: int
    defects: int
    residual_a: float = 0.0
    residual_b: float = 0.0


def reaction_probability(rate: float, dose: float) -> float:
    if not math.isfinite(rate) or not math.isfinite(dose) or rate < 0 or dose < 0:
        raise SurfaceModelError("rate and dose must be finite and non-negative")
    return -math.expm1(-rate * dose)


def reaction_rng(root_hash: bytes, model_version: str, seed: int,
                 cycle: int, half_reaction: str, region: int) -> np.random.Generator:
    material = b"\0".join([
        root_hash, model_version.encode(), str(seed).encode(), str(cycle).encode(),
        half_reaction.encode(), str(region).encode(),
    ])
    entropy = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
    return np.random.Generator(np.random.PCG64(entropy))
```

For each region, sample eligible reactions with `rng.binomial(eligible, p)`, subtract from the source state, add to the destination state, and assert the region total is unchanged. Generate bounded display samples from a separate `"sample"` RNG domain so enabling samples cannot alter aggregate draws.

- [ ] **Step 4: Implement purge and aggregate snapshots**

```python
def decay_residual(value: float, duration_ms: int, half_life_ms: int) -> float:
    if duration_ms < 0 or half_life_ms <= 0:
        raise SurfaceModelError("invalid purge timing")
    return value * math.exp(-math.log(2.0) * duration_ms / half_life_ms)
```

`snapshot()` returns immutable per-region counts plus totals, coverage, thickness, utilization, and defect fraction. Thickness is calculated from completed B reactions and `growth_nm_per_reaction_fraction`, not from the number of logged samples.

- [ ] **Step 5: Run surface tests and verify GREEN**

Run: `python -m pytest tests/test_ald_media_controller.py -k surface -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the surface model**

```bash
git add ald_media_controller.py tests/test_ald_media_controller.py
git commit -m "feat: add deterministic ALD surface model"
```

### Task 4: Controller state machine, interlocks, and fault shutdown

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: `CompiledRecipe`, `SurfaceModel`, and `Interlocks`.
- Produces: `SimulatedALDController.execute(compiled: CompiledRecipe, seed: int) -> SimulationResult`, ordered `AuditEvent` values, and `FaultRecord`.

- [ ] **Step 1: Write failing transition and fault tests**

```python
def test_a_and_b_valves_never_overlap(compiled_recipe):
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    assert all(not (e.valve_a_open and e.valve_b_open) for e in result.audit)


def test_short_purge_faults_closed(valid_recipe_dict):
    valid_recipe_dict["instructions"][4]["arguments"]["purge_a_ms"] = 1
    with pytest.raises(RecipeLimitError, match="minimum purge"):
        compile_recipe(validate_recipe(valid_recipe_dict))


def test_interlock_loss_closes_valves_and_returns_idle(compiled_recipe):
    controller = SimulatedALDController(interlocks=Interlocks(vacuum_available=False))
    result = controller.execute(compiled_recipe, seed=42)
    assert result.fault.code == "VACUUM_UNAVAILABLE"
    assert result.final_state is ControllerState.IDLE
    assert result.chamber.valve_a_open is False
    assert result.chamber.valve_b_open is False
```

- [ ] **Step 2: Run controller tests and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'valves or purge_faults or interlock' -v`

Expected: tests fail because controller interfaces are missing.

- [ ] **Step 3: Implement the allowed transition table and virtual chamber**

```python
@dataclass(frozen=True)
class Interlocks:
    chamber_closed: bool = True
    vacuum_available: bool = True
    exhaust_available: bool = True
    temperature_controller_available: bool = True
    watchdog_healthy: bool = True


@dataclass
class VirtualChamber:
    simulation_time_ms: int
    temperature_c: float
    pressure_pa: float
    valve_a_open: bool = False
    valve_b_open: bool = False
    inert_purge_open: bool = False
    pump_on: bool = False


ALLOWED_TRANSITIONS = {
    ControllerState.IDLE: {ControllerState.CONFIGURED},
    ControllerState.CONFIGURED: {ControllerState.HEATING, ControllerState.FAULT},
    ControllerState.HEATING: {ControllerState.EVACUATING, ControllerState.FAULT},
    ControllerState.EVACUATING: {ControllerState.READY, ControllerState.FAULT},
    ControllerState.READY: {ControllerState.A_PULSE, ControllerState.COMPLETE, ControllerState.FAULT},
    ControllerState.A_PULSE: {ControllerState.A_PURGE, ControllerState.FAULT},
    ControllerState.A_PURGE: {ControllerState.B_PULSE, ControllerState.FAULT},
    ControllerState.B_PULSE: {ControllerState.B_PURGE, ControllerState.FAULT},
    ControllerState.B_PURGE: {ControllerState.READY, ControllerState.FAULT},
    ControllerState.COMPLETE: {ControllerState.SHUTDOWN},
    ControllerState.FAULT: {ControllerState.SHUTDOWN},
    ControllerState.SHUTDOWN: {ControllerState.IDLE},
}
```

Every `transition()` validates the table, increments the audit record number, uses monotonic simulation time, and records both valve states. Implement deterministic heating, evacuation, stabilization, pulse, purge, measurement, and shutdown updates without wall-clock sleeps.

Define immutable `AuditEvent(record_number, simulation_time_ms, event_type, state, packet_sequence, valve_a_open, valve_b_open, details)`, `CycleMetric(cycle, simulation_time_ms, coverage, thickness_nm, utilization, defect_fraction)`, `FaultRecord(code, packet_sequence, state, last_verified_digest, chamber, interlocks)`, and `SimulationResult(audit, cycles, surface, fault, final_state, chamber)` dataclasses. Store sequences as tuples so report generation cannot mutate completed results.

- [ ] **Step 4: Implement pre-pulse invariants and one fault path**

```python
def assert_precursor_safe(self, next_precursor: str) -> None:
    if not self.interlocks.chamber_closed:
        raise ControllerFault("CHAMBER_OPEN")
    if not self.interlocks.vacuum_available:
        raise ControllerFault("VACUUM_UNAVAILABLE")
    if not self.interlocks.exhaust_available:
        raise ControllerFault("EXHAUST_UNAVAILABLE")
    if self.chamber.valve_a_open or self.chamber.valve_b_open:
        raise ControllerFault("PRECURSOR_VALVE_ALREADY_OPEN")
    if not self.temperature_is_stable():
        raise ControllerFault("TEMPERATURE_UNSTABLE")
    if self.incompatible_residual(next_precursor) > self.limits.max_residual_fraction:
        raise ControllerFault("INCOMPATIBLE_RESIDUAL")
```

Catch `ControllerFault` once at the execution boundary. Capture the current packet, sequence, chamber snapshot, interlocks, and last verified digest; close both valves before recording `FAULT`; run the simulated shutdown policy; never resume the recipe.

- [ ] **Step 5: Run controller tests and verify GREEN**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'controller or transition or valve or purge or interlock or fault' -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit controller behavior**

```bash
git add ald_media_controller.py tests/test_ald_media_controller.py
git commit -m "feat: simulate ALD controller interlocks"
```

### Task 5: Direct-mode reports and CLI commands

**Files:**
- Modify: `ald_media_controller.py`
- Modify: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: recipe path, output directory, seed, and `SimulationResult`.
- Produces: `validate`, `simulate`, `audit.jsonl`, `cycles.csv`, `surface-final.json`, and optional `fault.json`.

- [ ] **Step 1: Write failing CLI integration tests**

```python
def test_validate_prints_root_hash(sample_recipe_path, capsys):
    assert main(["validate", str(sample_recipe_path)]) == ExitCode.OK
    result = json.loads(capsys.readouterr().out)
    assert result["protocol"] == "ALD-MEDIA/1"
    assert len(result["root_hash"]) == 64


def test_simulate_writes_required_outputs(sample_recipe_path, tmp_path):
    out = tmp_path / "run"
    assert main(["simulate", str(sample_recipe_path), "--seed", "42", "--output", str(out)]) == ExitCode.OK
    assert {p.name for p in out.iterdir()} == {"audit.jsonl", "cycles.csv", "surface-final.json"}
```

- [ ] **Step 2: Run direct CLI tests and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py -k 'validate_prints or simulate_writes' -v`

Expected: tests fail because the subcommands and report writers are missing.

- [ ] **Step 3: Implement atomic report publication**

```python
def publish_reports(result: SimulationResult, output: Path, overwrite: bool = False) -> None:
    if output.exists() and not overwrite:
        raise OutputError(f"output exists: {output}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        write_audit_jsonl(result.audit, temporary / "audit.jsonl")
        write_cycle_csv(result.cycles, temporary / "cycles.csv")
        write_json(result.surface.as_dict(), temporary / "surface-final.json")
        if result.fault is not None:
            write_json(result.fault.as_dict(), temporary / "fault.json")
        replace_output_directory(temporary, output, overwrite=overwrite)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
```

- [ ] **Step 4: Wire `validate` and `simulate` through one error mapper**

Add parser arguments exactly as specified. Map each `ALDError.exit_code` to the process result, write one structured error object to stderr, and never emit a Python traceback unless `--log-level DEBUG` is selected.

- [ ] **Step 5: Run the complete core suite and verify GREEN**

Run: `python -m pytest tests/test_ald_media_controller.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit direct-mode CLI and reports**

```bash
git add ald_media_controller.py tests/test_ald_media_controller.py
git commit -m "feat: add direct ALD simulation CLI"
```

### Task 6: Generic Al2O3 example, documentation, and phase acceptance

**Files:**
- Create: `recipes/generic_al2o3.json`
- Modify: `README.md`
- Modify: `tests/test_ald_media_controller.py`

**Interfaces:**
- Consumes: public `validate` and `simulate` CLI behavior.
- Produces: a reproducible example recipe and documented commands for users and later phases.

- [ ] **Step 1: Add a failing sample-recipe acceptance test**

```python
def test_checked_in_al2o3_recipe_runs_twice_identically(tmp_path):
    recipe = Path("recipes/generic_al2o3.json")
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(first)]) == 0
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(second)]) == 0
    assert (first / "surface-final.json").read_bytes() == (second / "surface-final.json").read_bytes()
    assert (first / "cycles.csv").read_bytes() == (second / "cycles.csv").read_bytes()
```

- [ ] **Step 2: Run the sample test and verify RED**

Run: `python -m pytest tests/test_ald_media_controller.py::test_checked_in_al2o3_recipe_runs_twice_identically -v`

Expected: FAIL because the checked-in recipe is absent.

- [ ] **Step 3: Add the complete generic A/B recipe**

Write this exact schema instance; adjust only key ordering to the canonical serializer:

```json
{
  "protocol": "ALD-MEDIA/1",
  "recipe_id": "generic-al2o3-001",
  "metadata": {
    "material": "Al2O3",
    "simulation_notice": "Precursor names are simulation labels, not operational handling instructions."
  },
  "precursors": {
    "A": {"label": "trimethylaluminum"},
    "B": {"label": "water"}
  },
  "initial_conditions": {
    "temperature_c": 25.0,
    "pressure_pa": 101325.0
  },
  "limits": {
    "min_purge_ms": 1000,
    "max_temperature_c": 300.0,
    "max_pressure_pa": 200000.0,
    "max_cycles": 1000,
    "max_runtime_ms": 3600000,
    "max_residual_fraction": 0.01,
    "max_packet_bytes": 800
  },
  "surface": {
    "model_version": "site-binomial/1",
    "regions": 4,
    "sites_per_region": 250000,
    "transport_factors": [0.95, 1.0, 1.0, 0.95],
    "blocked_fraction": 0.01,
    "defect_fraction": 0.005,
    "k_a": 1.5,
    "k_b": 1.4,
    "growth_nm_per_reaction_fraction": 0.11,
    "purge_half_life_ms": 800,
    "max_event_samples": 100
  },
  "instructions": [
    {"opcode": "CONFIGURE", "arguments": {}},
    {"opcode": "SET_TEMPERATURE", "arguments": {"target_c": 200.0, "ramp_c_per_min": 20.0, "tolerance_c": 1.0}},
    {"opcode": "EVACUATE", "arguments": {"target_pa": 100.0, "timeout_ms": 900000}},
    {"opcode": "STABILIZE", "arguments": {"duration_ms": 60000}},
    {"opcode": "ALD_CYCLE", "arguments": {
      "precursor_a": "A", "pulse_a_ms": 100, "flow_a_sccm": 50.0, "purge_a_ms": 5000,
      "precursor_b": "B", "pulse_b_ms": 100, "flow_b_sccm": 50.0, "purge_b_ms": 5000,
      "repeat": 100
    }},
    {"opcode": "MEASURE", "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]}},
    {"opcode": "SHUTDOWN", "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0}}
  ]
}
```

- [ ] **Step 4: Document installation and the direct workflow**

Add:

```bash
python -m pip install -e '.[test]'
ald-media-controller validate recipes/generic_al2o3.json
ald-media-controller simulate recipes/generic_al2o3.json --seed 42 --output build/direct
python -m pytest -v
```

Place the simulation-only and non-safety-rated boundary before the commands. Describe the generated direct-mode files and state that media commands arrive in later implementation phases.

- [ ] **Step 5: Run phase verification**

Run: `python -m pytest -v`

Expected: all core tests pass with zero failures.

Run: `python ald_media_controller.py validate recipes/generic_al2o3.json`

Expected: exit 0 and one JSON object containing a 64-character root hash.

Run: `python ald_media_controller.py simulate recipes/generic_al2o3.json --seed 42 --output /tmp/ald-core-acceptance`

Expected: exit 0 with `audit.jsonl`, `cycles.csv`, and `surface-final.json`; no `fault.json`.

- [ ] **Step 6: Commit the phase-one acceptance state**

```bash
git add recipes/generic_al2o3.json README.md tests/test_ald_media_controller.py
git commit -m "docs: add reproducible Al2O3 simulation example"
```
