"""Backward-compatible public core facade with multi-precursor schema support.

The original implementation is retained byte-for-byte in ``_ald_legacy_core``.
This facade re-exports that API and patches only the extension hooks required
for ``multi-precursor/1`` recipes and ``DEPOSITION_CYCLE`` packets. Keeping
legacy objects and algorithms in the original module preserves existing
packet bytes, ALD1 roots, controller behavior, and report formats.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import _ald_legacy_core as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_PRECURSOR_IDS = ("A", "B", "C", "D", "E", "F")
_MULTI_SCHEMA = "multi-precursor/1"

_ORIGINAL_VALIDATE_INSTRUCTION = _legacy._validate_instruction
_ORIGINAL_VALIDATE_PACKET_ARGUMENTS = _legacy._validate_packet_arguments
_ORIGINAL_IS_EXACT_PACKET_ARGUMENTS = _legacy._is_exact_packet_arguments


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


_legacy._validate_packet_arguments = _validate_packet_arguments
_legacy._is_exact_packet_arguments = _is_exact_packet_arguments
_legacy._validate_instruction = _validate_instruction
_legacy.validate_recipe = validate_recipe

globals().update(
    {
        "_validate_packet_arguments": _validate_packet_arguments,
        "_is_exact_packet_arguments": _is_exact_packet_arguments,
        "_validate_instruction": _validate_instruction,
        "_validate_precursors": _validate_precursors,
        "_validate_deposition_cycle_arguments": _validate_deposition_cycle_arguments,
        "validate_recipe": validate_recipe,
    }
)
