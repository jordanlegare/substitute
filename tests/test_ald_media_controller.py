"""Core regression suite plus final hardening findings.

The original 87-test checkpoint is preserved in ``_ald_core_tests_base.py``.
This module re-exports that suite, replaces the descriptor-lifecycle tests
whose old expectations were unsafe, and adds the final review regressions.
"""

from _ald_core_tests_base import *  # noqa: F401,F403

from dataclasses import replace
import json
import os
from types import MappingProxyType

import pytest

import ald_media_controller as controller_module
from ald_media_controller import (
    ControllerFault,
    ExitCode,
    Interlocks,
    OutputError,
    SimulatedALDController,
)


class HostileInt(int):
    """An int subclass that must never cross a normalized recipe boundary."""


class ExplodingInitialConditions(dict):
    """Detect whether untrusted initial conditions are read before preflight."""

    accessed = False

    def __getitem__(self, key):
        self.accessed = True
        raise AssertionError("untrusted initial conditions were dereferenced")


def test_preflight_rejects_untrusted_initial_conditions_before_access(compiled_recipe):
    hostile = ExplodingInitialConditions(compiled_recipe.recipe.initial_conditions)
    forged_recipe = replace(compiled_recipe.recipe, initial_conditions=hostile)
    forged = replace(compiled_recipe, recipe=forged_recipe)

    result = SimulatedALDController().execute(forged, seed=42)

    assert hostile.accessed is False
    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.final_state.value == "IDLE"
    assert result.surface.total_sites == 0


def test_preflight_rejects_forged_process_limit_primitives(compiled_recipe):
    forged_limits = replace(compiled_recipe.recipe.limits, max_runtime_ms=True)
    forged_recipe = replace(compiled_recipe.recipe, limits=forged_limits)
    forged = replace(compiled_recipe, recipe=forged_recipe)

    result = SimulatedALDController().execute(forged, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.surface.total_sites == 0


def test_preflight_rejects_surface_primitive_subclasses(compiled_recipe):
    surface = dict(compiled_recipe.recipe.surface)
    surface["regions"] = HostileInt(surface.get("regions", 1))
    forged_recipe = replace(compiled_recipe.recipe, surface=MappingProxyType(surface))
    forged = replace(compiled_recipe, recipe=forged_recipe)

    result = SimulatedALDController().execute(forged, seed=42)

    assert result.fault is not None
    assert result.fault.code == "COMPILED_PACKET_STREAM_MISMATCH"
    assert result.surface.total_sites == 0


def test_fault_shutdown_failure_is_contained_and_returns_idle(compiled_recipe, monkeypatch):
    controller = SimulatedALDController(interlocks=Interlocks(vacuum_available=False))

    def fail_shutdown(*_args, **_kwargs):
        raise ControllerFault("INJECTED_SHUTDOWN_FAILURE")

    monkeypatch.setattr(controller, "_shutdown", fail_shutdown)

    result = controller.execute(compiled_recipe, seed=42)

    assert result.fault is not None
    assert result.fault.code == "VACUUM_UNAVAILABLE"
    assert result.final_state.value == "IDLE"
    assert result.chamber.valve_a_open is False
    assert result.chamber.valve_b_open is False
    assert result.chamber.inert_purge_open is False
    assert result.chamber.pump_on is False


# Replaces the old test that required retaining a numeric fd after close()
# raised. POSIX/Linux may release the descriptor even when close reports an
# error, so retaining the number makes a retry capable of closing an unrelated
# descriptor that reused the same number.
def test_owned_directory_close_failure_preserves_fd_until_retry(monkeypatch, tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    owned = controller_module._OwnedDirectory.from_fd(fd)
    real_close = os.close
    sentinel_fd = None
    injected = False

    def close_then_report_failure(candidate):
        nonlocal sentinel_fd, injected
        if candidate == fd and not injected:
            injected = True
            real_close(candidate)
            sentinel_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            assert sentinel_fd == fd
            raise OSError("injected post-close failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module.os, "close", close_then_report_failure)
    try:
        with pytest.raises(OSError, match="post-close failure"):
            owned.close()
        assert owned.fd == -1
        owned.close()  # must be a no-op; never close the reused descriptor
        assert os.fstat(sentinel_fd)
    finally:
        monkeypatch.setattr(controller_module.os, "close", real_close)
        if sentinel_fd is not None:
            try:
                real_close(sentinel_fd)
            except OSError:
                pass


def test_publisher_lock_close_does_not_require_explicit_unlock(monkeypatch, tmp_path):
    parent, _ = controller_module._open_parent_directory(tmp_path / "output")
    lock = controller_module._open_publisher_lock(parent)
    lock_fd = lock.fd
    real_flock = controller_module.fcntl.flock

    def reject_unlock(candidate, operation):
        if operation == controller_module.fcntl.LOCK_UN:
            raise OSError("explicit unlock must not be required")
        return real_flock(candidate, operation)

    monkeypatch.setattr(controller_module.fcntl, "flock", reject_unlock)
    try:
        lock.close()
        assert lock.fd == -1
        with pytest.raises(OSError):
            os.fstat(lock_fd)
    finally:
        controller_module._close_quietly(parent)


# Replace retry/deferred-close tests from the checkpoint. The safe invariant
# is ownership invalidation before close, not blind retry of the numeric fd.
def test_one_shot_lock_close_failure_is_retried_on_success(monkeypatch, compiled_recipe, tmp_path):
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    real_close = os.close
    lock_fd = None
    sentinel_fd = None
    injected = False

    def observe_lock(parent):
        nonlocal lock_fd
        lock = original_open_lock(parent)
        lock_fd = lock.fd
        return lock

    def close_then_report_failure(candidate):
        nonlocal sentinel_fd, injected
        if lock_fd is not None and candidate == lock_fd and not injected:
            injected = True
            real_close(candidate)
            sentinel_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            assert sentinel_fd == lock_fd
            raise OSError("injected post-close failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    monkeypatch.setattr(controller_module.os, "close", close_then_report_failure)
    try:
        publish_reports(result, tmp_path / "first")
        assert injected
        assert os.fstat(sentinel_fd)
        assert controller_module._DEFERRED_CLOSES == []
    finally:
        monkeypatch.setattr(controller_module.os, "close", real_close)
        if sentinel_fd is not None:
            try:
                real_close(sentinel_fd)
            except OSError:
                pass


def test_one_shot_lock_close_failure_does_not_mask_error_cleanup(monkeypatch, compiled_recipe, tmp_path):
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    real_close = os.close
    lock_fd = None
    sentinel_fd = None
    injected = False

    def observe_lock(parent):
        nonlocal lock_fd
        lock = original_open_lock(parent)
        lock_fd = lock.fd
        return lock

    def close_then_report_failure(candidate):
        nonlocal sentinel_fd, injected
        if lock_fd is not None and candidate == lock_fd and not injected:
            injected = True
            real_close(candidate)
            sentinel_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            assert sentinel_fd == lock_fd
            raise OSError("injected post-close failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    monkeypatch.setattr(
        controller_module,
        "_write_cycles_fd",
        lambda *args: (_ for _ in ()).throw(OutputError("injected report failure")),
    )
    monkeypatch.setattr(controller_module.os, "close", close_then_report_failure)
    try:
        with pytest.raises(OutputError, match="injected report failure"):
            publish_reports(result, tmp_path / "error")
        assert injected
        assert os.fstat(sentinel_fd)
        assert controller_module._DEFERRED_CLOSES == []
    finally:
        monkeypatch.setattr(controller_module.os, "close", real_close)
        if sentinel_fd is not None:
            try:
                real_close(sentinel_fd)
            except OSError:
                pass


def test_persistent_close_failure_is_deferred_until_next_publication(monkeypatch, compiled_recipe, tmp_path):
    """A post-close error must never retain a retryable numeric descriptor."""
    result = SimulatedALDController().execute(compiled_recipe, seed=42)
    original_open_lock = controller_module._open_publisher_lock
    real_close = os.close
    lock_fd = None
    sentinel_fd = None
    injected = False

    def observe_lock(parent):
        nonlocal lock_fd
        lock = original_open_lock(parent)
        lock_fd = lock.fd
        return lock

    def close_then_report_failure(candidate):
        nonlocal sentinel_fd, injected
        if lock_fd is not None and candidate == lock_fd and not injected:
            injected = True
            real_close(candidate)
            sentinel_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            assert sentinel_fd == lock_fd
            raise OSError("persistent-looking post-close failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module, "_open_publisher_lock", observe_lock)
    monkeypatch.setattr(controller_module.os, "close", close_then_report_failure)
    try:
        publish_reports(result, tmp_path / "persistent")
        assert os.fstat(sentinel_fd)
        assert controller_module._DEFERRED_CLOSES == []
    finally:
        monkeypatch.setattr(controller_module.os, "close", real_close)
        if sentinel_fd is not None:
            try:
                real_close(sentinel_fd)
            except OSError:
                pass


def test_parent_directory_close_error_cannot_close_reused_fd(monkeypatch, tmp_path):
    real_close = os.close
    injected = False
    sentinel_fd = None
    released_fd = None

    def close_then_reuse(candidate):
        nonlocal injected, sentinel_fd, released_fd
        if not injected:
            injected = True
            released_fd = candidate
            real_close(candidate)
            sentinel_fd = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            assert sentinel_fd == released_fd
            raise OSError("injected post-close parent failure")
        return real_close(candidate)

    monkeypatch.setattr(controller_module.os, "close", close_then_reuse)
    try:
        with pytest.raises(OutputError, match="unable to open publication parent"):
            controller_module._open_parent_directory(tmp_path / "nested" / "output")
        assert os.fstat(sentinel_fd)
    finally:
        monkeypatch.setattr(controller_module.os, "close", real_close)
        if sentinel_fd is not None:
            try:
                real_close(sentinel_fd)
            except OSError:
                pass


def test_unexpected_validate_failure_is_not_reported_as_dependency(monkeypatch, tmp_path, capsys):
    def explode(_path):
        raise RuntimeError("injected implementation failure")

    monkeypatch.setattr(controller_module, "_run_validate", explode)

    status = controller_module.main(["validate", str(tmp_path / "recipe.json")])
    payload = json.loads(capsys.readouterr().err)

    assert status == ExitCode.RECIPE
    assert payload["error"]["code"] == "RECIPE"
    assert payload["error"]["code"] != "DEPENDENCY"
