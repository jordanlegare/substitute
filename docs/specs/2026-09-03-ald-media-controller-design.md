# ALD Media Controller and Atom-Event Simulator — Design Specification

**Date:** 2026-09-03  
**Status:** Proposed for user review  
**Scope:** Offline recipe compilation, dual direct/media execution, and deterministic simulation only

## 1. Purpose

Build a Python 3.10+ command-line program that compiles a compact atomic layer deposition (ALD) recipe, packages it as an HLS/fMP4 instruction stream, verifies the resulting media, and executes either the original recipe or the decoded media against a simulated ALD controller.

The system supports two equivalent operating modes:

1. **Direct mode:** execute canonical structured instructions.
2. **Executable-media mode:** recover those instructions from video frames, verify synchronized audio checksums and manifest metadata, then execute them through the same simulator.

The first chemistry model is generic two-precursor A/B ALD with an Al2O3 example mapping A to trimethylaluminum (TMA) and B to water. Machine control remains cycle-level; a stochastic surface model derives atom/site reaction events from each exposure.

## 2. Goals

- Represent repeated ALD cycles compactly without storing one command per atom or one command per cycle.
- Produce deterministic canonical instruction packets and a chained integrity digest.
- Carry executable packets in robust, machine-readable video frames.
- Carry corresponding sequence and checksum data in synchronized audio intervals.
- Require agreement among the frame, audio, playlist, and complete hash chain before media execution.
- Execute both direct and media-decoded instructions through one strict simulated controller.
- Generate reproducible site-reaction events and aggregate film-growth metrics from a recipe hash and seed.
- Fail closed on malformed recipes, corrupt media, integrity mismatches, invalid state transitions, or simulated interlock violations.
- Produce audit logs, cycle metrics, final surface state, and fault reports.

## 3. Non-goals

- Direct control of valves, mass-flow controllers, heaters, pumps, doors, robots, or precursor-delivery hardware.
- Replacement of PLC, hardwired, or dedicated safety interlocks.
- A molecular-dynamics, density-functional-theory, or quantum-chemistry simulator.
- Proof that an arbitrary codec or media-transcoding pipeline preserves an executable payload.
- Authentication by checksum alone. Integrity hashes detect corruption but not malicious replacement.
- Complete reproduction of a specific ALD vendor's recipe language or communications protocol.

## 4. Deliverables

The implementation phase will create:

- `ald_media_controller.py`: standalone CLI and internal modules/classes.
- `recipes/generic_al2o3.json`: generic A/B example with an Al2O3 material mapping.
- `tests/test_ald_media_controller.py`: deterministic unit and end-to-end tests.
- `README.md`: installation, safety boundary, command examples, format notes, and limitations.

Generated output from a compile/simulation run will include:

- `stream.m3u8`: HLS media playlist.
- One or more fMP4/CMAF segments containing video instruction frames and audio checksum blocks.
- `recipe.canonical.json`: canonical direct-mode representation.
- `bundle.json`: protocol version, recipe identifier, media metadata, root hash, and optional signature metadata.
- `audit.jsonl`: ordered validation, state transition, instruction, and fault records.
- `cycles.csv`: per-cycle process and film-growth metrics.
- `surface-final.json`: final aggregate surface state and reproducibility metadata.
- `fault.json`: emitted only when execution faults.

## 5. System Architecture

### 5.1 Components

#### RecipeCompiler

- Parses JSON without accepting duplicate object keys.
- Validates the recipe schema, declared units, command arguments, process limits, and total expanded cycle count.
- Resolves generic A/B precursor identifiers through recipe-local material metadata.
- Converts commands into a deterministic canonical representation.
- Preserves repetition as an `ALD_CYCLE` packet with a `repeat` count; it does not unroll repeated cycles into the media.
- Computes packet hashes and the recipe root hash.

#### MediaEncoder

- Produces a human-readable frame for each instruction packet.
- Embeds an error-corrected QR symbol containing the canonical packet and current chained hash.
- Repeats the frame for a three-second packet-media interval that is independent of simulated process duration.
- Encodes sequence number, chained hash, and CRC-32 into the synchronized audio interval using binary frequency-shift keying (BFSK).
- Uses FFmpeg to package the tracks into fragmented MP4/CMAF segments and an HLS playlist.
- Adds standard playlist timing/index data and packet metadata attributes without making the playlist the sole executable source.
- Decodes and verifies the completed temporary bundle before publishing it atomically to the requested output directory.

#### MediaDecoder

- Uses ffprobe/FFmpeg to validate and demultiplex the input media.
- Recovers canonical packets from QR frames.
- Recovers sequence/hash records from BFSK audio.
- Correlates records by presentation timestamp and sequence number.
- Recomputes every packet digest and the complete hash chain.
- Requires frame, audio, playlist, and bundle metadata to agree before returning executable packets.

#### SimulatedALDController

- Owns the chamber state machine, virtual actuators, sensors, safety envelope, and simulation clock.
- Receives verified packet objects rather than JSON, QR, audio, or playlist structures.
- Executes direct and media-decoded packets identically.
- Rejects unsupported commands, invalid transitions, expired packet deadlines, sequence discontinuities, and limit violations.
- Records deterministic state transitions and faults.

#### SurfaceModel

- Represents surface regions using counts of vacant, A-terminated, B-reacted, blocked, and defect sites.
- Applies seeded binomial reaction events at each precursor exposure.
- Produces exact aggregate counts and optionally a bounded sample of individual site events.
- Derives independent deterministic random streams from the recipe root hash, model version, user seed, cycle index, exposure, and region.
- Reports coverage, growth per cycle, thickness, utilization, saturation indicators, and defect estimates.

### 5.2 Data flow

```text
recipe.json -> RecipeCompiler -> canonical packets ---------------------+
                                |                                      |
                                +-> MediaEncoder -> HLS/fMP4 bundle     |
                                                     |                  |
                                                     v                  v
                                                MediaDecoder -> SafetyValidator
                                                                       |
                                                                       v
                                                        SimulatedALDController
                                                                       |
                                                                       v
                                                               SurfaceModel
```

Direct mode follows the upper path from canonical packets to the safety validator. Media mode follows the encoder/decoder path. Both paths must yield the same verified packet sequence before controller execution.

## 6. Recipe and Instruction Model

### 6.1 Recipe structure

A recipe contains:

- Protocol and schema version.
- Unique recipe identifier and descriptive metadata.
- Material mapping for generic precursor A and B.
- Initial chamber conditions.
- Global process envelope.
- Ordered instruction list.
- Surface-model parameters and simulation limits.
- Optional signing metadata.

Every numeric value has an explicit unit in its field name or an adjacent unit field. The initial implementation uses milliseconds, degrees Celsius, pascals, and standard cubic centimetres per minute where applicable.

### 6.2 Initial opcode set

| Opcode | Purpose | Principal arguments |
| --- | --- | --- |
| `CONFIGURE` | Load recipe-level limits and material mapping | limits, material identifiers |
| `SET_TEMPERATURE` | Set simulated chamber target | `target_c`, `ramp_c_per_min`, `tolerance_c` |
| `EVACUATE` | Reach base-pressure envelope | `target_pa`, `timeout_ms` |
| `STABILIZE` | Require stable temperature/pressure window | `duration_ms` |
| `ALD_CYCLE` | Execute a repeated A/purge/B/purge macro | precursor identifiers, four durations, optional flows, `repeat` |
| `MEASURE` | Capture virtual sensor/surface snapshot | measurement set |
| `SHUTDOWN` | Close process and enter safe simulated shutdown | ramp and vent policy |

The first version intentionally uses one high-level `ALD_CYCLE` macro rather than exposing arbitrary simultaneous valve commands. This makes non-overlap and minimum-purge guarantees structural.

### 6.3 Canonical packet

Each packet contains only validated fields:

```json
{
  "protocol": "ALD-MEDIA/1",
  "recipe_id": "generic-al2o3-001",
  "sequence": 4,
  "opcode": "ALD_CYCLE",
  "arguments": {
    "precursor_a": "A",
    "pulse_a_ms": 100,
    "purge_a_ms": 5000,
    "precursor_b": "B",
    "pulse_b_ms": 100,
    "purge_b_ms": 5000,
    "repeat": 500
  }
}
```

Canonical JSON uses UTF-8, sorted object keys, no insignificant whitespace, finite JSON numbers only, and schema-controlled strings. The implementation will define and test one serialization routine; hashes are never computed from user-provided raw JSON bytes.

## 7. Integrity and Media Protocol

### 7.1 Hash chain

Let `P_i` be the canonical UTF-8 packet bytes, `H_0` be 32 zero bytes, and `||` mean byte concatenation:

```text
H_i = SHA-256(ASCII("ALD1") || H_(i-1) || P_i)
```

The final value `H_n` is the recipe root hash. Domain separation with `ALD1` prevents accidental reuse with unrelated hash constructions.

### 7.2 Video record

Each instruction interval displays a static, high-contrast frame containing:

- Protocol version and recipe identifier.
- Sequence number and presentation interval.
- Opcode and human-readable arguments.
- Current packet hash.
- Error-corrected QR symbol containing the canonical packet plus current hash.

Executable data comes from the decoded QR symbol, not OCR. A canonical packet is limited to 800 bytes and uses QR error-correction level Q. The initial media profile uses a 1920x1080 H.264 frame with a three-second duration, a forced keyframe at every packet boundary, and a QR module size of at least eight encoded pixels. The completed encoded media—not the source image—is decoded during the compilation round trip. Unsupported, oversized, or undecodable symbols are fatal in executable-media mode.

### 7.3 Audio record

Each synchronized instruction interval carries a BFSK record:

```text
preamble | protocol version | sequence | packet hash | CRC-32
```

The initial profile uses 1200 Hz and 2400 Hz carriers, 1200 symbols per second, Manchester coding, mono 48 kHz audio, and AAC-LC at 128 kbit/s. A record contains a 64-bit alternating preamble, 8-bit protocol version, 32-bit sequence number, 256-bit hash, and 32-bit CRC. It is transmitted three times within the three-second packet-media interval, with guard time around each copy. At least two valid, matching copies are required. Audio verifies the corresponding video record; it does not carry an independent command.

### 7.4 Playlist and bundle metadata

The media playlist provides segment URIs, three-second presentation durations, discontinuity handling, and packet-boundary indexing. Simulated process time is carried inside the packet and is not inferred from media duration. The initial profile uses one packet per HLS fMP4 segment plus a shared initialization segment. Packet hash metadata is duplicated in standard extensibility fields where practical. `bundle.json` declares the protocol version, stream layout, FFmpeg parameters, ordered packet index, root hash, and optional signature metadata.

### 7.5 Verification gate

Before any media instruction reaches the simulator:

1. The playlist and all referenced segments must be present and structurally valid.
2. Video and audio timestamps must fall within configured synchronization tolerance.
3. The QR payload must parse under the declared protocol schema.
4. The packet's computed hash must equal the frame hash.
5. The audio sequence/hash record and CRC must validate and equal the frame record.
6. Playlist/bundle indexing metadata must equal the decoded track metadata.
7. Sequences must be contiguous, unique, ordered, and within limits.
8. The recomputed chain root must equal the declared root.
9. If a signature is declared as required, it must verify before execution.

Any failure aborts the complete media execution. The decoder never skips a damaged command or substitutes playlist metadata for an unreadable frame/audio record.

### 7.6 Security boundary

SHA-256 and CRC detect accidental corruption; they do not authenticate the recipe's author. The format reserves signature algorithm, signer identifier, public-key fingerprint, and signature fields. The simulator accepts unsigned bundles by default but clearly records signature status. Any later live adapter must require an authenticated, authorized recipe and a separate deployment security review.

## 8. Simulated Controller

### 8.1 States

```text
IDLE -> CONFIGURED -> HEATING -> EVACUATING -> READY
READY -> A_PULSE -> A_PURGE -> B_PULSE -> B_PURGE -> READY
READY -> COMPLETE -> SHUTDOWN -> IDLE
ANY ACTIVE STATE -> FAULT -> SHUTDOWN -> IDLE
```

The controller may remain in `READY` while repeating an `ALD_CYCLE`, but each internal pulse and purge transition is recorded with its cycle index.

### 8.2 Virtual process state

- Simulation time and packet/cycle counters.
- Chamber temperature, pressure, and stability duration.
- A and B valve states, inert-purge flow, pump state, and simulated exhaust availability.
- Precursor A and B partial pressures and residual concentrations.
- Surface coverage, thickness, reactive-site populations, defects, and utilization.
- Chamber-closed, vacuum-available, temperature-controller, and watchdog interlocks.

### 8.3 Interlocks and invariants

Before a precursor pulse, the simulator requires:

- Chamber closed and vacuum/exhaust systems available.
- Chamber pressure within the configured pulse envelope.
- Temperature stable within recipe tolerance and global limits.
- Pump/purge configuration appropriate for the current transition.
- Both precursor valves initially closed.
- No residual incompatible precursor above the configured threshold.
- Completion of the minimum purge interval after the other precursor.
- Packet sequence, deadline, hash chain, cycle count, dose, and total-runtime limits valid.

At all times:

- A and B precursor valves are mutually exclusive.
- Temperature, pressure, flow, dose, cycle, and runtime values cannot exceed global limits.
- Time is monotonic and transitions are explicitly logged.
- Invalid states and unsupported operations cannot be silently ignored.

### 8.4 Fault response

On a fault, the simulator:

1. Closes precursor A and B valves.
2. Stops recipe advancement.
3. Captures the current command, state, sensor values, interlocks, and hash-chain position.
4. Enters `FAULT` and emits a structured fault record.
5. Executes only the simulated safe-shutdown policy: inert purge when permitted, heater ramp-down, controlled pressure normalization, then `IDLE`.

The Python program is not a safety-rated controller. A future hardware adapter must command through a vendor-supported control interface and remain subordinate to independent PLC/hardwired safety functions.

## 9. Surface and Atom-Event Model

### 9.1 Representation

The surface is divided into configurable regions. Each region tracks integer populations of site states rather than Python objects for every atom. The initial states are:

- Vacant/reactive sites.
- A-terminated sites.
- Sites converted by the B half-reaction.
- Blocked or inaccessible sites.
- Defect sites.

### 9.2 Reaction events

For an eligible population `N`, the reacted population is sampled from `Binomial(N, p)`. The baseline exposure probabilities are:

```text
p_A = 1 - exp(-k_A * D_A)
p_B = 1 - exp(-k_B * D_B)
```

where `D_A` and `D_B` are simulated dose functions of pulse time, flow, chamber pressure, residual concentration, and region transport factor. Purge intervals reduce residual precursor concentrations exponentially. The reaction model exposes its coefficients in the recipe and records them in output metadata.

### 9.3 Determinism

Each reaction draw uses a stream derived from:

```text
recipe root hash | model version | user seed | cycle | half-reaction | region
```

This makes results independent of logging verbosity and bounded event sampling. The same implementation, inputs, and seed must reproduce aggregate results exactly on the supported NumPy version range.

### 9.4 Atom-event output

Aggregate population deltas are authoritative. Optional site-event samples are bounded by a configurable maximum and contain cycle, exposure, region, source state, destination state, and deterministic sample identifier. The simulator does not serialize every event unless a deliberately small surface makes that safe.

### 9.5 Compression model

Compression comes from procedural representation:

- A repeated process is stored once as `ALD_CYCLE(..., repeat=N)`.
- Atom/site outcomes are regenerated from the canonical recipe, model version, surface initialization, and seed.
- Aggregate region deltas use integer counts and optional delta/run-length encoding in reports.

The test suite reports the byte ratio between the compiled recipe bundle's canonical instruction data and a naive expanded JSONL representation of every cycle and site event. Media size is reported separately because codec/container overhead is not equivalent to instruction compression.

## 10. Command-line Interface

```text
python ald_media_controller.py validate RECIPE
python ald_media_controller.py compile RECIPE --output DIRECTORY
python ald_media_controller.py verify MANIFEST
python ald_media_controller.py simulate RECIPE --seed INTEGER --output DIRECTORY
python ald_media_controller.py simulate-media MANIFEST --seed INTEGER --output DIRECTORY
```

### 10.1 Command behavior

- `validate` parses, canonicalizes, checks limits, and reports the root hash without generating media.
- `compile` builds into a temporary sibling directory, runs full media round-trip verification, and atomically publishes the output directory only on success.
- `verify` performs all structural, QR, audio, synchronization, metadata, and hash-chain checks without simulation.
- `simulate` executes canonical packets directly.
- `simulate-media` verifies the complete bundle and executes the recovered packets.

Common options include `--log-level`, `--max-runtime`, `--require-signature`, and `--overwrite`. Existing output is never replaced unless `--overwrite` is explicit; replacement uses a validated temporary build followed by a controlled rename.

## 11. Dependencies

- Python 3.10 or newer.
- NumPy for reaction sampling and BFSK signal processing.
- Pillow for deterministic frame rendering.
- A QR encoder/decoder binding selected during implementation planning, with explicit version bounds.
- FFmpeg and ffprobe executables for media generation, probing, and extraction.
- Pytest for automated tests.

The program checks dependency versions and required codec/container capabilities before compilation. Missing or incompatible dependencies produce actionable diagnostics and no partial published bundle.

## 12. Error Handling and Auditability

Domain failures have distinct exception types and CLI exit codes:

- Recipe/schema failure.
- Process-envelope or limit failure.
- Media build/probe failure.
- Frame decode failure.
- Audio decode or CRC failure.
- Synchronization or metadata mismatch.
- Hash-chain or signature failure.
- Controller transition/interlock failure.
- Surface-model limit failure.
- Filesystem/output publication failure.

Every audit record contains protocol version, recipe identifier, monotonic record number, simulation timestamp, event type, controller state, packet sequence where applicable, and structured details. Fatal records include the last verified hash-chain position. Logs never claim an instruction executed before its transition completes.

## 13. Testing Strategy

### 13.1 Unit tests

- Reject duplicate JSON keys, unknown fields, ambiguous units, non-finite numbers, and out-of-range values.
- Prove canonical bytes and root hashes are deterministic.
- Verify hash-chain sensitivity to packet order, content, insertion, deletion, and duplication.
- Verify BFSK/CRC round trips and rejection outside timing/noise tolerances.
- Verify QR round trips at supported payload sizes and encoding parameters.
- Verify every permitted and forbidden controller transition.
- Verify valve mutual exclusion, purge minimums, and global limits.
- Verify reaction bounds, conservation of site counts, and seeded reproducibility.

### 13.2 End-to-end tests

- Compile, verify, and simulate the generic Al2O3 recipe.
- Assert direct and media modes recover identical canonical packet bytes, controller transitions, root hash, and final aggregate surface metrics.
- Corrupt video, audio, playlist metadata, segment order, timestamps, and root hash separately; require closed failure for each.
- Truncate the playlist or remove a segment; require closed failure.
- Trigger each simulated interlock class; require fault capture and safe shutdown.
- Run a high-repeat recipe and compare compact versus naively expanded instruction/event sizes.

### 13.3 Acceptance criteria

The first implementation is acceptable when:

1. All automated tests pass in a clean documented environment.
2. The sample recipe compiles into an HLS/fMP4 bundle that verifies after a fresh decode.
3. Direct and media simulations are equivalent for canonical packets, state transitions, and aggregate surface output.
4. Each defined corruption and interlock test fails closed with the documented error class.
5. A repeated recipe remains compact and the report clearly separates procedural instruction compression from media encoding size.
6. No code path can initiate external machine or network control.

## 14. Future Hardware Boundary

A live-machine phase is a separate project. It requires the exact ALD make/model, vendor recipe/API documentation, transport, authentication, command acknowledgements, timing guarantees, watchdog behavior, and documented safety architecture. The future adapter would consume already verified internal packets but would not reuse the simulator as a safety controller. Live operation would require independent review, staged hardware-in-the-loop testing, and explicit user authorization.
