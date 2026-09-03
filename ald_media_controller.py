"""Hardened public boundary for the ALD media-controller core.

The previously reviewed phase-one implementation is preserved in
``_ald_media_controller_base.py``. This module installs the final trust,
fault-containment, descriptor-lifecycle, and CLI error-mapping corrections
without duplicating the large deterministic simulator implementation.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from types import MappingProxyType
from typing import Any

import _ald_media_controller_base as _base


_ORIGINAL_VALIDATE_RECIPE = _base.validate_recipe
_ORIGINAL_VERIFY_COMPILED_INTEGRITY = _base.SimulatedALDController._verify_compiled_integrity
_ORIGINAL_SURFACE_POST_INIT = _base.SurfaceConfig.__post_init__


def _raw_json_is_exact(value: Any) -> bool:
    """Accept only concrete JSON containers and primitive types.

    Finiteness and field semantics remain the original validator's job so its
    precise error classification/messages are preserved.
    """
    if value is None or type(value) in (str, bool, int, float):
        return True
    if type(value) is list:
        return all(_raw_json_is_exact(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _raw_json_is_exact(item) for key, item in value.items())
    return False


def _deep_freeze_validated(value: Any) -> Any:
    """Freeze the exact normalized value shapes emitted by recipe validation."""
    if type(value) is MappingProxyType:
        return MappingProxyType({key: _deep_freeze_validated(item) for key, item in value.items()})
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze_validated(item) for key, item in value.items()})
    if type(value) is tuple:
        return tuple(_deep_freeze_validated(item) for item in value)
    if type(value) is list:
        return tuple(_deep_freeze_validated(item) for item in value)
    return value


def _harden_validated_recipe(recipe):
    """Remove the one remaining mutable nested recipe container."""
    instructions = tuple(
        MappingProxyType(
            {
                "opcode": instruction["opcode"],
                "arguments": _deep_freeze_validated(instruction["arguments"]),
            }
        )
        for instruction in recipe.instructions
    )
    return _base.Recipe(
        protocol=recipe.protocol,
        recipe_id=recipe.recipe_id,
        metadata=_deep_freeze_validated(recipe.metadata),
        precursors=_deep_freeze_validated(recipe.precursors),
        initial_conditions=_deep_freeze_validated(recipe.initial_conditions),
        limits=recipe.limits,
        surface=_deep_freeze_validated(recipe.surface),
        instructions=instructions,
    )


def validate_recipe(raw):
    """Validate only an exact, inert JSON object graph and freeze the result."""
    if type(raw) is not dict or not _raw_json_is_exact(raw):
        raise _base.RecipeError("recipe must contain only plain JSON objects, arrays, and primitives")
    return _harden_validated_recipe(_ORIGINAL_VALIDATE_RECIPE(raw))


def _normalized_json_is_exact(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is tuple:
        return all(_normalized_json_is_exact(item) for item in value)
    if type(value) is MappingProxyType:
        try:
            return all(
                type(key) is str and _normalized_json_is_exact(item)
                for key, item in value.items()
            )
        except Exception:
            return False
    return False


def _limits_are_exact(limits: Any) -> bool:
    if type(limits) is not _base.ProcessLimits:
        return False
    try:
        return (
            type(limits.min_purge_ms) is int
            and limits.min_purge_ms >= 1
            and type(limits.max_temperature_c) is float
            and math.isfinite(limits.max_temperature_c)
            and limits.max_temperature_c > 0
            and type(limits.max_pressure_pa) is float
            and math.isfinite(limits.max_pressure_pa)
            and limits.max_pressure_pa > 0
            and type(limits.max_cycles) is int
            and limits.max_cycles >= 1
            and type(limits.max_runtime_ms) is int
            and limits.max_runtime_ms >= 1
            and type(limits.max_residual_fraction) is float
            and math.isfinite(limits.max_residual_fraction)
            and 0.0 <= limits.max_residual_fraction <= 1.0
            and type(limits.max_packet_bytes) is int
            and 1 <= limits.max_packet_bytes <= 800
        )
    except Exception:
        return False


def _thaw_normalized(value: Any) -> Any:
    if type(value) is MappingProxyType:
        return {key: _thaw_normalized(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_normalized(item) for item in value]
    return value


def _recipe_shape_is_trusted(recipe: Any) -> bool:
    """Validate every recipe-derived value before the controller reads it."""
    if type(recipe) is not _base.Recipe:
        return False
    try:
        if type(recipe.protocol) is not str or recipe.protocol != _base._PROTOCOL:
            return False
        if type(recipe.recipe_id) is not str or not recipe.recipe_id:
            return False
        if type(recipe.metadata) is not MappingProxyType or not _normalized_json_is_exact(recipe.metadata):
            return False
        if type(recipe.precursors) is not MappingProxyType or set(recipe.precursors.keys()) != {"A", "B"}:
            return False
        for name in ("A", "B"):
            precursor = recipe.precursors[name]
            if (
                type(precursor) is not MappingProxyType
                or set(precursor.keys()) != {"label"}
                or type(precursor["label"]) is not str
                or not precursor["label"]
            ):
                return False
        if type(recipe.initial_conditions) is not MappingProxyType:
            return False
        if set(recipe.initial_conditions.keys()) != {"temperature_c", "pressure_pa"}:
            return False
        temperature = recipe.initial_conditions["temperature_c"]
        pressure = recipe.initial_conditions["pressure_pa"]
        if (
            type(temperature) is not float
            or not math.isfinite(temperature)
            or type(pressure) is not float
            or not math.isfinite(pressure)
        ):
            return False
        if not _limits_are_exact(recipe.limits):
            return False
        if temperature > recipe.limits.max_temperature_c or pressure > recipe.limits.max_pressure_pa:
            return False
        if type(recipe.surface) is not MappingProxyType or not _normalized_json_is_exact(recipe.surface):
            return False
        if type(recipe.instructions) is not tuple or not recipe.instructions:
            return False
        for instruction in recipe.instructions:
            if type(instruction) is not MappingProxyType:
                return False
            if set(instruction.keys()) != {"opcode", "arguments"}:
                return False
            opcode = instruction["opcode"]
            arguments = instruction["arguments"]
            if type(opcode) is not str or type(arguments) is not MappingProxyType:
                return False
            if not _normalized_json_is_exact(arguments):
                return False
            # Packet-level shape validation is safe now because all arguments
            # are exact immutable containers/primitives.
            if not _base._is_exact_packet_arguments(opcode, arguments):
                return False

        raw = {
            "protocol": recipe.protocol,
            "recipe_id": recipe.recipe_id,
            "metadata": _thaw_normalized(recipe.metadata),
            "precursors": _thaw_normalized(recipe.precursors),
            "initial_conditions": _thaw_normalized(recipe.initial_conditions),
            "limits": {
                "min_purge_ms": recipe.limits.min_purge_ms,
                "max_temperature_c": recipe.limits.max_temperature_c,
                "max_pressure_pa": recipe.limits.max_pressure_pa,
                "max_cycles": recipe.limits.max_cycles,
                "max_runtime_ms": recipe.limits.max_runtime_ms,
                "max_residual_fraction": recipe.limits.max_residual_fraction,
                "max_packet_bytes": recipe.limits.max_packet_bytes,
            },
            "surface": _thaw_normalized(recipe.surface),
            "instructions": [_thaw_normalized(item) for item in recipe.instructions],
        }
        normalized = _harden_validated_recipe(_ORIGINAL_VALIDATE_RECIPE(raw))
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


def _hardened_start_run(self, compiled, seed):
    """Reset to a safe baseline before dereferencing any recipe-derived field."""
    self._limits = None
    self._surface = None
    self._current_packet = None
    self._fault = None
    self.state = _base.ControllerState.IDLE
    self.chamber = _base.VirtualChamber(
        simulation_time_ms=0,
        temperature_c=25.0,
        pressure_pa=101325.0,
    )
    self._audit = []
    self._cycles = []
    self._last_verified_digest = bytes(32)
    self._temperature_target = None
    self._temperature_tolerance = 0.0
    self._cycle_index = 0
    self._shutdown_completed = False
    self._compiled_protocol = _base._PROTOCOL
    self._compiled_recipe_id = ""

    try:
        recipe = compiled.recipe
    except Exception as error:
        raise _base.ControllerFault("COMPILED_PACKET_STREAM_MISMATCH") from error
    if not _recipe_shape_is_trusted(recipe):
        raise _base.ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")

    self._compiled_protocol = recipe.protocol
    self._compiled_recipe_id = recipe.recipe_id
    self.chamber = _base.VirtualChamber(
        simulation_time_ms=0,
        temperature_c=recipe.initial_conditions["temperature_c"],
        pressure_pa=recipe.initial_conditions["pressure_pa"],
    )
    self._limits = recipe.limits


def _hardened_verify_compiled_integrity(self, compiled):
    try:
        recipe = compiled.recipe
    except Exception as error:
        self._current_packet = None
        raise _base.ControllerFault("COMPILED_PACKET_STREAM_MISMATCH") from error
    if not _recipe_shape_is_trusted(recipe):
        self._current_packet = None
        raise _base.ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
    return _ORIGINAL_VERIFY_COMPILED_INTEGRITY(self, compiled)


def _strict_surface_post_init(self) -> None:
    """Reject primitive subclasses while preserving list-to-tuple normalization."""
    if type(self.model_version) is not str or not self.model_version:
        raise _base.SurfaceModelError("model_version must be a non-empty string")
    if type(self.regions) is not int or self.regions <= 0:
        raise _base.SurfaceModelError("regions must be a positive integer")
    if type(self.sites_per_region) is not int or self.sites_per_region <= 0:
        raise _base.SurfaceModelError("sites_per_region must be a positive integer")
    if type(self.transport_factors) not in (list, tuple):
        raise _base.SurfaceModelError("transport_factors must be a plain list or tuple")
    if any(type(value) not in (int, float) for value in self.transport_factors):
        raise _base.SurfaceModelError("transport_factors must contain plain numbers")
    for field in (
        "blocked_fraction",
        "defect_fraction",
        "k_a",
        "k_b",
        "growth_nm_per_reaction_fraction",
    ):
        if type(getattr(self, field)) not in (int, float):
            raise _base.SurfaceModelError(f"{field} must be a plain number")
    if type(self.purge_half_life_ms) is not int:
        raise _base.SurfaceModelError("purge_half_life_ms must be a plain integer")
    _ORIGINAL_SURFACE_POST_INIT(self)


def _hardened_handle_fault(self, error) -> None:
    """Make the fault boundary non-throwing even if simulated shutdown fails."""
    packet_sequence = self._fault_packet_sequence()
    fault_state = self.state
    self.chamber.valve_a_open = False
    self.chamber.valve_b_open = False
    self._fault = _base.FaultRecord(
        code=error.code,
        packet_sequence=packet_sequence,
        state=fault_state,
        last_verified_digest=self._last_verified_digest,
        chamber=self._chamber_snapshot(),
        interlocks=self.interlocks,
    )

    try:
        if self.state is not _base.ControllerState.FAULT:
            self.transition(
                _base.ControllerState.FAULT,
                packet_sequence=packet_sequence,
                event_type="FAULT",
                details={"code": error.code},
            )
    except BaseException:
        self.state = _base.ControllerState.FAULT

    try:
        self.transition(
            _base.ControllerState.SHUTDOWN,
            packet_sequence=packet_sequence,
            event_type="SHUTDOWN",
        )
    except BaseException:
        self.state = _base.ControllerState.SHUTDOWN

    shutdown_error: BaseException | None = None
    try:
        self._shutdown(20.0, self._safe_shutdown_pressure())
    except BaseException as caught:
        shutdown_error = caught
    finally:
        self.chamber.valve_a_open = False
        self.chamber.valve_b_open = False
        self.chamber.inert_purge_open = False
        self.chamber.pump_on = False
        self.state = _base.ControllerState.IDLE

    try:
        details = {"primary_fault": error.code}
        if shutdown_error is not None:
            details["shutdown_error"] = type(shutdown_error).__name__
        self._record(
            "SHUTDOWN_COMPLETE" if shutdown_error is None else "SHUTDOWN_FAULT_CONTAINED",
            packet_sequence,
            details,
        )
    except BaseException:
        pass


def _owned_directory_close(self) -> None:
    fd = self.fd
    if fd < 0:
        return
    self.fd = -1
    _base.os.close(fd)


def _owned_fd_close(self) -> None:
    fd = self.fd
    if fd < 0:
        return
    self.fd = -1
    _base.os.close(fd)


def _publisher_lock_close(self) -> None:
    fd = self.fd
    if fd < 0:
        return
    self.fd = -1
    # close(2) itself releases an flock lock; an explicit LOCK_UN creates a
    # failure point that can strand a live lock before descriptor teardown.
    _base.os.close(fd)


def _finalize_close(resource: Any, *, defer: bool = True) -> bool:
    """Finalize one owner without retrying a relinquished descriptor number."""
    if resource is None or getattr(resource, "fd", -1) < 0:
        return True
    try:
        resource.close()
    except BaseException:
        return getattr(resource, "fd", -1) < 0
    return True


def _drain_deferred_closes() -> None:
    _base._DEFERRED_CLOSES.clear()


def _open_parent_directory(path):
    """Open/create parents while transferring fd ownership exactly once."""
    if not sys.platform.startswith("linux") or not os.path.isabs(os.fspath(path)):
        raise _base.OutputError("descriptor-relative publication requires an absolute Linux path")
    absolute = _base.Path(os.path.abspath(os.fspath(path)))
    name = os.fsencode(absolute.name)
    components = [part for part in absolute.parts[1:-1] if part]
    current = None
    try:
        try:
            current = _base._OwnedFD(os.open("/", _base._DIR_FLAGS))
        except OSError as error:
            raise _base.OutputError(f"unable to open publication root: {error}") from error

        for component in components:
            component_bytes = os.fsencode(component)
            try:
                next_fd = os.open(component_bytes, _base._DIR_FLAGS, dir_fd=current.fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component_bytes, 0o700, dir_fd=current.fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component_bytes, _base._DIR_FLAGS, dir_fd=current.fd)
            next_owner = _base._OwnedFD(next_fd)
            try:
                current.close()
            except BaseException:
                _finalize_close(next_owner)
                raise
            current = next_owner

        opened = _base._OwnedDirectory.from_fd(current.fd)
        current.fd = -1
        return opened, name
    except BaseException as error:
        if current is not None:
            _finalize_close(current)
        if isinstance(error, _base.OutputError):
            raise
        raise _base.OutputError(f"unable to open publication parent: {error}") from error


class DependencyError(_base.ALDError):
    """Explicit missing/unsupported runtime dependency failure."""

    exit_code = _base.ExitCode.DEPENDENCY


def _emit_cli_error(error: BaseException, exit_code) -> int:
    payload = {
        "error": {
            "type": type(error).__name__,
            "code": exit_code.name,
            "exit_code": int(exit_code),
            "message": str(error),
        }
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
    return int(exit_code)


def main(argv=None) -> int:
    parser = _base.build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else int(_base.ExitCode.USAGE)
    except _base.ALDError as error:
        return _emit_cli_error(error, error.exit_code)

    log_level = getattr(arguments, "log_level", getattr(arguments, "global_log_level", "INFO"))
    try:
        if arguments.command == "validate":
            return _base._run_validate(arguments.recipe)
        if arguments.command == "simulate":
            return _base._run_simulate(
                arguments.recipe,
                arguments.seed,
                arguments.output,
                arguments.overwrite,
            )
        raise _base.ALDError(f"unsupported command: {arguments.command}")
    except _base.ALDError as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        return _emit_cli_error(error, error.exit_code)
    except Exception as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        exit_code = (
            _base.ExitCode.RECIPE
            if arguments.command == "validate"
            else _base.ExitCode.CONTROLLER
            if arguments.command == "simulate"
            else _base.ExitCode.USAGE
        )
        return _emit_cli_error(error, exit_code)


_base.validate_recipe = validate_recipe
_base.SimulatedALDController._start_run = _hardened_start_run
_base.SimulatedALDController._verify_compiled_integrity = _hardened_verify_compiled_integrity
_base.SimulatedALDController._handle_fault = _hardened_handle_fault
_base.SurfaceConfig.__post_init__ = _strict_surface_post_init
_base._OwnedDirectory.close = _owned_directory_close
_base._OwnedFD.close = _owned_fd_close
_base._PublisherLock.close = _publisher_lock_close
_base._finalize_close = _finalize_close
_base._drain_deferred_closes = _drain_deferred_closes
_base._open_parent_directory = _open_parent_directory
_base.DependencyError = DependencyError
_base.main = main

if __name__ == "__main__":
    raise SystemExit(_base.main())

# Preserve the original module object as the public namespace so monkeypatches
# in the existing regression suite target the same globals used internally.
sys.modules[__name__] = _base
