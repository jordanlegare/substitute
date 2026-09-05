"""Backward-compatible public core facade with multi-precursor support.

The reviewed legacy implementation is retained byte-for-byte in
``_ald_legacy_core``. This facade re-exports its API and installs narrowly
scoped extension hooks for ``multi-precursor/1`` recipes,
``DEPOSITION_CYCLE`` packets, and the ``site-sequential/1`` model.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any

import _ald_legacy_core as _legacy
from ald_sequential_surface import (
    SequentialSurfaceConfig,
    SequentialSurfaceError,
    SequentialSurfaceModel,
    SequentialSurfaceSnapshot,
)

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_PRECURSOR_IDS = ("A", "B", "C", "D", "E", "F")
_MULTI_SCHEMA = "multi-precursor/1"

_ORIGINAL_VALIDATE_INSTRUCTION = _legacy._validate_instruction
_ORIGINAL_VALIDATE_PACKET_ARGUMENTS = _legacy._validate_packet_arguments
_ORIGINAL_IS_EXACT_PACKET_ARGUMENTS = _legacy._is_exact_packet_arguments
_LEGACY_CONTROLLER = _legacy.SimulatedALDController


def _is_multi_recipe(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("recipe_schema") == _MULTI_SCHEMA


def _expected_precursor_prefix(count: int) -> tuple[str, ...]:
    return _PRECURSOR_IDS[:count]


def _validate_precursors(metadata: Mapping[str, Any], raw: Any) -> Mapping[str, Mapping[str, Any]]:
    if not _is_multi_recipe(metadata):
        values = _legacy._require_exact_keys(raw, frozenset({"A", "B"}), "precursors")
        normalized: dict[str, Mapping[str, Any]] = {}
        for key in ("A", "B"):
            item = _legacy._require_exact_keys(values[key], frozenset({"label"}), f"precursors.{key}")
            normalized[key] = MappingProxyType(
                {"label": _legacy._require_string(item["label"], f"precursors.{key}.label")}
            )
        return MappingProxyType(normalized)

    values = _legacy._require_mapping(raw, "precursors")
    keys = tuple(sorted(values))
    if not 2 <= len(keys) <= 6:
        raise _legacy.RecipeError("multi-precursor recipes require 2 to 6 precursors")
    if keys != _expected_precursor_prefix(len(keys)):
        raise _legacy.RecipeError("multi-precursor keys must be a contiguous A-F prefix")
    normalized = {}
    for key in keys:
        item = _legacy._require_exact_keys(
            values[key], frozenset({"name", "formula", "role"}), f"precursors.{key}"
        )
        normalized[key] = MappingProxyType(
            {
                field: _legacy._require_string(item[field], f"precursors.{key}.{field}")
                for field in ("name", "formula", "role")
            }
        )
    return MappingProxyType(normalized)


def _validate_deposition_cycle_arguments(
    arguments: Any,
    limits: _legacy.ProcessLimits,
    precursors: Mapping[str, Any],
) -> tuple[Mapping[str, Any], int]:
    values = _legacy._require_exact_keys(
        arguments, frozenset({"exposures", "repeat"}), "DEPOSITION_CYCLE arguments"
    )
    exposures = values["exposures"]
    if not isinstance(exposures, list) or not 2 <= len(exposures) <= 12:
        raise _legacy.RecipeError("DEPOSITION_CYCLE exposures must contain 2 to 12 steps")

    normalized: list[Mapping[str, Any]] = []
    used: set[str] = set()
    for index, raw_exposure in enumerate(exposures):
        item = _legacy._require_exact_keys(
            raw_exposure,
            frozenset({"precursor", "dose", "purge_ms"}),
            f"exposures[{index}]",
        )
        precursor = _legacy._require_string(item["precursor"], f"exposures[{index}].precursor")
        if precursor not in precursors:
            raise _legacy.RecipeError("DEPOSITION_CYCLE references undeclared precursor")
        dose = _legacy._require_finite_number(item["dose"], f"exposures[{index}].dose")
        purge_ms = _legacy._require_integer(
            item["purge_ms"], f"exposures[{index}].purge_ms", minimum=1
        )
        if dose < 0:
            raise _legacy.RecipeLimitError("DEPOSITION_CYCLE dose must be non-negative")
        if purge_ms < limits.min_purge_ms:
            raise _legacy.RecipeLimitError("DEPOSITION_CYCLE purge below min_purge_ms")
        used.add(precursor)
        normalized.append(
            MappingProxyType(
                {"precursor": precursor, "dose": float(dose), "purge_ms": purge_ms}
            )
        )

    if used != set(precursors):
        raise _legacy.RecipeError("DEPOSITION_CYCLE must use every declared precursor")
    repeat = _legacy._require_integer(values["repeat"], "repeat", minimum=1)
    runtime_ms = repeat * sum(item["purge_ms"] for item in normalized)
    return MappingProxyType({"exposures": tuple(normalized), "repeat": repeat}), runtime_ms


def _validate_instruction(
    raw: Any,
    limits: _legacy.ProcessLimits,
    precursors: Mapping[str, Any],
) -> tuple[Mapping[str, Any], int]:
    instruction = _legacy._require_exact_keys(
        raw, frozenset({"opcode", "arguments"}), "instruction"
    )
    opcode = _legacy._require_string(instruction["opcode"], "opcode")
    if opcode != "DEPOSITION_CYCLE":
        return _ORIGINAL_VALIDATE_INSTRUCTION(raw, limits, precursors)
    normalized, runtime_ms = _validate_deposition_cycle_arguments(
        instruction["arguments"], limits, precursors
    )
    return MappingProxyType({"opcode": opcode, "arguments": normalized}), runtime_ms


def _validate_packet_arguments(opcode: str, arguments: Any) -> Mapping[str, Any]:
    if opcode != "DEPOSITION_CYCLE":
        return _ORIGINAL_VALIDATE_PACKET_ARGUMENTS(opcode, arguments)

    values = _legacy._require_exact_keys(
        arguments, frozenset({"exposures", "repeat"}), "DEPOSITION_CYCLE arguments"
    )
    exposures = values["exposures"]
    if not isinstance(exposures, (list, tuple)) or not 2 <= len(exposures) <= 12:
        raise _legacy.RecipeError("DEPOSITION_CYCLE exposures must contain 2 to 12 steps")
    normalized: list[dict[str, Any]] = []
    for index, raw_exposure in enumerate(exposures):
        item = _legacy._require_exact_keys(
            raw_exposure,
            frozenset({"precursor", "dose", "purge_ms"}),
            f"exposures[{index}]",
        )
        precursor = _legacy._require_string(item["precursor"], f"exposures[{index}].precursor")
        if precursor not in _PRECURSOR_IDS:
            raise _legacy.RecipeError("DEPOSITION_CYCLE precursor must be A through F")
        dose = _legacy._require_finite_number(item["dose"], f"exposures[{index}].dose")
        purge_ms = _legacy._require_integer(
            item["purge_ms"], f"exposures[{index}].purge_ms", minimum=1
        )
        if dose < 0:
            raise _legacy.RecipeLimitError("DEPOSITION_CYCLE dose must be non-negative")
        normalized.append(
            {"precursor": precursor, "dose": float(dose), "purge_ms": purge_ms}
        )
    repeat = _legacy._require_integer(values["repeat"], "repeat", minimum=1)
    return {"exposures": normalized, "repeat": repeat}


def _is_exact_packet_arguments(opcode: object, arguments: object) -> bool:
    if opcode != "DEPOSITION_CYCLE":
        return _ORIGINAL_IS_EXACT_PACKET_ARGUMENTS(opcode, arguments)
    if type(arguments) is not MappingProxyType:
        return False
    try:
        if set(arguments) != {"exposures", "repeat"}:
            return False
        exposures = arguments["exposures"]
        repeat = arguments["repeat"]
        if type(exposures) is not tuple or not 2 <= len(exposures) <= 12:
            return False
        if type(repeat) is not int or repeat < 1:
            return False
        for item in exposures:
            if type(item) is not MappingProxyType or set(item) != {"precursor", "dose", "purge_ms"}:
                return False
            precursor = item["precursor"]
            dose = item["dose"]
            purge_ms = item["purge_ms"]
            if type(precursor) is not str or precursor not in _PRECURSOR_IDS:
                return False
            if type(dose) is not float or not _legacy.math.isfinite(dose) or dose < 0:
                return False
            if type(purge_ms) is not int or purge_ms < 1:
                return False
        return True
    except Exception:
        return False


def validate_recipe(raw: Mapping[str, Any]) -> _legacy.Recipe:
    """Validate legacy or ``multi-precursor/1`` recipes into the legacy Recipe type."""
    recipe = _legacy._require_exact_keys(raw, _legacy._TOP_LEVEL_KEYS, "recipe")
    if recipe["protocol"] != _legacy._PROTOCOL:
        raise _legacy.RecipeError("protocol must be ALD-MEDIA/1")
    recipe_id = _legacy._require_string(recipe["recipe_id"], "recipe_id")

    metadata = _legacy._require_mapping(recipe["metadata"], "metadata")
    _legacy._validate_json_value(metadata, "metadata")
    surface = _legacy._require_mapping(recipe["surface"], "surface")
    _legacy._validate_json_value(surface, "surface")
    precursors = _validate_precursors(metadata, recipe["precursors"])

    if _is_multi_recipe(metadata) and surface.get("model_version") != "site-sequential/1":
        raise _legacy.RecipeError(
            "multi-precursor recipes require surface.model_version site-sequential/1"
        )

    limits = _legacy._validate_limits(recipe["limits"])
    initial = _legacy._require_exact_keys(
        recipe["initial_conditions"], _legacy._INITIAL_CONDITION_KEYS, "initial_conditions"
    )
    temperature = _legacy._require_finite_number(
        initial["temperature_c"], "initial_conditions.temperature_c"
    )
    pressure = _legacy._require_finite_number(
        initial["pressure_pa"], "initial_conditions.pressure_pa"
    )
    if temperature > limits.max_temperature_c:
        raise _legacy.RecipeLimitError("initial temperature exceeds max_temperature_c")
    if pressure > limits.max_pressure_pa:
        raise _legacy.RecipeLimitError("initial pressure exceeds max_pressure_pa")

    if not isinstance(recipe["instructions"], list) or not recipe["instructions"]:
        raise _legacy.RecipeError("instructions must be a non-empty list")
    instructions: list[Mapping[str, Any]] = []
    expanded_cycles = 0
    runtime_ms = 0
    exposure_signature: tuple[str, ...] | None = None
    for instruction in recipe["instructions"]:
        normalized, duration = _validate_instruction(instruction, limits, precursors)
        instructions.append(normalized)
        runtime_ms += duration
        if normalized["opcode"] in {"ALD_CYCLE", "DEPOSITION_CYCLE"}:
            expanded_cycles += normalized["arguments"]["repeat"]
        if normalized["opcode"] == "DEPOSITION_CYCLE":
            signature = tuple(item["precursor"] for item in normalized["arguments"]["exposures"])
            if exposure_signature is None:
                exposure_signature = signature
            elif signature != exposure_signature:
                raise _legacy.RecipeError(
                    "all DEPOSITION_CYCLE instructions must use the same exposure signature"
                )
        if expanded_cycles > limits.max_cycles:
            raise _legacy.RecipeLimitError("expanded cycles exceed max_cycles")
        if runtime_ms > limits.max_runtime_ms:
            raise _legacy.RecipeLimitError("expanded runtime exceeds max_runtime_ms")

    return _legacy.Recipe(
        protocol=_legacy._PROTOCOL,
        recipe_id=recipe_id,
        metadata=_legacy._freeze_json(metadata),
        precursors=precursors,
        initial_conditions=MappingProxyType(
            {"temperature_c": temperature, "pressure_pa": pressure}
        ),
        limits=limits,
        surface=_legacy._freeze_json(surface),
        instructions=tuple(instructions),
    )


class ControllerState(str, Enum):
    IDLE = "IDLE"
    CONFIGURED = "CONFIGURED"
    HEATING = "HEATING"
    EVACUATING = "EVACUATING"
    READY = "READY"
    A_PULSE = "A_PULSE"
    A_PURGE = "A_PURGE"
    B_PULSE = "B_PULSE"
    B_PURGE = "B_PURGE"
    DEPOSITION_EXPOSURE = "DEPOSITION_EXPOSURE"
    DEPOSITION_PURGE = "DEPOSITION_PURGE"
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"
    SHUTDOWN = "SHUTDOWN"


ALLOWED_TRANSITIONS = MappingProxyType(
    {
        ControllerState.IDLE: frozenset({ControllerState.CONFIGURED, ControllerState.FAULT}),
        ControllerState.CONFIGURED: frozenset({ControllerState.HEATING, ControllerState.FAULT}),
        ControllerState.HEATING: frozenset({ControllerState.EVACUATING, ControllerState.FAULT}),
        ControllerState.EVACUATING: frozenset({ControllerState.READY, ControllerState.FAULT}),
        ControllerState.READY: frozenset(
            {
                ControllerState.A_PULSE,
                ControllerState.DEPOSITION_EXPOSURE,
                ControllerState.COMPLETE,
                ControllerState.FAULT,
            }
        ),
        ControllerState.A_PULSE: frozenset({ControllerState.A_PURGE, ControllerState.FAULT}),
        ControllerState.A_PURGE: frozenset({ControllerState.B_PULSE, ControllerState.FAULT}),
        ControllerState.B_PULSE: frozenset({ControllerState.B_PURGE, ControllerState.FAULT}),
        ControllerState.B_PURGE: frozenset({ControllerState.READY, ControllerState.FAULT}),
        ControllerState.DEPOSITION_EXPOSURE: frozenset(
            {ControllerState.DEPOSITION_PURGE, ControllerState.FAULT}
        ),
        ControllerState.DEPOSITION_PURGE: frozenset(
            {
                ControllerState.DEPOSITION_EXPOSURE,
                ControllerState.READY,
                ControllerState.FAULT,
            }
        ),
        ControllerState.COMPLETE: frozenset({ControllerState.SHUTDOWN}),
        ControllerState.FAULT: frozenset({ControllerState.SHUTDOWN}),
        ControllerState.SHUTDOWN: frozenset({ControllerState.IDLE}),
    }
)


class _SequentialSnapshotAdapter:
    def __init__(self, snapshot: SequentialSurfaceSnapshot, exposure_signature: tuple[str, ...]) -> None:
        self._snapshot = snapshot
        self.exposure_signature = exposure_signature

    def __getattr__(self, name: str) -> Any:
        return getattr(self._snapshot, name)

    def as_dict(self) -> dict[str, object]:
        result = self._snapshot.as_dict()
        result["exposure_signature"] = list(self.exposure_signature)
        return result


class SimulatedALDController(_LEGACY_CONTROLLER):
    """Legacy controller plus deterministic ``DEPOSITION_CYCLE`` execution."""

    def _initialize_surface(self, compiled: _legacy.CompiledRecipe, seed: int) -> None:
        recipe = compiled.recipe
        if recipe.surface.get("model_version", "site-binomial/1") != "site-sequential/1":
            return super()._initialize_surface(compiled, seed)

        deposition = next(
            (
                instruction
                for instruction in recipe.instructions
                if instruction["opcode"] == "DEPOSITION_CYCLE"
            ),
            None,
        )
        if deposition is None:
            raise _legacy.SurfaceModelError(
                "site-sequential/1 requires at least one DEPOSITION_CYCLE"
            )
        signature = tuple(
            item["precursor"] for item in deposition["arguments"]["exposures"]
        )
        surface = recipe.surface
        try:
            regions = surface.get("regions", 1)
            transport = surface.get("transport_factors", (1.0,) * int(regions))
            reaction_factors = surface.get(
                "reaction_factors", (1.0,) * len(signature)
            )
            config = SequentialSurfaceConfig(
                model_version="site-sequential/1",
                regions=regions,
                sites_per_region=surface.get("sites_per_region", 1000),
                transport_factors=tuple(transport),
                blocked_fraction=surface.get("blocked_fraction", 0.0),
                defect_fraction=surface.get("defect_fraction", 0.0),
                reaction_factors=tuple(reaction_factors),
                growth_nm_per_completion_fraction=surface.get(
                    "growth_nm_per_completion_fraction", 0.1
                ),
                purge_half_life_ms=surface.get("purge_half_life_ms", 800),
                precursor_ids=tuple(recipe.precursors.keys()),
                exposure_signature=signature,
            )
            self._surface = SequentialSurfaceModel(
                config,
                compiled.root_hash,
                seed,
                max_event_samples=surface.get("max_event_samples", 0),
            )
        except (SequentialSurfaceError, TypeError, ValueError) as error:
            raise _legacy.SurfaceModelError(str(error)) from error
        self._active_recipe = recipe
        self.chamber.active_precursor = None
        self._sequential_signature = signature

    def incompatible_residual(self, next_precursor: str) -> float:
        if type(self._surface) is SequentialSurfaceModel:
            try:
                return self._surface.max_incompatible_residual(next_precursor)
            except SequentialSurfaceError as error:
                raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG") from error
        return super().incompatible_residual(next_precursor)

    def _execute_packet(self, packet: _legacy.Packet) -> None:
        if packet.opcode != "DEPOSITION_CYCLE":
            return super()._execute_packet(packet)
        if self._shutdown_completed:
            raise _legacy.ControllerFault("INVALID_TRANSITION")
        self._execute_deposition_cycles(packet.arguments, packet.sequence)

    def _require_sequential_surface(self) -> SequentialSurfaceModel:
        if type(self._surface) is not SequentialSurfaceModel:
            raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG")
        return self._surface

    def _deposition_details(self, cycle: int, step_index: int, precursor: str) -> Mapping[str, Any]:
        recipe = getattr(self, "_active_recipe", None)
        if recipe is None or precursor not in recipe.precursors:
            raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG")
        precursor_name = recipe.precursors[precursor].get("name")
        if type(precursor_name) is not str or not precursor_name:
            raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG")
        return {
            "cycle": cycle,
            "step_index": step_index,
            "precursor": precursor,
            "precursor_name": precursor_name,
        }

    def _append_cycle_metric(self, cycle: int) -> None:
        surface = self._require_sequential_surface().snapshot()
        self._cycles.append(
            _legacy.CycleMetric(
                cycle=cycle,
                simulation_time_ms=self.chamber.simulation_time_ms,
                coverage=surface.coverage,
                thickness_nm=surface.thickness_nm,
                utilization=surface.utilization,
                defect_fraction=surface.defect_fraction,
            )
        )

    def _execute_deposition_cycles(self, arguments: Mapping[str, Any], sequence: int) -> None:
        if self.state is not ControllerState.READY:
            raise _legacy.ControllerFault("INVALID_TRANSITION")
        exposures = arguments["exposures"]
        for _ in range(int(arguments["repeat"])):
            self._cycle_index += 1
            cycle = self._cycle_index
            for step_index, exposure in enumerate(exposures):
                precursor = exposure["precursor"]
                self.assert_precursor_safe(precursor)
                self.chamber.active_precursor = precursor
                self.transition(
                    ControllerState.DEPOSITION_EXPOSURE,
                    packet_sequence=sequence,
                    details=self._deposition_details(cycle, step_index, precursor),
                )
                try:
                    self._require_sequential_surface().expose_step(
                        cycle,
                        step_index,
                        precursor,
                        float(exposure["dose"]),
                    )
                except SequentialSurfaceError as error:
                    raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG") from error
                self.chamber.active_precursor = None
                self.chamber.inert_purge_open = True
                self.transition(
                    ControllerState.DEPOSITION_PURGE,
                    packet_sequence=sequence,
                    details=self._deposition_details(cycle, step_index, precursor),
                )
                purge_ms = int(exposure["purge_ms"])
                self._advance_time(purge_ms)
                try:
                    self._require_sequential_surface().purge(purge_ms)
                except SequentialSurfaceError as error:
                    raise _legacy.ControllerFault("INVALID_SURFACE_CONFIG") from error
                self.chamber.inert_purge_open = False
            self.transition(
                ControllerState.READY,
                packet_sequence=sequence,
                details={"cycle": cycle},
            )
            self._append_cycle_metric(cycle)

    def _shutdown(self, ramp_c_per_min: float, vent_target_pa: float) -> None:
        self.chamber.active_precursor = None
        super()._shutdown(ramp_c_per_min, vent_target_pa)

    def _handle_fault(self, error: _legacy.ControllerFault) -> None:
        self.chamber.active_precursor = None
        super()._handle_fault(error)

    def execute(self, compiled: _legacy.CompiledRecipe, seed: int) -> _legacy.SimulationResult:
        result = super().execute(compiled, seed)
        if type(result.surface) is not SequentialSurfaceSnapshot:
            return result
        signature = getattr(self, "_sequential_signature", result.surface.model_version and ())
        adapted = _SequentialSnapshotAdapter(result.surface, tuple(signature))
        return _legacy.SimulationResult(
            audit=result.audit,
            cycles=result.cycles,
            surface=adapted,
            fault=result.fault,
            final_state=result.final_state,
            chamber=result.chamber,
            protocol=result.protocol,
            recipe_id=result.recipe_id,
            root_hash=result.root_hash,
            seed=result.seed,
            model_version=result.model_version,
        )


def _expanded_cycle_count(recipe: _legacy.Recipe) -> int:
    return sum(
        int(instruction["arguments"]["repeat"])
        for instruction in recipe.instructions
        if instruction["opcode"] in {"ALD_CYCLE", "DEPOSITION_CYCLE"}
    )


def _expanded_runtime_ms(recipe: _legacy.Recipe) -> int:
    runtime = 0
    for instruction in recipe.instructions:
        opcode = instruction["opcode"]
        arguments = instruction["arguments"]
        if opcode == "EVACUATE":
            runtime += int(arguments["timeout_ms"])
        elif opcode == "STABILIZE":
            runtime += int(arguments["duration_ms"])
        elif opcode == "ALD_CYCLE":
            runtime += int(arguments["repeat"]) * sum(
                int(arguments[field])
                for field in ("pulse_a_ms", "purge_a_ms", "pulse_b_ms", "purge_b_ms")
            )
        elif opcode == "DEPOSITION_CYCLE":
            runtime += int(arguments["repeat"]) * sum(
                int(item["purge_ms"]) for item in arguments["exposures"]
            )
    return runtime


_legacy._validate_packet_arguments = _validate_packet_arguments
_legacy._is_exact_packet_arguments = _is_exact_packet_arguments
_legacy._validate_instruction = _validate_instruction
_legacy.validate_recipe = validate_recipe
_legacy.ControllerState = ControllerState
_legacy.ALLOWED_TRANSITIONS = ALLOWED_TRANSITIONS
_legacy.SimulatedALDController = SimulatedALDController
_legacy._expanded_cycle_count = _expanded_cycle_count
_legacy._expanded_runtime_ms = _expanded_runtime_ms

globals().update(
    {
        "_validate_packet_arguments": _validate_packet_arguments,
        "_is_exact_packet_arguments": _is_exact_packet_arguments,
        "_validate_instruction": _validate_instruction,
        "_validate_precursors": _validate_precursors,
        "_validate_deposition_cycle_arguments": _validate_deposition_cycle_arguments,
        "validate_recipe": validate_recipe,
        "ControllerState": ControllerState,
        "ALLOWED_TRANSITIONS": ALLOWED_TRANSITIONS,
        "SimulatedALDController": SimulatedALDController,
        "_expanded_cycle_count": _expanded_cycle_count,
        "_expanded_runtime_ms": _expanded_runtime_ms,
    }
)
