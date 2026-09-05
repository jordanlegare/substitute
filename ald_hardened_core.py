"""Hardened public facade with multi-precursor trust-shape support.

The reviewed hardening implementation is retained byte-for-byte in
``_ald_legacy_hardened_core``. Importing it installs the original trust,
fault-containment, publication, and CLI hardening on ``ald_core``. This module
then widens only the validated recipe-shape predicate for
``multi-precursor/1`` recipes and clears the generalized active-precursor
marker on fault.
"""

from __future__ import annotations

import math
import sys
from types import MappingProxyType
from typing import Any

# Import for side effects: this installs the existing hardened boundary on
# the public ald_core module and then aliases its own module name to ald_core.
import _ald_legacy_hardened_core  # noqa: F401
import ald_core as _base


# The installed hardened methods retain the original module globals even
# though that module aliases itself to ald_core in sys.modules. Reach those
# globals through the installed function object instead of copying hardening
# logic here.
_HARDENED_GLOBALS = _base.SimulatedALDController._start_run.__globals__
_ORIGINAL_SHAPE_CHECK = _HARDENED_GLOBALS["_recipe_shape_is_trusted"]
_ORIGINAL_HARDENED_HANDLE_FAULT = _base.SimulatedALDController._handle_fault


def _multi_recipe_shape_is_trusted(recipe: Any) -> bool:
    """Apply the existing hardened contract to the extended precursor schema."""
    if type(recipe) is not _base.Recipe:
        return False
    try:
        metadata = recipe.metadata
        if type(metadata) is not MappingProxyType:
            return False
        if metadata.get("recipe_schema") != "multi-precursor/1":
            return _ORIGINAL_SHAPE_CHECK(recipe)
        normalized_json_is_exact = _HARDENED_GLOBALS["_normalized_json_is_exact"]
        limits_are_exact = _HARDENED_GLOBALS["_limits_are_exact"]
        thaw_normalized = _HARDENED_GLOBALS["_thaw_normalized"]
        harden_validated_recipe = _HARDENED_GLOBALS["_harden_validated_recipe"]
        original_validate_recipe = _HARDENED_GLOBALS["_ORIGINAL_VALIDATE_RECIPE"]

        if type(recipe.protocol) is not str or recipe.protocol != _base._PROTOCOL:
            return False
        if type(recipe.recipe_id) is not str or not recipe.recipe_id:
            return False
        if not normalized_json_is_exact(metadata):
            return False

        precursors = recipe.precursors
        if type(precursors) is not MappingProxyType:
            return False
        keys = tuple(sorted(precursors.keys()))
        if not 2 <= len(keys) <= 6 or keys != tuple("ABCDEF"[: len(keys)]):
            return False
        for key in keys:
            item = precursors[key]
            if type(item) is not MappingProxyType or set(item.keys()) != {"name", "formula", "role"}:
                return False
            if any(type(item[field]) is not str or not item[field] for field in ("name", "formula", "role")):
                return False

        initial = recipe.initial_conditions
        if type(initial) is not MappingProxyType or set(initial.keys()) != {"temperature_c", "pressure_pa"}:
            return False
        temperature = initial["temperature_c"]
        pressure = initial["pressure_pa"]
        if type(temperature) is not float or not math.isfinite(temperature):
            return False
        if type(pressure) is not float or not math.isfinite(pressure):
            return False
        if not limits_are_exact(recipe.limits):
            return False
        if temperature > recipe.limits.max_temperature_c or pressure > recipe.limits.max_pressure_pa:
            return False

        if type(recipe.surface) is not MappingProxyType or not normalized_json_is_exact(recipe.surface):
            return False
        if recipe.surface.get("model_version") != "site-sequential/1":
            return False

        if type(recipe.instructions) is not tuple or not recipe.instructions:
            return False
        for instruction in recipe.instructions:
            if type(instruction) is not MappingProxyType or set(instruction.keys()) != {"opcode", "arguments"}:
                return False
            opcode = instruction["opcode"]
            arguments = instruction["arguments"]
            if type(opcode) is not str or type(arguments) is not MappingProxyType:
                return False
            if not normalized_json_is_exact(arguments):
                return False
            if not _base._is_exact_packet_arguments(opcode, arguments):
                return False

        raw = {
            "protocol": recipe.protocol,
            "recipe_id": recipe.recipe_id,
            "metadata": thaw_normalized(recipe.metadata),
            "precursors": thaw_normalized(recipe.precursors),
            "initial_conditions": thaw_normalized(recipe.initial_conditions),
            "limits": {
                "min_purge_ms": recipe.limits.min_purge_ms,
                "max_temperature_c": recipe.limits.max_temperature_c,
                "max_pressure_pa": recipe.limits.max_pressure_pa,
                "max_cycles": recipe.limits.max_cycles,
                "max_runtime_ms": recipe.limits.max_runtime_ms,
                "max_residual_fraction": recipe.limits.max_residual_fraction,
                "max_packet_bytes": recipe.limits.max_packet_bytes,
            },
            "surface": thaw_normalized(recipe.surface),
            "instructions": [thaw_normalized(item) for item in recipe.instructions],
        }
        normalized = harden_validated_recipe(original_validate_recipe(raw))
        return (
            normalized.protocol == recipe.protocol
            and normalized.recipe_id == recipe.recipe_id
            and normalized.metadata == recipe.metadata
            and normalized.precursors == recipe.precursors
            and normalized.initial_conditions == recipe.initial_conditions
            and normalized.limits == recipe.limits
            and normalized.surface == recipe.surface
            and normalized.instructions == recipe.instructions
        )
    except Exception:
        return False


def _multi_hardened_handle_fault(self, error) -> None:
    if hasattr(self.chamber, "active_precursor"):
        self.chamber.active_precursor = None
    _ORIGINAL_HARDENED_HANDLE_FAULT(self, error)


# Patch only names looked up dynamically by the already-installed hardening.
_HARDENED_GLOBALS["_recipe_shape_is_trusted"] = _multi_recipe_shape_is_trusted
_base.SimulatedALDController._handle_fault = _multi_hardened_handle_fault

# Keep the established public namespace behavior.
sys.modules[__name__] = _base
