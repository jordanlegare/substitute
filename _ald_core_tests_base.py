import hashlib
import json
import math
import os
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from ald_media_controller import (
    ControllerFault,
    ControllerState,
    CycleMetric,
    HashedPacket,
    ExitCode,
    Interlocks,
    Packet,
    RecipeError,
    RecipeLimitError,
    SurfaceConfig,
    SurfaceModel,
    SurfaceModelError,
    SimulatedALDController,
    canonical_packet_bytes,
    compile_recipe,
    decay_residual,
    load_recipe,
    main,
    OutputError,
    reaction_probability,
    reaction_rng,
    validate_recipe,
    publish_reports,
    replace_output_directory,
    write_cycle_csv,
)


class EqualityBytes(bytes):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


class EqualityTuple(tuple):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


class FlakyTuple(tuple):
    """A hostile tuple subclass that changes contents on each iteration."""

    def __new__(cls, first, second):
        instance = super().__new__(cls, first)
        instance._second = second
        return instance

    def __iter__(self):
        if not getattr(self, "_iterated", False):
            self._iterated = True
            return iter(tuple.__iter__(self))
        return iter(self._second)


class MaliciousHashedPacket(HashedPacket):
    pass


class MaliciousPacket(Packet):
    pass


@pytest.fixture
def valid_recipe_dict():
    return {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": "generic-al2o3-001",
        "metadata": {
            "material": "Al2O3",
            "simulation_notice": "Simulation-only precursor labels.",
        },
        "precursors": {
            "A": {"label": "trimethylaluminum"},
            "B": {"label": "water"},
        },
        "initial_conditions": {"temperature_c": 25.0, "pressure_pa": 101325.0},
        "limits": {
            "min_purge_ms": 1000,
            "max_temperature_c": 300.0,
            "max_pressure_pa": 200000.0,
            "max_cycles": 1000,
            "max_runtime_ms": 3_600_000,
            "max_residual_fraction": 0.01,
            "max_packet_bytes": 800,
        },
        "surface": {"model_version": "site-binomial/1", "regions": 4},
        "instructions": [
            {"opcode": "CONFIGURE", "arguments": {}},
            {
                "opcode": "SET_TEMPERATURE",
                "arguments": {
                    "target_c": 200.0,
                    "ramp_c_per_min": 20.0,
                    "tolerance_c": 1.0,
                },
            },
            {"opcode": "EVACUATE", "arguments": {"target_pa": 100.0, "timeout_ms": 900_000}},
            {"opcode": "STABILIZE", "arguments": {"duration_ms": 60_000}},
            {
                "opcode": "ALD_CYCLE",
                "arguments": {
                    "precursor_a": "A",
                    "pulse_a_ms": 100,
                    "flow_a_sccm": 50.0,
                    "purge_a_ms": 5000,
                    "precursor_b": "B",
                    "pulse_b_ms": 100,
                    "flow_b_sccm": 50.0,
                    "purge_b_ms": 5000,
                    "repeat": 100,
                },
            },
            {
                "opcode": "MEASURE",
                "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]},
            },
            {
                "opcode": "SHUTDOWN",
                "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0},
            },
        ],
    }


@pytest.fixture
def surface_config():
    return SurfaceConfig(
        model_version="site-binomial/1",
        regions=3,
        sites_per_region=1_000,
        transport_factors=(0.8, 1.0, 0.9),
        blocked_fraction=0.1,
        defect_fraction=0.02,
        k_a=1.5,
        k_b=1.4,
        growth_nm_per_reaction_fraction=0.11,
        purge_half_life_ms=800,
    )


@pytest.fixture
def compiled_recipe(valid_recipe_dict):
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 2
    return compile_recipe(validate_recipe(valid_recipe_dict))


def test_controller_executes_each_cycle_with_ordered_monotonic_audit(compiled_recipe):
    """Skipping a half-cycle or moving simulated time backward must be observable."""
    result = SimulatedALDController().execute(compiled_recipe, seed=42)

    assert result.fault is None
    assert result.final_state is ControllerState.IDLE
    assert [metric.cycle for metric in result.cycles] == [1, 2]
    assert [event.record_number for event in result.audit] == list(range(1, len(result.audit) + 1))
    assert [event.simulation_time_ms for event in result.audit] == sorted(
        event.simulation_time_ms for event in result.audit
    )
    assert [event.state for event in result.audit].count(ControllerState.A_PULSE) == 2
    assert [event.state for event in result.audit].count(ControllerState.B_PURGE) == 2


def test_a_and_b_valves_never_overlap(compiled_recipe):
    """Opening both precursor valves during a pulse would violate the process envelope."""
    result = SimulatedALDController().execute(compiled_recipe, seed=42)

    assert all(not (event.valve_a_open and event.valve_b_open) for event in result.audit)


def test_short_purge_faults_closed(valid_recipe_dict):
    """Relaxing compile-time purge validation would permit an unsafe cycle macro."""
    valid_recipe_dict["instructions"][4]["arguments"]["purge_a_ms"] = 1

    with pytest.raises(RecipeLimitError, match="purge_a_ms below min_purge_ms"):
        compile_recipe(validate_recipe(valid_recipe_dict))


def test_interlock_loss_closes_valves_snapshots_provenance_and_returns_idle(compiled_recipe):
    """Continuing after an unavailable vacuum would advance an unsafe recipe."""
    controller = SimulatedALDController(interlocks=Interlocks(vacuum_available=False))
    result = controller.execute(compiled_recipe, seed=42)

    assert result.fault is not None
    assert result.fault.code == "VACUUM_UNAVAILABLE"
    assert result.fault.packet_sequence == 2
    assert result.fault.state is ControllerState.EVACUATING
    assert result.fault.last_verified_digest == compiled_recipe.packets[1].digest
    assert result.fault.interlocks == Interlocks(vacuum_available=False)
    assert result.final_state is ControllerState.IDLE
    assert result.chamber.valve_a_open is False
    assert result.chamber.valve_b_open is False
    assert result.fault.chamber.valve_a_open is False
    assert result.fault.chamber.valve_b_open is False
    assert result.cycles == ()
    assert {event.packet_sequence for event in result.audit} <= {0, 1, 2}
    assert result.audit[-1].state is ControllerState.IDLE


def test_transition_rejects_states_outside_the_allowed_table():
    """Bypassing the central transition table would allow unsafe state jumps."""
    controller = SimulatedALDController()

    with pytest.raises(ControllerFault, match="INVALID_TRANSITION"):
        controller.transition(ControllerState.READY)


def test_audit_events_preserve_packet_and_digest_provenance(compiled_recipe):
    """Dropping packet digests from audit records would prevent deterministic replay reports."""
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    configured = next(event for event in result.audit if event.state is ControllerState.CONFIGURED)

    assert configured.packet_sequence == 0
    assert configured.details["packet_digest"] == compiled_recipe.packets[0].digest.hex()
    assert configured.details["last_verified_digest"] == bytes(32).hex()


def test_runtime_fault_still_runs_safe_shutdown_to_idle(valid_recipe_dict):
    """Applying the process runtime cap to safe shutdown would strand the controller active."""
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 2
    valid_recipe_dict["limits"]["max_runtime_ms"] = 980_400
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "RUNTIME_LIMIT_EXCEEDED"
    assert result.final_state is ControllerState.IDLE
    assert result.chamber.valve_a_open is False
    assert result.chamber.valve_b_open is False


def test_corrupt_first_packet_digest_faults_closed_from_idle(compiled_recipe):
    """A first-packet integrity fault must still produce a fail-closed result."""
    first = replace(compiled_recipe.packets[0], digest=b"x" * 32)
    compiled = replace(compiled_recipe, packets=(first,) + compiled_recipe.packets[1:])

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "PACKET_DIGEST_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.chamber.valve_a_open is False
    assert result.chamber.valve_b_open is False
    assert result.audit[-1].state is ControllerState.IDLE


def test_packet_after_shutdown_faults_closed_without_resuming(valid_recipe_dict):
    """A schema-valid packet after shutdown must not resume an idle recipe."""
    valid_recipe_dict["instructions"].append({"opcode": "CONFIGURE", "arguments": {}})
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "INVALID_TRANSITION"
    assert result.fault.packet_sequence == 7
    assert result.final_state is ControllerState.IDLE
    assert result.cycles[-1].cycle == 100


def test_invalid_surface_config_faults_closed_inside_execution_boundary(valid_recipe_dict):
    """Recipe-derived surface errors must become immutable safe results."""
    valid_recipe_dict["surface"]["regions"] = -1
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "INVALID_SURFACE_CONFIG"
    assert result.fault.last_verified_digest == compiled.root_hash
    assert result.fault.packet_sequence == 0
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_empty_compiled_packet_tuple_faults_against_recipe_stream(compiled_recipe):
    """A non-empty recipe cannot be replaced by an empty successful stream."""
    compiled = replace(compiled_recipe, packets=(), root_hash=bytes(32))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_recomputed_truncated_stream_cannot_replace_recipe_packets(compiled_recipe):
    """A valid hash chain for a different packet stream must still be rejected."""
    truncated_recipe = replace(
        compiled_recipe.recipe,
        instructions=compiled_recipe.recipe.instructions[:1],
    )
    truncated = compile_recipe(truncated_recipe)
    compiled = replace(
        compiled_recipe,
        packets=truncated.packets,
        root_hash=truncated.root_hash,
    )

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_recomputed_replaced_stream_cannot_replace_recipe_packets(compiled_recipe):
    """A recomputed valid chain with a replaced instruction must be rejected."""
    instructions = list(compiled_recipe.recipe.instructions)
    instructions[0] = {
        "opcode": "MEASURE",
        "arguments": {"measurements": ("coverage",)},
    }
    replaced_recipe = replace(compiled_recipe.recipe, instructions=tuple(instructions))
    replaced = compile_recipe(replaced_recipe)
    compiled = replace(
        compiled_recipe,
        packets=replaced.packets,
        root_hash=replaced.root_hash,
    )

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_string_compiled_packet_element_faults_closed(compiled_recipe):
    """A non-packet tuple element must not escape through fault provenance."""
    compiled = replace(compiled_recipe, packets=("malformed",), root_hash=bytes(32))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_malformed_nested_packet_shape_faults_closed(compiled_recipe):
    """A malformed HashedPacket payload must be rejected before provenance use."""
    malformed = replace(compiled_recipe.packets[0], packet=object())
    compiled = replace(compiled_recipe, packets=(malformed,) + compiled_recipe.packets[1:])

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_packet_subclass_with_missing_shape_faults_closed_without_provenance(compiled_recipe):
    """A Packet forged with object.__new__ cannot poison fault provenance."""
    malformed_packet = object.__new__(Packet)
    malformed = replace(compiled_recipe.packets[0], packet=malformed_packet)
    compiled = replace(compiled_recipe, packets=(malformed,) + compiled_recipe.packets[1:])

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.fault.packet_sequence is None
    assert result.surface.total_sites == 0


def test_malicious_packet_and_hashed_packet_subclasses_are_not_trusted(compiled_recipe):
    """Subclass overrides cannot enter execution or audit provenance."""
    packet = compiled_recipe.packets[0].packet
    forged_packet = object.__new__(MaliciousPacket)
    for field in ("protocol", "recipe_id", "sequence", "opcode", "arguments"):
        object.__setattr__(forged_packet, field, getattr(packet, field))
    forged_hashed = object.__new__(MaliciousHashedPacket)
    for field in ("packet", "canonical_bytes", "previous_digest", "digest"):
        object.__setattr__(forged_hashed, field, getattr(compiled_recipe.packets[0], field))
    compiled = replace(
        compiled_recipe,
        packets=(forged_hashed,) + compiled_recipe.packets[1:],
    )

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.fault.packet_sequence is None
    assert result.surface.total_sites == 0


def test_packet_container_and_root_require_exact_bytes_and_tuple(compiled_recipe):
    """Equality-overriding containers cannot bypass stream/root binding."""
    with_container = replace(compiled_recipe, packets=EqualityTuple(compiled_recipe.packets))
    container_result = SimulatedALDController().execute(with_container, seed=42)
    assert container_result.fault is not None
    assert container_result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert container_result.surface.total_sites == 0

    with_root = replace(compiled_recipe, root_hash=EqualityBytes(compiled_recipe.root_hash))
    root_result = SimulatedALDController().execute(with_root, seed=42)
    assert root_result.fault is not None
    assert root_result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert root_result.surface.total_sites == 0


def test_packet_digest_and_argument_tuple_require_exact_primitives(compiled_recipe):
    """Nested equality-overriding bytes/tuples cannot pass shape validation."""
    digest_packet = replace(
        compiled_recipe.packets[0],
        digest=EqualityBytes(compiled_recipe.packets[0].digest),
    )
    digest_compiled = replace(
        compiled_recipe,
        packets=(digest_packet,) + compiled_recipe.packets[1:],
    )
    digest_result = SimulatedALDController().execute(digest_compiled, seed=42)
    assert digest_result.fault is not None
    assert digest_result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert digest_result.surface.total_sites == 0

    packet = compiled_recipe.packets[5].packet
    forged_packet = replace(packet)
    object.__setattr__(
        forged_packet,
        "arguments",
        MappingProxyType({"measurements": EqualityTuple(("thickness_nm",))}),
    )
    forged_hashed = replace(compiled_recipe.packets[5], packet=forged_packet)
    argument_compiled = replace(
        compiled_recipe,
        packets=compiled_recipe.packets[:5] + (forged_hashed,) + compiled_recipe.packets[6:],
    )
    argument_result = SimulatedALDController().execute(argument_compiled, seed=42)
    assert argument_result.fault is not None
    assert argument_result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert argument_result.surface.total_sites == 0


def test_flaky_packet_container_is_rejected_before_second_iteration(compiled_recipe):
    """A packet tuple changing between preflight and execution must fail closed."""
    packets = FlakyTuple(compiled_recipe.packets, ("malformed",))
    compiled = replace(compiled_recipe, packets=packets)

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.surface.total_sites == 0


def test_surface_config_is_derived_from_recipe_fields(valid_recipe_dict):
    """Non-default recipe surface parameters must reach the aggregate model."""
    valid_recipe_dict["surface"] = {
        "model_version": "site-binomial/1",
        "regions": 2,
        "sites_per_region": 10,
        "transport_factors": [0.5, 0.75],
        "blocked_fraction": 0.2,
        "defect_fraction": 0.1,
        "k_a": 2.5,
        "k_b": 2.25,
        "growth_nm_per_reaction_fraction": 0.5,
        "purge_half_life_ms": 400,
        "max_event_samples": 3,
    }
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 1
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    controller = SimulatedALDController()
    result = controller.execute(compiled, seed=42)

    assert result.fault is None
    assert result.surface.total_sites == 20
    assert result.surface.blocked == 4
    assert result.surface.defects == 2
    assert controller._surface is not None
    assert controller._surface.config.transport_factors == (0.5, 0.75)
    assert controller._surface.config.k_a == 2.5
    assert controller._surface.config.k_b == 2.25
    assert controller._surface.config.growth_nm_per_reaction_fraction == 0.5
    assert controller._surface.config.purge_half_life_ms == 400
    assert controller._surface.max_event_samples == 3


def test_cycle_metrics_use_one_monotonic_index_across_macros(valid_recipe_dict):
    """Each ALD_CYCLE macro must continue the global cycle numbering."""
    cycle = valid_recipe_dict["instructions"][4]
    cycle["arguments"]["repeat"] = 1
    valid_recipe_dict["instructions"].insert(
        5, {"opcode": cycle["opcode"], "arguments": dict(cycle["arguments"])}
    )
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is None
    assert [metric.cycle for metric in result.cycles] == [1, 2]


def test_forged_root_hash_faults_without_seeding_surface(compiled_recipe):
    """A root-hash mismatch must be rejected before surface seeding."""
    compiled = replace(compiled_recipe, root_hash=b"r" * 32)

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == "ROOT_HASH_MISMATCH"
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("protocol", "FORGED/1", "PACKET_PROTOCOL_MISMATCH"),
        ("recipe_id", "forged-recipe", "PACKET_RECIPE_ID_MISMATCH"),
    ],
)
def test_forged_packet_identity_faults_before_surface_seeding(compiled_recipe, field, value, code):
    """Packet identity must bind to the compiled recipe before simulation."""
    if field == "protocol":
        packet = compiled_recipe.packets[0].packet
        object.__setattr__(packet, field, value)
    else:
        packet = replace(compiled_recipe.packets[0].packet, **{field: value})
    first = replace(compiled_recipe.packets[0], packet=packet)
    compiled = replace(compiled_recipe, packets=(first,) + compiled_recipe.packets[1:])

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.fault.code == code
    assert result.final_state is ControllerState.IDLE
    assert result.surface.total_sites == 0


def test_fault_shutdown_respects_low_recipe_pressure_limit(valid_recipe_dict):
    """Fault shutdown venting must remain inside the recipe pressure envelope."""
    valid_recipe_dict["initial_conditions"]["pressure_pa"] = 1000.0
    valid_recipe_dict["limits"]["max_pressure_pa"] = 1000.0
    valid_recipe_dict["instructions"][2]["arguments"]["target_pa"] = 100.0
    valid_recipe_dict["instructions"][6]["arguments"]["vent_target_pa"] = 1000.0
    valid_recipe_dict["limits"]["max_runtime_ms"] = 1_980_000
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    result = SimulatedALDController().execute(compiled, seed=42)

    assert result.fault is not None
    assert result.chamber.pressure_pa <= 1000.0
    assert all(event.details["pressure_pa"] <= 1000.0 for event in result.audit)
    assert result.audit[-1].state is ControllerState.IDLE


def test_interlocks_require_actual_booleans():
    with pytest.raises(TypeError, match="boolean"):
        Interlocks(vacuum_available=1)


def test_surface_counts_are_conserved(surface_config):
    model = SurfaceModel(surface_config, root_hash=b"r" * 32, user_seed=42)

    before = model.total_sites
    model.expose_a(cycle=1, dose=1.5)
    model.purge(duration_ms=5_000, half_life_ms=800)
    model.expose_b(cycle=1, dose=1.2)

    snapshot = model.snapshot()
    assert model.total_sites == before
    assert snapshot.total_sites == before
    assert all(region.total_sites == surface_config.sites_per_region for region in snapshot.regions)


def test_surface_seed_is_reproducible_and_sampling_independent(surface_config):
    a = SurfaceModel(surface_config, b"h" * 32, 42, max_event_samples=0)
    b = SurfaceModel(surface_config, b"h" * 32, 42, max_event_samples=100)

    for model in (a, b):
        model.expose_a(cycle=7, dose=1.5)
        model.expose_b(cycle=7, dose=1.2)

    assert a.snapshot() == b.snapshot()


def test_surface_probability_and_purge_boundaries_are_exact():
    assert reaction_probability(0.0, 99.0) == 0.0
    assert reaction_probability(3.0, 0.0) == 0.0
    assert reaction_probability(1.0, math.log(2.0)) == pytest.approx(0.5)
    assert decay_residual(1.0, duration_ms=800, half_life_ms=800) == pytest.approx(0.5)


def test_surface_a_reuses_b_reacted_sites_in_later_cycles():
    config = SurfaceConfig(
        model_version="site-binomial/1",
        regions=1,
        sites_per_region=100,
        transport_factors=(1.0,),
        blocked_fraction=0.0,
        defect_fraction=0.0,
        k_a=100.0,
        k_b=100.0,
        growth_nm_per_reaction_fraction=0.1,
        purge_half_life_ms=800,
    )
    model = SurfaceModel(config, root_hash=b"c" * 32, user_seed=2)

    assert model.expose_a(cycle=1, dose=1.0).total_reactions == 100
    assert model.expose_b(cycle=1, dose=1.0).total_reactions == 100
    assert model.expose_a(cycle=2, dose=1.0).total_reactions == 100

    snapshot = model.snapshot()
    assert snapshot.a_terminated == 100
    assert snapshot.b_reacted == 0
    assert snapshot.thickness_nm == pytest.approx(0.1)


def test_surface_config_normalizes_transport_factors_and_rejects_malformed_inputs():
    factors = [0.8, 1.0, 0.9]
    config = SurfaceConfig(
        model_version="site-binomial/1",
        regions=3,
        sites_per_region=10,
        transport_factors=factors,
        blocked_fraction=0.0,
        defect_fraction=0.0,
        k_a=1.0,
        k_b=1.0,
        growth_nm_per_reaction_fraction=0.1,
        purge_half_life_ms=800,
    )
    factors[0] = 0.1

    assert config.transport_factors == (0.8, 1.0, 0.9)
    with pytest.raises(SurfaceModelError, match="transport_factors"):
        SurfaceConfig(
            model_version="site-binomial/1",
            regions=1,
            sites_per_region=10,
            transport_factors=None,
            blocked_fraction=0.0,
            defect_fraction=0.0,
            k_a=1.0,
            k_b=1.0,
            growth_nm_per_reaction_fraction=0.1,
            purge_half_life_ms=800,
        )


def test_surface_initial_unavailable_sites_are_apportioned_without_overlap():
    config = SurfaceConfig(
        model_version="site-binomial/1",
        regions=1,
        sites_per_region=3,
        transport_factors=(1.0,),
        blocked_fraction=0.6,
        defect_fraction=0.4,
        k_a=1.0,
        k_b=1.0,
        growth_nm_per_reaction_fraction=0.1,
        purge_half_life_ms=800,
    )

    snapshot = SurfaceModel(config, root_hash=b"a" * 32, user_seed=1).snapshot()

    assert (snapshot.blocked, snapshot.defects, snapshot.vacant) == (2, 1, 0)


def test_reaction_rng_length_prefixes_domain_components_to_prevent_nul_collisions():
    root_hash = b"z" * 32
    # These inputs serialized identically with the old NUL-delimited encoding.
    first = reaction_rng(root_hash, "v\0" "1", 2, 3, "A", 4)
    second = reaction_rng(root_hash, "v", 1, 2, "3\0A", 4)

    assert first.integers(0, 2**63) != second.integers(0, 2**63)


def test_main_without_command_returns_usage_error(capsys):
    assert main([]) == ExitCode.USAGE
    assert "usage:" in capsys.readouterr().err.lower()


def test_live_control_is_rejected_as_an_invalid_command(capsys):
    assert main(["live-control"]) == ExitCode.USAGE
    assert "invalid choice" in capsys.readouterr().err.lower()


def test_duplicate_json_key_is_rejected(tmp_path):
    """Removing duplicate-key detection would silently accept ambiguous recipes."""
    path = tmp_path / "bad.json"
    path.write_text('{"protocol":"ALD-MEDIA/1","protocol":"other"}')

    with pytest.raises(RecipeError, match="duplicate key: protocol"):
        load_recipe(path)


def test_cycle_repeat_remains_one_packet(valid_recipe_dict):
    """Unrolling cycle repeats would break compact recipe compilation."""
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 500
    valid_recipe_dict["limits"]["max_runtime_ms"] = 6_100_000

    compiled = compile_recipe(validate_recipe(valid_recipe_dict))
    cycle = next(item for item in compiled.packets if item.packet.opcode == "ALD_CYCLE")

    assert cycle.packet.arguments["repeat"] == 500
    assert sum(item.packet.opcode == "ALD_CYCLE" for item in compiled.packets) == 1


def test_validation_rejects_expanded_runtime_above_limit(valid_recipe_dict):
    """Discarding macro duration would allow the static process budget to be exceeded."""
    valid_recipe_dict["limits"]["max_runtime_ms"] = 1_979_999

    with pytest.raises(RecipeLimitError, match="expanded runtime exceeds max_runtime_ms"):
        validate_recipe(valid_recipe_dict)


def test_hash_chain_matches_formula(valid_recipe_dict):
    """Changing the hash prefix or previous digest input must break chain verification."""
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))
    previous = bytes(32)

    for item in compiled.packets:
        expected = hashlib.sha256(b"ALD1" + previous + item.canonical_bytes).digest()
        assert item.previous_digest == previous
        assert item.digest == expected
        previous = expected

    assert compiled.root_hash == previous


def test_canonical_packet_bytes_are_exact_utf8_json():
    """Changing sort order, whitespace, or Unicode encoding changes integrity bytes."""
    packet = Packet(
        protocol="ALD-MEDIA/1",
        recipe_id="r\u00e9cipe",
        sequence=7,
        opcode="SET_TEMPERATURE",
        arguments={"tolerance_c": 1.0, "target_c": 200.0, "ramp_c_per_min": 20.0},
    )

    assert canonical_packet_bytes(packet) == (
        b'{"arguments":{"ramp_c_per_min":20.0,"target_c":200.0,"tolerance_c":1.0},'
        b'"opcode":"SET_TEMPERATURE",'
        b'"protocol":"ALD-MEDIA/1","recipe_id":"r\xc3\xa9cipe","sequence":7}'
    )


def test_validation_rejects_unknown_top_level_key(valid_recipe_dict):
    """Adding undeclared recipe fields must fail closed."""
    valid_recipe_dict["unsafe_extra"] = True

    with pytest.raises(RecipeError, match="unexpected keys"):
        validate_recipe(valid_recipe_dict)


def test_recipe_uses_default_packet_limit_when_omitted(valid_recipe_dict):
    """Omitting the optional packet limit must retain the 800-byte protocol cap."""
    del valid_recipe_dict["limits"]["max_packet_bytes"]

    recipe = validate_recipe(valid_recipe_dict)

    assert recipe.limits.max_packet_bytes == 800


def test_validation_rejects_non_integer_millisecond_field(valid_recipe_dict):
    """Allowing fractional millisecond durations makes process timing ambiguous."""
    valid_recipe_dict["instructions"][3]["arguments"]["duration_ms"] = 0.5

    with pytest.raises(RecipeError, match="duration_ms must be an integer"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_non_finite_float(valid_recipe_dict):
    """Non-finite numeric targets cannot be canonically encoded."""
    valid_recipe_dict["instructions"][1]["arguments"]["target_c"] = float("nan")

    with pytest.raises(RecipeError, match="target_c must be finite"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_cycle_purge_below_limit(valid_recipe_dict):
    """Relaxing the configured purge minimum would permit an unsafe macro."""
    valid_recipe_dict["instructions"][4]["arguments"]["purge_a_ms"] = 999

    with pytest.raises(RecipeLimitError, match="purge_a_ms below min_purge_ms"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_expanded_cycles_above_limit(valid_recipe_dict):
    """Ignoring repeat expansion would let a compact packet exceed max_cycles."""
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 1001

    with pytest.raises(RecipeLimitError, match="expanded cycles exceed max_cycles"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_target_outside_global_limit(valid_recipe_dict):
    """Ignoring global envelopes would accept excessive chamber targets."""
    valid_recipe_dict["instructions"][1]["arguments"]["target_c"] = 300.1

    with pytest.raises(RecipeLimitError, match="target_c exceeds max_temperature_c"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_negative_pressure_target(valid_recipe_dict):
    """A negative pressure target is outside the physical global envelope."""
    valid_recipe_dict["instructions"][2]["arguments"]["target_pa"] = -0.1

    with pytest.raises(RecipeLimitError, match="target_pa must be non-negative"):
        validate_recipe(valid_recipe_dict)


def test_validation_rejects_unknown_opcode_argument(valid_recipe_dict):
    """Permitting undeclared opcode arguments would make packet content ambiguous."""
    valid_recipe_dict["instructions"][3]["arguments"]["extra"] = 1

    with pytest.raises(RecipeError, match="STABILIZE arguments: unexpected keys"):
        validate_recipe(valid_recipe_dict)


def test_generated_packet_sequences_are_contiguous(valid_recipe_dict):
    """A sequence gap would break media packet ordering and the integrity chain."""
    compiled = compile_recipe(validate_recipe(valid_recipe_dict))

    assert [item.packet.sequence for item in compiled.packets] == list(range(7))


def test_canonical_packet_size_limit_is_enforced():
    """Oversize packet bytes must be rejected before media representation."""
    packet = Packet(
        protocol="ALD-MEDIA/1",
        recipe_id="r" * 800,
        sequence=0,
        opcode="CONFIGURE",
        arguments={},
    )

    with pytest.raises(RecipeLimitError, match="canonical packet exceeds 800 bytes"):
        canonical_packet_bytes(packet)


def test_compile_recipe_enforces_recipe_specific_packet_limit(valid_recipe_dict):
    """Ignoring a recipe's smaller packet budget would allow non-portable output."""
    valid_recipe_dict["recipe_id"] = "r" * 200
    valid_recipe_dict["limits"]["max_packet_bytes"] = 100

    with pytest.raises(RecipeLimitError, match="canonical packet exceeds recipe max_packet_bytes"):
        compile_recipe(validate_recipe(valid_recipe_dict))


def test_direct_packet_rejects_unknown_measurement_argument():
    """Direct packet construction must not accept undeclared opcode fields."""
    with pytest.raises(RecipeError, match="MEASURE arguments: unexpected keys"):
        Packet(
            protocol="ALD-MEDIA/1",
            recipe_id="direct",
            sequence=0,
            opcode="MEASURE",
            arguments={"measurements": ["coverage"], "unexpected": 1},
        )


@pytest.mark.parametrize("sequence", [True, 0.5])
def test_direct_packet_rejects_non_integer_sequence(sequence):
    """Boolean and fractional packet sequences break contiguous ordering."""
    with pytest.raises(RecipeError, match="sequence must be an integer"):
        Packet(
            protocol="ALD-MEDIA/1",
            recipe_id="direct",
            sequence=sequence,
            opcode="MEASURE",
            arguments={"measurements": ["coverage"]},
        )


def test_direct_packet_rejects_uncontrolled_measurement_value():
    """Packet arguments must remain within the controlled JSON opcode schema."""
    with pytest.raises(RecipeError, match="measurements contain unsupported value"):
        Packet(
            protocol="ALD-MEDIA/1",
            recipe_id="direct",
            sequence=0,
            opcode="MEASURE",
            arguments={"measurements": [object()]},
        )


def test_direct_packet_defensively_freezes_arguments():
    """Caller mutation must not alter already-constructed packet integrity bytes."""
    arguments = {"measurements": ["coverage"]}
    packet = Packet(
        protocol="ALD-MEDIA/1",
        recipe_id="direct",
        sequence=0,
        opcode="MEASURE",
        arguments=arguments,
    )
    before = canonical_packet_bytes(packet)

    arguments["measurements"].append("defect_fraction")

    assert canonical_packet_bytes(packet) == before
    with pytest.raises(TypeError):
        packet.arguments["measurements"] = ("coverage",)


def test_validate_prints_root_hash(valid_recipe_dict, tmp_path, capsys):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")

    assert main(["validate", str(recipe_path)]) == ExitCode.OK

    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == ""
    assert report["protocol"] == "ALD-MEDIA/1"
    assert len(report["root_hash"]) == 64
    assert report["packet_count"] == 7


def test_simulate_writes_required_outputs_and_is_deterministic(valid_recipe_dict, tmp_path):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    first, second = tmp_path / "first", tmp_path / "second"

    assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(first)]) == ExitCode.OK
    assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(second)]) == ExitCode.OK
    assert {path.name for path in first.iterdir()} == {"audit.jsonl", "cycles.csv", "surface-final.json"}
    for name in ("audit.jsonl", "cycles.csv", "surface-final.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_simulate_fault_publishes_fault_report_and_controller_exit(valid_recipe_dict, tmp_path):
    valid_recipe_dict["instructions"][4]["arguments"]["repeat"] = 2
    valid_recipe_dict["limits"]["max_runtime_ms"] = 980400
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    output = tmp_path / "fault-run"

    assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(output)]) == ExitCode.CONTROLLER
    assert {path.name for path in output.iterdir()} == {
        "audit.jsonl",
        "cycles.csv",
        "surface-final.json",
        "fault.json",
    }
    fault = json.loads((output / "fault.json").read_text(encoding="utf-8"))
    assert fault["code"] == "RUNTIME_LIMIT_EXCEEDED"
    assert len(fault["last_verified_digest"]) == 64


def test_simulate_collision_is_structured_and_does_not_replace_output(valid_recipe_dict, tmp_path, capsys):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    output = tmp_path / "run"
    output.mkdir()
    marker = output / "marker"
    marker.write_text("keep", encoding="utf-8")

    assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(output)]) == ExitCode.OUTPUT
    assert marker.read_text(encoding="utf-8") == "keep"
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "OUTPUT"


def test_simulate_overwrite_replaces_existing_directory(valid_recipe_dict, tmp_path):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    output = tmp_path / "run"
    output.mkdir()
    (output / "stale").write_text("remove", encoding="utf-8")

    assert main(
        [
            "simulate",
            str(recipe_path),
            "--seed",
            "42",
            "--output",
            str(output),
            "--overwrite",
        ]
    ) == ExitCode.OK
    assert not (output / "stale").exists()
    assert (output / "surface-final.json").exists()


def test_simulate_rejects_recipe_parent_and_higher_ancestor(valid_recipe_dict, tmp_path, capsys):
    recipe_dir = tmp_path / "recipes" / "nested"
    recipe_dir.mkdir(parents=True)
    recipe_path = recipe_dir / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    marker = tmp_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    for output in (recipe_dir, tmp_path):
        assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(output), "--overwrite"]) == ExitCode.OUTPUT
        assert recipe_path.exists()
        assert marker.read_text(encoding="utf-8") == "keep"
        assert json.loads(capsys.readouterr().err)["error"]["code"] == "OUTPUT"


def test_simulate_rejects_recipe_output_symlink_alias(valid_recipe_dict, tmp_path, capsys):
    recipe_dir = tmp_path / "recipes"
    recipe_dir.mkdir()
    recipe_path = recipe_dir / "recipe.json"
    recipe_path.write_text(json.dumps(valid_recipe_dict), encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(recipe_dir, target_is_directory=True)

    assert main(["simulate", str(recipe_path), "--seed", "42", "--output", str(alias), "--overwrite"]) == ExitCode.OUTPUT
    assert recipe_path.exists()
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "OUTPUT"


def test_replace_output_late_collision_never_clobbers(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    (temporary / "new").write_text("new", encoding="utf-8")
    output = tmp_path / "output"

    import ald_media_controller as controller_module

    original = controller_module._rename_noreplace

    def late_collision(parent_fd, source, destination, expected_source=None):
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=parent_fd)
        os.close(fd)
        return original(parent_fd, source, destination, expected_source)

    monkeypatch.setattr(controller_module, "_rename_noreplace", late_collision)
    with pytest.raises(OutputError):
        replace_output_directory(temporary, output)
    assert output.exists() and output.is_file()


def test_replace_output_staging_swap_fails_closed(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    (temporary / "new").write_text("new", encoding="utf-8")
    swapped = tmp_path / "swapped"
    swapped.mkdir()
    (swapped / "unrelated").write_text("unrelated", encoding="utf-8")
    output = tmp_path / "output"

    import ald_media_controller as controller_module

    original = controller_module._rename_noreplace

    def swap_staging(parent_fd, source_name, destination_name, expected_source=None):
        moved = os.fsencode("moved-staging")
        os.rename(source_name, moved, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.symlink(moved, source_name, src_dir_fd=parent_fd, target_is_directory=True)
        return original(parent_fd, source_name, destination_name, expected_source)

    monkeypatch.setattr(controller_module, "_rename_noreplace", swap_staging)
    with pytest.raises(OutputError):
        replace_output_directory(temporary, output)
    assert not output.exists()
    assert (swapped / "unrelated").read_text(encoding="utf-8") == "unrelated"


def test_publish_reports_does_not_delete_swapped_staging_directory(
    monkeypatch, compiled_recipe, tmp_path
):
    output = tmp_path / "output"
    swapped = tmp_path / "swapped"
    swapped.mkdir()
    (swapped / "unrelated").write_text("unrelated", encoding="utf-8")
    result = SimulatedALDController().execute(compiled_recipe, seed=42)

    import ald_media_controller as controller_module

    original = controller_module._rename_noreplace

    def swap_staging(parent_fd, source_name, destination_name, expected_source=None):
        moved = os.fsencode("moved-staging")
        os.rename(source_name, moved, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.symlink(moved, source_name, src_dir_fd=parent_fd, target_is_directory=True)
        return original(parent_fd, source_name, destination_name, expected_source)

    monkeypatch.setattr(controller_module, "_rename_noreplace", swap_staging)
    with pytest.raises(OutputError):
        publish_reports(result, output)
    assert not output.exists()
    assert (swapped / "unrelated").read_text(encoding="utf-8") == "unrelated"


def test_publish_reports_parent_swap_fails_closed_without_publishing(
    monkeypatch, compiled_recipe, tmp_path
):
    parent = tmp_path / "parent"
    parent.mkdir()
    moved_parent = tmp_path / "moved-parent"
    (parent / "unrelated").write_text("unrelated", encoding="utf-8")
    output = parent / "output"
    result = SimulatedALDController().execute(compiled_recipe, seed=42)

    import ald_media_controller as controller_module

    original_create = controller_module._create_staging_directory
    swapped = False

    def swap_parent(parent_handle, output_name):
        nonlocal swapped
        staging, staging_name = original_create(parent_handle, output_name)
        if not swapped:
            swapped = True
            parent.rename(moved_parent)
            parent.symlink_to(moved_parent, target_is_directory=True)
        return staging, staging_name

    monkeypatch.setattr(controller_module, "_create_staging_directory", swap_parent)
    publish_reports(result, output)
    assert (moved_parent / "unrelated").read_text(encoding="utf-8") == "unrelated"
    assert output.is_dir()


def test_replace_output_prepublication_failure_leaves_old_directory(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "old").write_text("old", encoding="utf-8")

    import ald_media_controller as controller_module

    monkeypatch.setattr(
        controller_module,
        "_rename_exchange",
        lambda parent_fd, source, destination, expected_source=None: (_ for _ in ()).throw(OSError("exchange failed")),
    )
    with pytest.raises(OutputError):
        replace_output_directory(temporary, output, overwrite=True)
    assert (output / "old").read_text(encoding="utf-8") == "old"


def test_replace_output_restores_old_directory_when_publication_fails(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "old").write_text("old", encoding="utf-8")

    import ald_media_controller as controller_module

    monkeypatch.setattr(
        controller_module,
        "_rename_exchange",
        lambda parent_fd, source, destination, expected_source=None: (_ for _ in ()).throw(OSError("publish failed")),
    )
    with pytest.raises(OutputError):
        replace_output_directory(temporary, output, overwrite=True)
    assert (output / "old").read_text(encoding="utf-8") == "old"


def test_replace_output_rolls_back_if_exchange_reports_after_commit(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    (temporary / "new").write_text("new", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "old").write_text("old", encoding="utf-8")

    import ald_media_controller as controller_module

    original_exchange = controller_module._rename_exchange
    calls = 0

    def exchange_then_fail(parent_fd, source_name, destination_name, expected_source=None):
        nonlocal calls
        calls += 1
        original_exchange(parent_fd, source_name, destination_name, expected_source)
        if calls == 1:
            raise OSError("injected post-commit exchange error")

    monkeypatch.setattr(controller_module, "_rename_exchange", exchange_then_fail)
    with pytest.raises(OutputError):
        replace_output_directory(temporary, output, overwrite=True)
    assert (output / "old").read_text(encoding="utf-8") == "old"
    assert (temporary / "new").read_text(encoding="utf-8") == "new"


def test_replace_output_retains_backup_when_restore_fails(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "old").write_text("old", encoding="utf-8")

    import ald_media_controller as controller_module

    original_exchange = controller_module._rename_exchange
    calls = 0

    def fail_restore(parent_fd, source, destination, expected_source=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_exchange(parent_fd, source, destination, expected_source)
        raise OSError("restore failed")

    monkeypatch.setattr(controller_module, "_rename_exchange", fail_restore)
    original_open = controller_module._open_existing_directory
    opens = 0

    def fail_identity(parent_handle, name):
        nonlocal opens
        opens += 1
        opened = original_open(parent_handle, name)
        if opens == 3 and opened is not None:
            opened.identity = (opened.identity[0], opened.identity[1] + 1)
        return opened

    monkeypatch.setattr(controller_module, "_open_existing_directory", fail_identity)
    with pytest.raises(OutputError, match="backup retained at"):
        replace_output_directory(temporary, output, overwrite=True)
    assert temporary.exists() and (temporary / "old").read_text(encoding="utf-8") == "old"


def test_replace_output_cleanup_failure_keeps_new_output_and_backup(monkeypatch, tmp_path):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    (temporary / "new").write_text("new", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "old").write_text("old", encoding="utf-8")

    import ald_media_controller as controller_module

    monkeypatch.setattr(controller_module, "_remove_owned_entry", lambda *args: (_ for _ in ()).throw(OSError("cleanup failed")))
    replace_output_directory(temporary, output, overwrite=True)
    assert (output / "new").read_text(encoding="utf-8") == "new"
    assert temporary.exists() and (temporary / "old").read_text(encoding="utf-8") == "old"


def test_create_staging_open_failure_does_not_orphan_entry(monkeypatch, tmp_path):
    import ald_media_controller as controller_module

    parent = tmp_path / "parent"
    parent.mkdir()
    parent_handle, output_name = controller_module._open_parent_directory(parent / "output")
    original_open = controller_module._open_child_directory
    calls = 0

    def fail_first_open(parent_fd, name):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected child-open failure")
        return original_open(parent_fd, name)

    monkeypatch.setattr(controller_module, "_open_child_directory", fail_first_open)
    try:
        with pytest.raises(OutputError, match="unable to open staging directory"):
            controller_module._create_staging_directory(parent_handle, output_name)
        entries = [entry for entry in parent.iterdir() if entry.name != ".ald-media-controller.lock"]
        assert entries == []
    finally:
        controller_module._close_quietly(parent_handle)


def test_owned_directory_close_failure_preserves_fd_until_retry(monkeypatch, tmp_path):
    import ald_media_controller as controller_module

    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    owned = controller_module._OwnedDirectory.from_fd(fd)
    real_close = os.close

    def fail_close(candidate):
        if candidate == fd:
            raise OSError("injected close failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module.os, "close", fail_close)
    with pytest.raises(OSError, match="injected close failure"):
        owned.close()
    assert owned.fd == fd
    monkeypatch.setattr(controller_module.os, "close", real_close)
    owned.close()
    owned.close()
    assert owned.fd == -1


def test_publisher_lock_is_held_during_report_transaction(monkeypatch, compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    observed = []
    real_flock = controller_module.fcntl.flock

    def observe_flock(fd, operation):
        observed.append((fd, operation))
        return real_flock(fd, operation)

    monkeypatch.setattr(controller_module.fcntl, "flock", observe_flock)
    output = tmp_path / "reports"
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    publish_reports(result, output)
    assert observed
    assert observed[0][1] == controller_module.fcntl.LOCK_EX
    assert sorted(path.name for path in output.iterdir()) == [
        "audit.jsonl",
        "cycles.csv",
        "surface-final.json",
    ]


def test_one_shot_lock_close_failure_is_retried_on_success(monkeypatch, compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    lock_fds = []

    def observe_lock(parent):
        lock = original_open_lock(parent)
        lock_fds.append(lock.fd)
        return lock

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    real_close = os.close
    failed = False
    baseline = set(os.listdir("/proc/self/fd"))

    def fail_once(fd):
        nonlocal failed
        if lock_fds and fd == lock_fds[0] and not failed:
            failed = True
            raise OSError("injected one-shot close failure")
        return real_close(fd)

    monkeypatch.setattr(controller_module.os, "close", fail_once)
    publish_reports(result, tmp_path / "first")
    assert failed
    with pytest.raises(OSError):
        os.fstat(lock_fds[0])
    assert set(os.listdir("/proc/self/fd")) == baseline
    monkeypatch.setattr(controller_module.os, "close", real_close)
    publish_reports(result, tmp_path / "second")


def test_one_shot_lock_close_failure_does_not_mask_error_cleanup(monkeypatch, compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    lock_fds = []

    def observe_lock(parent):
        lock = original_open_lock(parent)
        lock_fds.append(lock.fd)
        return lock

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    monkeypatch.setattr(
        controller_module,
        "_write_cycles_fd",
        lambda *args: (_ for _ in ()).throw(OutputError("injected report failure")),
    )
    real_close = os.close
    failed = False
    baseline = set(os.listdir("/proc/self/fd"))

    def fail_once(fd):
        nonlocal failed
        if lock_fds and fd == lock_fds[0] and not failed:
            failed = True
            raise OSError("injected one-shot close failure")
        return real_close(fd)

    monkeypatch.setattr(controller_module.os, "close", fail_once)
    with pytest.raises(OutputError, match="injected report failure"):
        publish_reports(result, tmp_path / "error")
    assert failed
    with pytest.raises(OSError):
        os.fstat(lock_fds[0])
    assert set(os.listdir("/proc/self/fd")) == baseline


def test_persistent_close_failure_is_deferred_until_next_publication(monkeypatch, compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    lock_fds = []
    persistent_fd = None

    def observe_lock(parent):
        nonlocal persistent_fd
        lock = original_open_lock(parent)
        lock_fds.append(lock.fd)
        if persistent_fd is None:
            persistent_fd = lock.fd
        return lock

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    real_close = os.close
    baseline = set(os.listdir("/proc/self/fd"))

    def fail_persistent(fd):
        if persistent_fd is not None and fd == persistent_fd:
            raise OSError("injected persistent close failure")
        return real_close(fd)

    monkeypatch.setattr(controller_module.os, "close", fail_persistent)
    publish_reports(result, tmp_path / "persistent")
    assert os.fstat(persistent_fd)
    monkeypatch.setattr(controller_module.os, "close", real_close)
    publish_reports(result, tmp_path / "drain")
    with pytest.raises(OSError):
        os.fstat(persistent_fd)
    assert set(os.listdir("/proc/self/fd")) == baseline


def test_fdopen_failure_closes_report_fd(monkeypatch, compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    parent, _ = controller_module._open_parent_directory(tmp_path / "output")
    staging, _ = controller_module._create_staging_directory(parent, b"output")
    before = set(os.listdir("/proc/self/fd"))

    monkeypatch.setattr(
        controller_module.os,
        "fdopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected fdopen failure")),
    )
    try:
        with pytest.raises(OutputError, match="unable to write report"):
            controller_module._write_fd_text(staging, b"report.txt", "report")
        assert set(os.listdir("/proc/self/fd")) == before
    finally:
        controller_module._close_quietly(staging)
        controller_module._close_quietly(parent)


def test_report_encoding_failure_does_not_leak_fd(compiled_recipe, tmp_path):
    import ald_media_controller as controller_module

    parent, _ = controller_module._open_parent_directory(tmp_path / "output")
    staging, _ = controller_module._create_staging_directory(parent, b"output")
    before = set(os.listdir("/proc/self/fd"))
    try:
        with pytest.raises(OutputError, match="unable to write report"):
            controller_module._write_fd_text(staging, b"report.txt", "\udcff")
        assert set(os.listdir("/proc/self/fd")) == before
    finally:
        controller_module._close_quietly(staging)
        controller_module._close_quietly(parent)


def test_write_cycle_csv_rejects_nonfinite_values_without_creating_file(tmp_path):
    path = tmp_path / "cycles.csv"
    with pytest.raises(OutputError, match="must be finite"):
        write_cycle_csv(
            [CycleMetric(1, 1, float("nan"), 0.0, 0.0, 0.0)],
            path,
        )
    assert not path.exists()


def test_write_cycle_csv_normalizes_malformed_metric_to_output_error(tmp_path):
    class MalformedMetric:
        cycle = 1
        simulation_time_ms = 1
        coverage = 0.0
        thickness_nm = 0.0
        utilization = 0.0

    with pytest.raises(OutputError, match="invalid cycle metric"):
        write_cycle_csv([MalformedMetric()], tmp_path / "cycles.csv")


def test_invalid_utf8_recipe_is_structured_recipe_error(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_bytes(b"{\xff")
    assert main(["validate", str(path)]) == ExitCode.RECIPE
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "RECIPE"


def test_help_returns_ok_without_structured_error(capsys):
    assert main(["--help"]) == ExitCode.OK
    output = capsys.readouterr()
    assert "usage:" in output.out.lower()
    assert output.err == ""


def test_argument_error_is_one_structured_usage_error(capsys):
    assert main(["simulate"]) == ExitCode.USAGE
    output = capsys.readouterr()
    assert output.out == ""
    payload = json.loads(output.err)
    assert payload["error"]["code"] == "USAGE"
    assert "usage:" in payload["error"]["message"].lower()
