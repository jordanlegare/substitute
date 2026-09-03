# Recipe Authoring Guide

This guide explains how to write JSON recipes for **Substitute**, the offline ALD recipe compiler and deterministic simulator.

> **Simulation-only boundary**
>
> Recipe fields such as precursor labels, pressure, temperature, pulse time, purge time, and flow are inputs to a virtual controller and aggregate surface model. They are **not** operating instructions for real deposition equipment, chemical-handling guidance, or production process parameters.

## Start here

A Substitute recipe is a UTF-8 JSON object using protocol `ALD-MEDIA/1`.

The safest authoring loop is:

```bash
ald-media-controller validate my-recipe.json
ald-media-controller simulate my-recipe.json --seed 42 --output build/my-run
```

`validate` checks JSON structure, supported instructions, process-limit relationships, cycle expansion, runtime estimates, and canonical packet size. `simulate` additionally runs the controller state machine, interlocks, residual checks, surface-model configuration, and deterministic surface reactions.

That distinction matters: a recipe can be structurally valid yet still fail closed during simulation if its instruction order or execution-time configuration is invalid.

## Small runnable recipe

The following is a compact, runnable generic A/B simulation recipe. It uses the current default surface model by leaving `surface` empty.

Save it as `recipes/my-first-recipe.json`:

```json
{
  "protocol": "ALD-MEDIA/1",
  "recipe_id": "my-first-recipe",
  "metadata": {
    "purpose": "generic A/B simulator example"
  },
  "precursors": {
    "A": {"label": "A-sim"},
    "B": {"label": "B-sim"}
  },
  "initial_conditions": {
    "temperature_c": 25.0,
    "pressure_pa": 101325.0
  },
  "limits": {
    "min_purge_ms": 1000,
    "max_temperature_c": 200.0,
    "max_pressure_pa": 200000.0,
    "max_cycles": 10,
    "max_runtime_ms": 1000000,
    "max_residual_fraction": 0.01
  },
  "surface": {},
  "instructions": [
    {"opcode": "CONFIGURE", "arguments": {}},
    {
      "opcode": "SET_TEMPERATURE",
      "arguments": {
        "target_c": 100.0,
        "ramp_c_per_min": 20.0,
        "tolerance_c": 1.0
      }
    },
    {
      "opcode": "EVACUATE",
      "arguments": {
        "target_pa": 100.0,
        "timeout_ms": 100000
      }
    },
    {"opcode": "STABILIZE", "arguments": {"duration_ms": 1000}},
    {
      "opcode": "ALD_CYCLE",
      "arguments": {
        "precursor_a": "A",
        "pulse_a_ms": 100,
        "purge_a_ms": 5000,
        "precursor_b": "B",
        "pulse_b_ms": 100,
        "purge_b_ms": 5000,
        "repeat": 1
      }
    },
    {
      "opcode": "MEASURE",
      "arguments": {
        "measurements": ["thickness_nm", "coverage", "defect_fraction"]
      }
    },
    {
      "opcode": "SHUTDOWN",
      "arguments": {
        "heater_ramp_c_per_min": 20.0,
        "vent_target_pa": 101325.0
      }
    }
  ]
}
```

Validate it:

```bash
ald-media-controller validate recipes/my-first-recipe.json
```

Then run it:

```bash
ald-media-controller simulate \
  recipes/my-first-recipe.json \
  --seed 42 \
  --output build/my-first-run
```

## Required top-level structure

The recipe object has an **exact** top-level schema. All eight keys below are required; unexpected top-level keys are rejected.

| Field | Type | Meaning |
| --- | --- | --- |
| `protocol` | string | Must be exactly `ALD-MEDIA/1`. |
| `recipe_id` | non-empty string | Stable identifier copied into every compiled instruction packet. |
| `metadata` | object | User metadata containing normal JSON values. It does not directly drive the controller. |
| `precursors` | object | Must contain exactly precursor slots `A` and `B`. |
| `initial_conditions` | object | Initial virtual-chamber temperature and pressure. |
| `limits` | object | Author-supplied safety/complexity envelope for validation and simulation. |
| `surface` | object | Surface-model configuration. An empty object uses current defaults. |
| `instructions` | non-empty array | Ordered instruction stream compiled into packets. |

The JSON loader also rejects:

- duplicate object keys;
- malformed UTF-8 or malformed JSON;
- non-finite numeric constants such as `NaN`, `Infinity`, or `-Infinity`.

## `protocol`

Use:

```json
"protocol": "ALD-MEDIA/1"
```

Other protocol values are rejected.

## `recipe_id`

`recipe_id` must be a non-empty string:

```json
"recipe_id": "experiment-001"
```

It is included in every canonical packet, so a very long identifier also consumes packet bytes. The absolute canonical packet limit is 800 bytes.

## `metadata`

`metadata` can contain normal JSON values, nested arrays, and nested objects:

```json
"metadata": {
  "material": "generic-film",
  "owner": "simulation-team",
  "tags": ["demo", "deterministic"]
}
```

Metadata must contain finite JSON values. It is preserved in the canonical recipe but is not an instruction opcode.

## `precursors`

The current recipe protocol requires exactly two declared slots, `A` and `B`:

```json
"precursors": {
  "A": {"label": "A-sim"},
  "B": {"label": "B-sim"}
}
```

Each precursor object must contain exactly one key, `label`, and the label must be a non-empty string.

`ALD_CYCLE` must reference the declared `A` and `B` slots as distinct precursors.

Precursor labels are descriptive simulator metadata. They do not authorize or describe real chemical handling.

## `initial_conditions`

The initial-condition object has exactly two fields:

```json
"initial_conditions": {
  "temperature_c": 25.0,
  "pressure_pa": 101325.0
}
```

Both values must be finite numbers. The initial temperature must not exceed `limits.max_temperature_c`, and the initial pressure must not exceed `limits.max_pressure_pa`.

These values initialize the **virtual** chamber.

## `limits`

Required limit fields:

| Field | Constraint | Effect |
| --- | --- | --- |
| `min_purge_ms` | integer ≥ 1 | Each A/B purge in `ALD_CYCLE` must be at least this long. |
| `max_temperature_c` | finite number > 0 | Caps initial and requested target temperatures. |
| `max_pressure_pa` | finite number > 0 | Caps initial, evacuation target, vent target, and execution pressure checks. |
| `max_cycles` | integer ≥ 1 | Caps the sum of all expanded `ALD_CYCLE.repeat` values. |
| `max_runtime_ms` | integer ≥ 1 | Caps expanded recipe runtime and is also enforced as simulation time advances. |
| `max_residual_fraction` | finite number from 0 through 1 | Execution-time threshold for incompatible simulated precursor residual. |

Optional field:

| Field | Constraint | Default |
| --- | --- | --- |
| `max_packet_bytes` | integer from 1 through 800 | `800` |

Example:

```json
"limits": {
  "min_purge_ms": 1000,
  "max_temperature_c": 300.0,
  "max_pressure_pa": 200000.0,
  "max_cycles": 1000,
  "max_runtime_ms": 3600000,
  "max_residual_fraction": 0.01,
  "max_packet_bytes": 800
}
```

### Runtime accounting nuance

During `validate`, the expanded runtime estimate includes:

- every `EVACUATE.timeout_ms`;
- every `STABILIZE.duration_ms`;
- every expanded A pulse, A purge, B pulse, and B purge.

During actual simulation, the controller also advances time for the temperature ramp. That means a recipe can pass the compile-time expanded-runtime check but still hit `RUNTIME_LIMIT_EXCEEDED` if the execution-time ramp pushes simulation time past `max_runtime_ms`.

The fail-closed shutdown path is allowed to complete its safety shutdown even after a runtime fault.

## `surface`

`surface` is intentionally an extensible JSON object. The current `site-binomial/1` simulator recognizes the following fields.

| Field | Current default | Constraint / role |
| --- | ---: | --- |
| `model_version` | `"site-binomial/1"` | Non-empty string used in deterministic RNG domain separation. |
| `regions` | `1` | Positive integer number of aggregate surface regions. |
| `sites_per_region` | `1000` | Positive integer number of modeled sites per region. |
| `transport_factors` | one `1.0` per region | Array with exactly one finite non-negative number per region. |
| `blocked_fraction` | `0.0` | Finite non-negative fraction. |
| `defect_fraction` | `0.0` | Finite non-negative fraction. Together with blocked fraction, must sum to at most 1. |
| `k_a` | `1.5` | Finite non-negative A half-reaction rate scalar. |
| `k_b` | `1.4` | Finite non-negative B half-reaction rate scalar. |
| `growth_nm_per_reaction_fraction` | `0.11` | Finite non-negative simulated growth scaling factor. |
| `purge_half_life_ms` | `800` | Positive integer used to decay simulated residuals during purges. |
| `max_event_samples` | `0` | Non-negative integer cap for bounded display/audit event samples. It does not change aggregate reaction outcomes. |

Example:

```json
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
}
```

### Extensible does not mean executable

Recipe validation accepts additional JSON keys inside `surface`, but the current simulator ignores keys it does not recognize. Prefer the documented keys above. Unknown keys should be treated as inert metadata, not as a stable extension mechanism; a future protocol/model version may assign them meaning or tighten validation.

Recognized surface fields are checked when the simulator initializes the surface model. Therefore some malformed surface configurations can pass `validate` and then fail closed during `simulate` as `INVALID_SURFACE_CONFIG`.

## Instruction objects

Every entry in `instructions` has exactly this shape:

```json
{
  "opcode": "OPCODE_NAME",
  "arguments": {}
}
```

Unexpected keys in the instruction object are rejected.

The currently supported opcodes are:

1. `CONFIGURE`
2. `SET_TEMPERATURE`
3. `EVACUATE`
4. `STABILIZE`
5. `ALD_CYCLE`
6. `MEASURE`
7. `SHUTDOWN`

## Controller order: validation vs. execution

The simulator begins in `IDLE`. Its normal executable path is:

```text
IDLE
  ↓ CONFIGURE
CONFIGURED
  ↓ SET_TEMPERATURE
HEATING
  ↓ EVACUATE
EVACUATING
  ↓ STABILIZE
READY
  ↓ ALD_CYCLE (returns to READY)
READY
  ↓ MEASURE (stays READY)
READY
  ↓ SHUTDOWN
COMPLETE → SHUTDOWN → IDLE
```

`validate` checks each instruction's schema but does **not** execute this state machine. For example, the following can be structurally valid yet fail during simulation:

```json
[
  {"opcode": "CONFIGURE", "arguments": {}},
  {"opcode": "ALD_CYCLE", "arguments": {"precursor_a":"A","pulse_a_ms":100,"purge_a_ms":5000,"precursor_b":"B","pulse_b_ms":100,"purge_b_ms":5000,"repeat":1}}
]
```

After `CONFIGURE`, the controller is `CONFIGURED`, not `READY`, so `ALD_CYCLE` would cause an `INVALID_TRANSITION` fault.

For ordinary runnable recipes:

- start with `CONFIGURE`;
- follow with `SET_TEMPERATURE`;
- then `EVACUATE`;
- then `STABILIZE` to enter `READY`;
- from `READY`, use one or more `ALD_CYCLE` and/or `MEASURE` instructions;
- finish with `SHUTDOWN`;
- do not place instructions after `SHUTDOWN`.

## `CONFIGURE`

Arguments must be an empty object:

```json
{"opcode": "CONFIGURE", "arguments": {}}
```

It is the normal first instruction and moves the controller from `IDLE` to `CONFIGURED`.

## `SET_TEMPERATURE`

Required arguments:

```json
{
  "opcode": "SET_TEMPERATURE",
  "arguments": {
    "target_c": 200.0,
    "ramp_c_per_min": 20.0,
    "tolerance_c": 1.0
  }
}
```

Constraints:

- `target_c` must be finite and no greater than `max_temperature_c`;
- `ramp_c_per_min` must be finite and greater than 0;
- `tolerance_c` must be finite and at least 0.

The simulator advances virtual time according to the temperature change and ramp value.

## `EVACUATE`

Required arguments:

```json
{
  "opcode": "EVACUATE",
  "arguments": {
    "target_pa": 100.0,
    "timeout_ms": 900000
  }
}
```

Constraints:

- `target_pa` must be finite, at least 0, and no greater than `max_pressure_pa`;
- `timeout_ms` must be an integer ≥ 1.

In the current simulator, `timeout_ms` is added to virtual simulation time and is included in validation-time runtime accounting.

## `STABILIZE`

Required arguments:

```json
{
  "opcode": "STABILIZE",
  "arguments": {
    "duration_ms": 60000
  }
}
```

`duration_ms` must be an integer ≥ 1. The duration is included in runtime accounting. `STABILIZE` moves the controller from `EVACUATING` to `READY`.

## `ALD_CYCLE`

Required arguments:

```json
{
  "opcode": "ALD_CYCLE",
  "arguments": {
    "precursor_a": "A",
    "pulse_a_ms": 100,
    "purge_a_ms": 5000,
    "precursor_b": "B",
    "pulse_b_ms": 100,
    "purge_b_ms": 5000,
    "repeat": 100
  }
}
```

Optional arguments:

```json
"flow_a_sccm": 50.0,
"flow_b_sccm": 50.0
```

Constraints:

- `precursor_a` and `precursor_b` must reference distinct declared precursor slots;
- pulse values must be integers ≥ 1;
- purge values must be integers ≥ 1 and each must be at least `limits.min_purge_ms`;
- `repeat` must be an integer ≥ 1;
- optional flows must be finite and non-negative;
- the sum of every expanded `repeat` across the recipe must not exceed `max_cycles`;
- expanded pulse/purge duration must fit the runtime envelope.

### Compact repeat behavior

`repeat` is deliberately kept inside one compact packet. A recipe with:

```json
"repeat": 100
```

creates one `ALD_CYCLE` instruction packet, not 100 duplicate packets. The simulator expands those cycles procedurally during execution.

### Current simulation dose scalar

For the aggregate surface model, the current simulator computes a generic dose scalar as:

```text
dose = flow × pulse_ms / 100000
```

If a flow field is omitted, the simulator uses `1.0` for that flow term.

This is a model scalar for the offline simulator; it is not a calibrated physical dosing equation or equipment setpoint recommendation.

### Purge minimum vs. residual safety

Passing `min_purge_ms` is only a schema/limit requirement. At execution time the controller also checks incompatible simulated residual against `max_residual_fraction` before each precursor exposure.

Residual decays according to the surface model's `purge_half_life_ms`. A recipe can therefore satisfy the minimum purge duration yet still fail closed with `INCOMPATIBLE_RESIDUAL` if its simulated residual remains above the configured threshold.

## `MEASURE`

Required argument: a non-empty list of unique supported measurement names.

```json
{
  "opcode": "MEASURE",
  "arguments": {
    "measurements": [
      "thickness_nm",
      "coverage",
      "defect_fraction"
    ]
  }
}
```

Supported names are exactly:

- `thickness_nm`
- `coverage`
- `defect_fraction`

Duplicates and unknown names are rejected.

`MEASURE` requires the controller to be in `READY` and leaves it in `READY`.

## `SHUTDOWN`

Required arguments:

```json
{
  "opcode": "SHUTDOWN",
  "arguments": {
    "heater_ramp_c_per_min": 20.0,
    "vent_target_pa": 101325.0
  }
}
```

Constraints:

- `heater_ramp_c_per_min` must be finite and greater than 0;
- `vent_target_pa` must be finite, at least 0, and no greater than `max_pressure_pa`.

A normal `SHUTDOWN` starts from `READY`, transitions through `COMPLETE` and `SHUTDOWN`, and returns the simulator to `IDLE`.

A recipe that reaches the end without returning to `IDLE` fails closed as `RECIPE_DID_NOT_SHUTDOWN`.

## Full checked-in example

The repository's acceptance recipe is `recipes/generic_al2o3.json`:

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
      "precursor_a": "A",
      "pulse_a_ms": 100,
      "flow_a_sccm": 50.0,
      "purge_a_ms": 5000,
      "precursor_b": "B",
      "pulse_b_ms": 100,
      "flow_b_sccm": 50.0,
      "purge_b_ms": 5000,
      "repeat": 100
    }},
    {"opcode": "MEASURE", "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]}},
    {"opcode": "SHUTDOWN", "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0}}
  ]
}
```

### What this example demonstrates

- **7 top-level instructions** compile to 7 compact chained packets.
- The single `ALD_CYCLE` packet represents **100 simulated cycles** through its `repeat` field.
- Four regions × 250,000 sites creates an aggregate simulated surface of **1,000,000 sites**.
- `transport_factors` slightly reduce modeled exposure at the first and last region.
- `max_event_samples` bounds display/audit samples; it does not materialize every modeled reaction as an event object.
- `MEASURE` requests all three currently supported measurement names.
- The final `SHUTDOWN` returns the controller to `IDLE`.

The real chemistry names in this demonstration are labels for the generic simulation mapping only.

## Common authoring errors

### Unexpected top-level field

This is rejected:

```json
{
  "protocol": "ALD-MEDIA/1",
  "recipe_id": "bad",
  "notes": "extra top-level field"
}
```

The top-level schema is exact. Put descriptive data inside `metadata` instead.

### Duplicate JSON key

This is rejected during JSON loading:

```json
{"recipe_id": "one", "recipe_id": "two"}
```

### Missing required limit

All limit keys except `max_packet_bytes` are required. If you do not want a tighter packet cap, simply omit `max_packet_bytes`; it defaults to 800.

### Purge below minimum

If:

```json
"min_purge_ms": 1000
```

then this is rejected:

```json
"purge_a_ms": 500
```

### Too many expanded cycles

If `max_cycles` is 100, then two `ALD_CYCLE` instructions with `repeat: 60` each are rejected because the expanded total is 120.

### Runtime estimate exceeds limit

The validator accumulates evacuation timeout, stabilization duration, and expanded cycle pulse/purge durations. If that sum exceeds `max_runtime_ms`, validation fails.

### Target exceeds configured maximum

This fails when `max_temperature_c` is 200:

```json
"target_c": 250.0
```

### Duplicate or unsupported measurement

These are rejected:

```json
"measurements": ["coverage", "coverage"]
```

```json
"measurements": ["mass_g"]
```

### Valid schema, invalid instruction order

`validate` can succeed on individually valid opcodes that are ordered incorrectly. Always run a deterministic simulation after validation to exercise controller transitions.

### Invalid recognized surface field

Because `surface` is extensible JSON at recipe-validation time, a value such as:

```json
"regions": 0
```

can survive recipe parsing but fail when the simulator initializes the current surface model. `simulate` will fail closed with `INVALID_SURFACE_CONFIG`.

### Canonical packet too large

Each instruction becomes one canonical packet containing protocol, recipe ID, sequence, opcode, and arguments. The hard ceiling is 800 bytes per packet, and `limits.max_packet_bytes` can set a smaller ceiling.

Large instruction argument payloads or an unusually long `recipe_id` can therefore trigger a packet-size error.

## Recommended authoring workflow

1. Copy the small runnable example or `recipes/generic_al2o3.json`.
2. Give the recipe a new non-empty `recipe_id`.
3. Keep `protocol` at `ALD-MEDIA/1`.
4. Put descriptive information in `metadata`.
5. Set explicit limits before editing the instruction stream.
6. Start with the normal controller sequence through `STABILIZE`.
7. Add `ALD_CYCLE` / `MEASURE` operations while the controller is `READY`.
8. End with `SHUTDOWN`.
9. Run `validate`.
10. Run `simulate` with an explicit seed and inspect `fault.json` if present.
11. Only after the direct simulation behaves as intended, compile the recipe into media if you need the QR/BFSK/HLS verification path.

## Validate and inspect failures

Validate:

```bash
ald-media-controller validate recipes/my-recipe.json
```

For more diagnostic detail:

```bash
ald-media-controller validate recipes/my-recipe.json --log-level DEBUG
```

CLI failures are emitted as structured JSON on stderr. Important error categories include recipe/schema errors, limit errors, controller faults, surface-model errors, media errors, and integrity errors.

A direct simulation writes `fault.json` when the virtual controller fails closed:

```bash
ald-media-controller simulate \
  recipes/my-recipe.json \
  --seed 42 \
  --output build/my-run
```

## Compile your recipe into verified media

After direct validation/simulation, build the HLS/fMP4 representation:

```bash
ald-media-controller compile \
  recipes/my-recipe.json \
  --output build/my-bundle
```

Verify it:

```bash
ald-media-controller verify build/my-bundle/stream.m3u8
```

And execute the verified media path:

```bash
ald-media-controller simulate-media \
  build/my-bundle/stream.m3u8 \
  --seed 42 \
  --output build/my-media-run
```

For signed bundles and caller-trusted Ed25519 verification, see the **Signed bundles** section in the project `README.md`.

## Determinism

For a fixed:

- canonical recipe;
- compiled packet/root hash;
- surface-model version;
- user seed;
- controller implementation;

the simulation is designed to be deterministic.

Changing recipe content changes the canonical packet stream and/or the recipe binding used by the media bundle. Changing the seed changes the deterministic surface-reaction stream while leaving the recipe itself unchanged.

## Source of truth

This guide describes the current `main` implementation. The checked-in executable references are:

- `recipes/generic_al2o3.json` — accepted demonstration recipe;
- `ald_core.py` — recipe validation, packet compilation, surface model, and controller state machine;
- `ald_media_cli.py` — user-facing CLI boundary;
- `docs/specs/2026-09-03-ald-media-controller-design.md` — protocol/system design.

When changing the recipe protocol itself, update the implementation, tests, design specification, and this guide together.
