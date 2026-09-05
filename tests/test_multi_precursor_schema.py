from copy import deepcopy
from pathlib import Path
import math

import pytest

import ald_core as core


def test_generic_al2o3_root_is_legacy_golden():
    recipe = core.validate_recipe(core.load_recipe(Path("recipes/generic_al2o3.json")))
    compiled = core.compile_recipe(recipe)
    assert compiled.root_hash.hex() == "ba55931d8057799a9456c6412c9a1dc36d6600b2c877e25a28ec3564574dcad0"


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
                    {"precursor": "C", "dose": 0.3, "purge_ms": 2000},
                ],
                "repeat": 2,
            }},
            {"opcode": "MEASURE", "arguments": {"measurements": ["thickness_nm", "coverage", "defect_fraction"]}},
            {"opcode": "SHUTDOWN", "arguments": {"heater_ramp_c_per_min": 20.0, "vent_target_pa": 101325.0}},
        ],
    }


def _leave_one_precursor(raw):
    raw["precursors"].pop("C")
    raw["precursors"].pop("B")


def _make_precursor_gap(raw):
    raw["precursors"]["D"] = raw["precursors"].pop("C")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (_leave_one_precursor, "2 to 6"),
        (_make_precursor_gap, "contiguous"),
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
