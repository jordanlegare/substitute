from copy import deepcopy

import ald_core as core


def multi_recipe():
    return {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": "controller-multi-001",
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
            "max_residual_fraction": 0.1,
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
                    {"precursor": "C", "dose": 0.3, "purge_ms": 2000},
                ],
                "repeat": 2,
            }},
            {"opcode": "MEASURE", "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]}},
            {"opcode": "SHUTDOWN", "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0}},
        ],
    }


def execute(raw, seed=42):
    recipe = core.validate_recipe(raw)
    return core.SimulatedALDController().execute(core.compile_recipe(recipe), seed)


def test_three_precursor_controller_completes():
    result = execute(multi_recipe())
    assert result.fault is None
    assert result.final_state is core.ControllerState.IDLE
    assert result.surface.completed_depositions > 0
    assert result.surface.exposure_signature == ("A", "B", "C")


def test_seed_42_is_reproducible():
    first = execute(multi_recipe(), 42)
    second = execute(multi_recipe(), 42)
    assert first.surface.as_dict() == second.surface.as_dict()
    assert first.cycles == second.cycles


def test_bad_reaction_factor_length_fails_closed():
    raw = multi_recipe()
    raw["surface"]["reaction_factors"] = [1.0, 1.0]
    result = execute(raw)
    assert result.fault is not None
    assert result.fault.code == "INVALID_SURFACE_CONFIG"


def test_six_precursor_controller_completes():
    raw = multi_recipe()
    raw["recipe_id"] = "controller-six-001"
    raw["precursors"].update(
        {
            "D": {"name": "oxygen", "formula": "O2", "role": "oxidant"},
            "E": {"name": "nitrogen", "formula": "N2", "role": "modifier"},
            "F": {"name": "hydrogen", "formula": "H2", "role": "reductant"},
        }
    )
    raw["instructions"][4]["arguments"]["exposures"].extend(
        [
            {"precursor": "D", "dose": 0.25, "purge_ms": 3000},
            {"precursor": "E", "dose": 0.2, "purge_ms": 3000},
            {"precursor": "F", "dose": 0.15, "purge_ms": 3000},
        ]
    )
    raw["surface"]["reaction_factors"] = [1.4, 1.2, 1.0, 0.9, 0.8, 0.7]
    raw["limits"]["max_residual_fraction"] = 0.15
    result = execute(raw)
    assert result.fault is None
    assert result.surface.exposure_signature == ("A", "B", "C", "D", "E", "F")
    assert result.surface.completed_depositions > 0


def test_sequential_residual_interlock_fails_closed():
    raw = deepcopy(multi_recipe())
    raw["limits"]["max_residual_fraction"] = 0.001
    result = execute(raw)
    assert result.fault is not None
    assert result.fault.code == "INCOMPATIBLE_RESIDUAL"
