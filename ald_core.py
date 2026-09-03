"""Command-line boundary for the ALD media controller simulator."""

import argparse
import csv
from collections.abc import Mapping
import ctypes
from dataclasses import dataclass
from enum import Enum, IntEnum
import errno
try:
    import fcntl
except ImportError:  # pragma: no cover - publication is Linux-only
    fcntl = None  # type: ignore[assignment]
import hashlib
import io
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import traceback
from types import MappingProxyType
from typing import Any, Sequence, TypeAlias

import numpy as np


class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    RECIPE = 3
    LIMIT = 4
    MEDIA = 5
    FRAME = 6
    AUDIO = 7
    SYNC = 8
    INTEGRITY = 9
    CONTROLLER = 10
    SURFACE = 11
    OUTPUT = 12
    DEPENDENCY = 13


class ALDError(Exception):
    exit_code = ExitCode.USAGE


class RecipeError(ALDError):
    exit_code = ExitCode.RECIPE


class RecipeLimitError(RecipeError):
    exit_code = ExitCode.LIMIT


class OutputError(ALDError):
    """Raised when report output cannot be published safely."""

    exit_code = ExitCode.OUTPUT


class SurfaceModelError(ALDError):
    """Raised when deterministic surface-model inputs or invariants are invalid."""

    exit_code = ExitCode.SURFACE


class ControllerFault(ALDError):
    """Raised internally when the simulated chamber must fail closed."""

    exit_code = ExitCode.CONTROLLER

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

_PROTOCOL = "ALD-MEDIA/1"
_MAX_CANONICAL_PACKET_BYTES = 800
_TOP_LEVEL_KEYS = frozenset(
    {
        "protocol",
        "recipe_id",
        "metadata",
        "precursors",
        "initial_conditions",
        "limits",
        "surface",
        "instructions",
    }
)
_LIMIT_KEYS = frozenset(
    {
        "min_purge_ms",
        "max_temperature_c",
        "max_pressure_pa",
        "max_cycles",
        "max_runtime_ms",
        "max_residual_fraction",
        "max_packet_bytes",
    }
)
_REQUIRED_LIMIT_KEYS = _LIMIT_KEYS - {"max_packet_bytes"}
_INITIAL_CONDITION_KEYS = frozenset({"temperature_c", "pressure_pa"})
_MEASUREMENTS = frozenset({"thickness_nm", "coverage", "defect_fraction"})


@dataclass(frozen=True)
class ProcessLimits:
    min_purge_ms: int
    max_temperature_c: float
    max_pressure_pa: float
    max_cycles: int
    max_runtime_ms: int
    max_residual_fraction: float
    max_packet_bytes: int = _MAX_CANONICAL_PACKET_BYTES


@dataclass(frozen=True)
class Recipe:
    protocol: str
    recipe_id: str
    metadata: Mapping[str, JSONValue]
    precursors: Mapping[str, Mapping[str, JSONValue]]
    initial_conditions: Mapping[str, float]
    limits: ProcessLimits
    surface: Mapping[str, JSONValue]
    instructions: tuple[Mapping[str, JSONValue], ...]


@dataclass(frozen=True)
class Packet:
    protocol: str
    recipe_id: str
    sequence: int
    opcode: str
    arguments: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        protocol = _require_string(self.protocol, "packet protocol")
        if protocol != _PROTOCOL:
            raise RecipeError("packet protocol must be ALD-MEDIA/1")
        _require_string(self.recipe_id, "packet recipe_id")
        _require_integer(self.sequence, "sequence", minimum=0)
        opcode = _require_string(self.opcode, "packet opcode")
        object.__setattr__(self, "arguments", _freeze_json(_validate_packet_arguments(opcode, self.arguments)))


@dataclass(frozen=True)
class HashedPacket:
    packet: Packet
    canonical_bytes: bytes
    previous_digest: bytes
    digest: bytes


@dataclass(frozen=True)
class CompiledRecipe:
    recipe: Recipe
    packets: tuple[HashedPacket, ...]
    root_hash: bytes


@dataclass(frozen=True)
class SurfaceConfig:
    """Static parameters for the aggregate, region-based surface model."""

    model_version: str
    regions: int
    sites_per_region: int
    transport_factors: tuple[float, ...]
    blocked_fraction: float
    defect_fraction: float
    k_a: float
    k_b: float
    growth_nm_per_reaction_fraction: float
    purge_half_life_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.model_version, str) or not self.model_version:
            raise SurfaceModelError("model_version must be a non-empty string")
        for value, field in ((self.regions, "regions"), (self.sites_per_region, "sites_per_region")):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SurfaceModelError(f"{field} must be a positive integer")
        try:
            if isinstance(self.transport_factors, (str, bytes)):
                raise TypeError
            transport_factors = tuple(self.transport_factors)
        except Exception as error:
            raise SurfaceModelError("transport_factors must be an iterable of finite numbers") from error
        if len(transport_factors) != self.regions:
            raise SurfaceModelError("transport_factors must have one value per region")
        for value, field in (
            (self.blocked_fraction, "blocked_fraction"),
            (self.defect_fraction, "defect_fraction"),
            (self.k_a, "k_a"),
            (self.k_b, "k_b"),
            (self.growth_nm_per_reaction_fraction, "growth_nm_per_reaction_fraction"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise SurfaceModelError(f"{field} must be finite and non-negative")
        if self.blocked_fraction + self.defect_fraction > 1:
            raise SurfaceModelError("blocked_fraction and defect_fraction must sum to at most one")
        for value in transport_factors:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise SurfaceModelError("transport_factors must be finite and non-negative")
        object.__setattr__(self, "transport_factors", transport_factors)
        if (
            isinstance(self.purge_half_life_ms, bool)
            or not isinstance(self.purge_half_life_ms, int)
            or self.purge_half_life_ms <= 0
        ):
            raise SurfaceModelError("purge_half_life_ms must be a positive integer")


@dataclass
class SurfaceRegion:
    vacant: int
    a_terminated: int
    b_reacted: int
    blocked: int
    defects: int
    residual_a: float = 0.0
    residual_b: float = 0.0

    @property
    def total_sites(self) -> int:
        return self.vacant + self.a_terminated + self.b_reacted + self.blocked + self.defects


@dataclass(frozen=True)
class SurfaceRegionSnapshot:
    vacant: int
    a_terminated: int
    b_reacted: int
    blocked: int
    defects: int
    residual_a: float
    residual_b: float

    @property
    def total_sites(self) -> int:
        return self.vacant + self.a_terminated + self.b_reacted + self.blocked + self.defects


@dataclass(frozen=True)
class EventSample:
    cycle: int
    half_reaction: str
    region: int
    source_state: str
    destination_state: str
    sample_id: str


@dataclass(frozen=True)
class ExposureResult:
    cycle: int
    half_reaction: str
    dose: float
    reactions_by_region: tuple[int, ...]
    event_samples: tuple[EventSample, ...]

    @property
    def total_reactions(self) -> int:
        return sum(self.reactions_by_region)


@dataclass(frozen=True)
class SurfaceSnapshot:
    regions: tuple[SurfaceRegionSnapshot, ...]
    total_sites: int
    vacant: int
    a_terminated: int
    b_reacted: int
    blocked: int
    defects: int
    residual_a: float
    residual_b: float
    coverage: float
    thickness_nm: float
    utilization: float
    defect_fraction: float
    completed_b_reactions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "regions": [
                {
                    "vacant": region.vacant,
                    "a_terminated": region.a_terminated,
                    "b_reacted": region.b_reacted,
                    "blocked": region.blocked,
                    "defects": region.defects,
                    "residual_a": region.residual_a,
                    "residual_b": region.residual_b,
                }
                for region in self.regions
            ],
            "total_sites": self.total_sites,
            "vacant": self.vacant,
            "a_terminated": self.a_terminated,
            "b_reacted": self.b_reacted,
            "blocked": self.blocked,
            "defects": self.defects,
            "residual_a": self.residual_a,
            "residual_b": self.residual_b,
            "coverage": self.coverage,
            "thickness_nm": self.thickness_nm,
            "utilization": self.utilization,
            "defect_fraction": self.defect_fraction,
            "completed_b_reactions": self.completed_b_reactions,
        }


def _empty_surface_snapshot() -> SurfaceSnapshot:
    """Return an explicitly unseeded surface for preflight failures."""
    return SurfaceSnapshot(
        regions=(),
        total_sites=0,
        vacant=0,
        a_terminated=0,
        b_reacted=0,
        blocked=0,
        defects=0,
        residual_a=0.0,
        residual_b=0.0,
        coverage=0.0,
        thickness_nm=0.0,
        utilization=0.0,
        defect_fraction=0.0,
        completed_b_reactions=0,
    )


def reaction_probability(rate: float, dose: float) -> float:
    """Return the numerically stable binomial reaction probability for an exposure."""
    if (
        isinstance(rate, bool)
        or isinstance(dose, bool)
        or not isinstance(rate, (int, float))
        or not isinstance(dose, (int, float))
        or not math.isfinite(rate)
        or not math.isfinite(dose)
        or rate < 0
        or dose < 0
    ):
        raise SurfaceModelError("rate and dose must be finite and non-negative")
    return -math.expm1(-rate * dose)


def reaction_rng(
    root_hash: bytes,
    model_version: str,
    seed: int,
    cycle: int,
    half_reaction: str,
    region: int,
) -> np.random.Generator:
    """Create the aggregate reaction stream for one region and half-reaction."""
    material = _rng_material(root_hash, model_version, seed, cycle, half_reaction, region, "reaction")
    entropy = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
    return np.random.Generator(np.random.PCG64(entropy))


def _sample_rng(
    root_hash: bytes,
    model_version: str,
    seed: int,
    cycle: int,
    half_reaction: str,
    region: int,
) -> np.random.Generator:
    """Create an independent display-only stream; it never draws aggregate outcomes."""
    material = _rng_material(root_hash, model_version, seed, cycle, half_reaction, region, "sample")
    entropy = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
    return np.random.Generator(np.random.PCG64(entropy))


def _rng_material(
    root_hash: bytes,
    model_version: str,
    seed: int,
    cycle: int,
    half_reaction: str,
    region: int,
    domain: str,
) -> bytes:
    """Length-prefix every RNG component so embedded delimiters cannot collide."""
    if not isinstance(root_hash, bytes) or len(root_hash) != 32:
        raise SurfaceModelError("root_hash must be 32 bytes")
    for value, field in ((seed, "seed"), (cycle, "cycle"), (region, "region")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SurfaceModelError(f"{field} must be a non-negative integer")
    for value, field in (
        (model_version, "model_version"),
        (half_reaction, "half_reaction"),
        (domain, "domain"),
    ):
        if not isinstance(value, str) or not value:
            raise SurfaceModelError(f"{field} must be a non-empty string")
    try:
        components = (
            root_hash,
            model_version.encode("utf-8"),
            str(seed).encode("ascii"),
            str(cycle).encode("ascii"),
            half_reaction.encode("utf-8"),
            str(region).encode("ascii"),
            domain.encode("utf-8"),
        )
    except UnicodeError as error:
        raise SurfaceModelError("RNG string components must be valid UTF-8") from error
    material = bytearray(b"ALD-SURFACE-RNG/1")
    for component in components:
        material.extend(len(component).to_bytes(8, "big"))
        material.extend(component)
    return bytes(material)


def decay_residual(value: float, duration_ms: int, half_life_ms: int) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or isinstance(duration_ms, bool)
        or not isinstance(duration_ms, int)
        or isinstance(half_life_ms, bool)
        or not isinstance(half_life_ms, int)
        or duration_ms < 0
        or half_life_ms <= 0
    ):
        raise SurfaceModelError("invalid purge timing")
    return value * math.exp(-math.log(2.0) * duration_ms / half_life_ms)


class SurfaceModel:
    """A deterministic, aggregate site-population model for generic A/B ALD cycles."""

    def __init__(
        self,
        config: SurfaceConfig,
        root_hash: bytes,
        user_seed: int,
        max_event_samples: int = 0,
    ) -> None:
        if not isinstance(config, SurfaceConfig):
            raise SurfaceModelError("config must be a SurfaceConfig")
        if not isinstance(root_hash, bytes) or len(root_hash) != 32:
            raise SurfaceModelError("root_hash must be 32 bytes")
        if isinstance(user_seed, bool) or not isinstance(user_seed, int):
            raise SurfaceModelError("user_seed must be an integer")
        if (
            isinstance(max_event_samples, bool)
            or not isinstance(max_event_samples, int)
            or max_event_samples < 0
        ):
            raise SurfaceModelError("max_event_samples must be a non-negative integer")
        self.config = config
        self.root_hash = root_hash
        self.user_seed = user_seed
        self.max_event_samples = max_event_samples
        blocked, defects = _apportion_unavailable_sites(config)
        vacant = config.sites_per_region - blocked - defects
        self._regions = [
            SurfaceRegion(vacant=vacant, a_terminated=0, b_reacted=0, blocked=blocked, defects=defects)
            for _ in range(config.regions)
        ]
        self._completed_b_reactions = 0
        self._assert_all_regions_conserved()

    @property
    def total_sites(self) -> int:
        return self.config.regions * self.config.sites_per_region

    def expose_a(self, cycle: int, dose: float) -> ExposureResult:
        return self._expose(cycle, dose, "A")

    def expose_b(self, cycle: int, dose: float) -> ExposureResult:
        return self._expose(cycle, dose, "B")

    def _expose(self, cycle: int, dose: float, half_reaction: str) -> ExposureResult:
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
            raise SurfaceModelError("cycle must be a non-negative integer")
        if (
            isinstance(dose, bool)
            or not isinstance(dose, (int, float))
            or not math.isfinite(dose)
            or dose < 0
        ):
            raise SurfaceModelError("dose must be finite and non-negative")
        reactions_by_region: list[int] = []
        sources: list[tuple[int, int]] = []
        for index, region in enumerate(self._regions):
            probability = reaction_probability(
                self.config.k_a if half_reaction == "A" else self.config.k_b,
                float(dose) * self.config.transport_factors[index],
            )
            rng = reaction_rng(
                self.root_hash, self.config.model_version, self.user_seed, cycle, half_reaction, index
            )
            if half_reaction == "A":
                # A can react both fresh vacant sites and sites left B-reacted by a prior cycle.
                eligible = region.vacant + region.b_reacted
                reactions = int(rng.binomial(eligible, probability))
                from_vacant = (
                    reactions
                    if region.b_reacted == 0
                    else int(rng.hypergeometric(region.vacant, region.b_reacted, reactions))
                )
                from_b_reacted = reactions - from_vacant
                region.vacant -= from_vacant
                region.b_reacted -= from_b_reacted
                region.a_terminated += reactions
                region.residual_a += float(dose)
                sources.append((from_vacant, from_b_reacted))
            else:
                eligible = region.a_terminated
                reactions = int(rng.binomial(eligible, probability))
                region.a_terminated -= reactions
                region.b_reacted += reactions
                region.residual_b += float(dose)
                self._completed_b_reactions += reactions
                sources.append((reactions, 0))
            reactions_by_region.append(reactions)
            self._assert_region_conserved(region)
        return ExposureResult(
            cycle=cycle,
            half_reaction=half_reaction,
            dose=float(dose),
            reactions_by_region=tuple(reactions_by_region),
            event_samples=self._event_samples(cycle, half_reaction, reactions_by_region, sources),
        )

    def _event_samples(
        self,
        cycle: int,
        half_reaction: str,
        reactions_by_region: Sequence[int],
        sources: Sequence[tuple[int, int]],
    ) -> tuple[EventSample, ...]:
        remaining = self.max_event_samples
        samples: list[EventSample] = []
        destination = "a_terminated" if half_reaction == "A" else "b_reacted"
        for region_index, reactions in enumerate(reactions_by_region):
            if remaining == 0:
                break
            sample_count = min(remaining, reactions)
            if sample_count == 0:
                continue
            sample_rng = _sample_rng(
                self.root_hash,
                self.config.model_version,
                self.user_seed,
                cycle,
                half_reaction,
                region_index,
            )
            sampled_indices = sample_rng.choice(reactions, size=sample_count, replace=False)
            first_source_count, _ = sources[region_index]
            for sampled_index in sorted(int(index) for index in sampled_indices):
                source = "vacant" if half_reaction == "A" and sampled_index < first_source_count else (
                    "b_reacted" if half_reaction == "A" else "a_terminated"
                )
                samples.append(
                    EventSample(
                        cycle=cycle,
                        half_reaction=half_reaction,
                        region=region_index,
                        source_state=source,
                        destination_state=destination,
                        sample_id=f"{region_index}:{sampled_index}",
                    )
                )
            remaining -= sample_count
        return tuple(samples)

    def purge(self, duration_ms: int, half_life_ms: int | None = None) -> None:
        half_life = self.config.purge_half_life_ms if half_life_ms is None else half_life_ms
        for region in self._regions:
            region.residual_a = decay_residual(region.residual_a, duration_ms, half_life)
            region.residual_b = decay_residual(region.residual_b, duration_ms, half_life)

    def snapshot(self) -> SurfaceSnapshot:
        self._assert_all_regions_conserved()
        regions = tuple(
            SurfaceRegionSnapshot(
                vacant=region.vacant,
                a_terminated=region.a_terminated,
                b_reacted=region.b_reacted,
                blocked=region.blocked,
                defects=region.defects,
                residual_a=region.residual_a,
                residual_b=region.residual_b,
            )
            for region in self._regions
        )
        vacant = sum(region.vacant for region in self._regions)
        a_terminated = sum(region.a_terminated for region in self._regions)
        b_reacted = sum(region.b_reacted for region in self._regions)
        blocked = sum(region.blocked for region in self._regions)
        defects = sum(region.defects for region in self._regions)
        reactive_sites = self.total_sites - blocked - defects
        return SurfaceSnapshot(
            regions=regions,
            total_sites=self.total_sites,
            vacant=vacant,
            a_terminated=a_terminated,
            b_reacted=b_reacted,
            blocked=blocked,
            defects=defects,
            residual_a=sum(region.residual_a for region in self._regions),
            residual_b=sum(region.residual_b for region in self._regions),
            coverage=b_reacted / reactive_sites if reactive_sites else 0.0,
            thickness_nm=(
                self._completed_b_reactions / self.total_sites * self.config.growth_nm_per_reaction_fraction
            ),
            utilization=self._completed_b_reactions / reactive_sites if reactive_sites else 0.0,
            defect_fraction=defects / self.total_sites,
            completed_b_reactions=self._completed_b_reactions,
        )

    def _assert_all_regions_conserved(self) -> None:
        for region in self._regions:
            self._assert_region_conserved(region)

    def _assert_region_conserved(self, region: SurfaceRegion) -> None:
        if region.total_sites != self.config.sites_per_region:
            raise SurfaceModelError("surface region site count is not conserved")
        if min(region.vacant, region.a_terminated, region.b_reacted, region.blocked, region.defects) < 0:
            raise SurfaceModelError("surface region contains a negative site count")


def _apportion_unavailable_sites(config: SurfaceConfig) -> tuple[int, int]:
    """Allocate blocked and defect sites by largest remainder without overlap."""
    quotas = (
        config.sites_per_region * config.blocked_fraction,
        config.sites_per_region * config.defect_fraction,
    )
    counts = [math.floor(quota) for quota in quotas]
    target = min(config.sites_per_region, math.floor(sum(quotas) + 0.5))
    remaining = target - sum(counts)
    for index in sorted(range(len(quotas)), key=lambda item: (-(quotas[item] - counts[item]), item))[:remaining]:
        counts[index] += 1
    return counts[0], counts[1]


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RecipeError(f"non-finite JSON number: {value}")


def load_recipe(path: Path) -> Mapping[str, Any]:
    """Load a JSON recipe while rejecting ambiguous object keys and non-finite values."""
    try:
        with path.open(encoding="utf-8") as recipe_file:
            raw = json.load(
                recipe_file,
                object_pairs_hook=reject_duplicates,
                parse_constant=_reject_json_constant,
            )
    except RecipeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecipeError(f"unable to load recipe: {error}") from error
    if not isinstance(raw, Mapping):
        raise RecipeError("recipe must be a JSON object")
    return raw


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecipeError(f"{context} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise RecipeError(f"{context} keys must be strings")
    return value


def _require_exact_keys(value: Any, expected: frozenset[str], context: str) -> Mapping[str, Any]:
    mapping = _require_mapping(value, context)
    actual = set(mapping)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unexpected:
        raise RecipeError(f"{context}: unexpected keys: {', '.join(unexpected)}")
    if missing:
        raise RecipeError(f"{context}: missing keys: {', '.join(missing)}")
    return mapping


def _require_string(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise RecipeError(f"{field} must be a non-empty string")
    return value


def _require_integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int:
        raise RecipeError(f"{field} must be an integer")
    if value < minimum:
        raise RecipeLimitError(f"{field} must be at least {minimum}")
    return value


def _require_finite_number(value: Any, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RecipeError(f"{field} must be finite")
    return float(value)


def _validate_json_value(value: Any, context: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecipeError(f"{context} must contain finite numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{context}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RecipeError(f"{context} keys must be strings")
            _validate_json_value(item, f"{context}.{key}")
        return
    raise RecipeError(f"{context} must contain JSON values")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _validate_limits(raw: Any) -> ProcessLimits:
    limits = _require_mapping(raw, "limits")
    unexpected = sorted(set(limits) - _LIMIT_KEYS)
    missing = sorted(_REQUIRED_LIMIT_KEYS - set(limits))
    if unexpected:
        raise RecipeError(f"limits: unexpected keys: {', '.join(unexpected)}")
    if missing:
        raise RecipeError(f"limits: missing keys: {', '.join(missing)}")
    min_purge_ms = _require_integer(limits["min_purge_ms"], "min_purge_ms", minimum=1)
    max_temperature_c = _require_finite_number(limits["max_temperature_c"], "max_temperature_c")
    max_pressure_pa = _require_finite_number(limits["max_pressure_pa"], "max_pressure_pa")
    max_cycles = _require_integer(limits["max_cycles"], "max_cycles", minimum=1)
    max_runtime_ms = _require_integer(limits["max_runtime_ms"], "max_runtime_ms", minimum=1)
    max_residual_fraction = _require_finite_number(
        limits["max_residual_fraction"], "max_residual_fraction"
    )
    max_packet_bytes = _require_integer(
        limits.get("max_packet_bytes", _MAX_CANONICAL_PACKET_BYTES),
        "max_packet_bytes",
        minimum=1,
    )
    if max_temperature_c <= 0:
        raise RecipeLimitError("max_temperature_c must be positive")
    if max_pressure_pa <= 0:
        raise RecipeLimitError("max_pressure_pa must be positive")
    if not 0 <= max_residual_fraction <= 1:
        raise RecipeLimitError("max_residual_fraction must be between 0 and 1")
    if max_packet_bytes > _MAX_CANONICAL_PACKET_BYTES:
        raise RecipeLimitError("max_packet_bytes exceeds 800")
    return ProcessLimits(
        min_purge_ms=min_purge_ms,
        max_temperature_c=max_temperature_c,
        max_pressure_pa=max_pressure_pa,
        max_cycles=max_cycles,
        max_runtime_ms=max_runtime_ms,
        max_residual_fraction=max_residual_fraction,
        max_packet_bytes=max_packet_bytes,
    )


def _validate_cycle_arguments(arguments: Any, limits: ProcessLimits, precursors: Mapping[str, Any]) -> tuple[Mapping[str, Any], int]:
    required = {
        "precursor_a",
        "pulse_a_ms",
        "purge_a_ms",
        "precursor_b",
        "pulse_b_ms",
        "purge_b_ms",
        "repeat",
    }
    optional = {"flow_a_sccm", "flow_b_sccm"}
    values = _require_mapping(arguments, "ALD_CYCLE arguments")
    unexpected = sorted(set(values) - required - optional)
    missing = sorted(required - set(values))
    if unexpected:
        raise RecipeError(f"ALD_CYCLE arguments: unexpected keys: {', '.join(unexpected)}")
    if missing:
        raise RecipeError(f"ALD_CYCLE arguments: missing keys: {', '.join(missing)}")
    precursor_a = _require_string(values["precursor_a"], "precursor_a")
    precursor_b = _require_string(values["precursor_b"], "precursor_b")
    if precursor_a not in precursors or precursor_b not in precursors or precursor_a == precursor_b:
        raise RecipeError("ALD_CYCLE must reference distinct declared precursors")
    normalized: dict[str, Any] = {
        "precursor_a": precursor_a,
        "pulse_a_ms": _require_integer(values["pulse_a_ms"], "pulse_a_ms", minimum=1),
        "purge_a_ms": _require_integer(values["purge_a_ms"], "purge_a_ms", minimum=1),
        "precursor_b": precursor_b,
        "pulse_b_ms": _require_integer(values["pulse_b_ms"], "pulse_b_ms", minimum=1),
        "purge_b_ms": _require_integer(values["purge_b_ms"], "purge_b_ms", minimum=1),
        "repeat": _require_integer(values["repeat"], "repeat", minimum=1),
    }
    for purge in ("purge_a_ms", "purge_b_ms"):
        if normalized[purge] < limits.min_purge_ms:
            raise RecipeLimitError(f"{purge} below min_purge_ms")
    for flow in ("flow_a_sccm", "flow_b_sccm"):
        if flow in values:
            amount = _require_finite_number(values[flow], flow)
            if amount < 0:
                raise RecipeLimitError(f"{flow} must be non-negative")
            normalized[flow] = amount
    return MappingProxyType(normalized), normalized["repeat"]


def _validate_instruction(
    raw: Any, limits: ProcessLimits, precursors: Mapping[str, Any]
) -> tuple[Mapping[str, JSONValue], int]:
    instruction = _require_exact_keys(raw, frozenset({"opcode", "arguments"}), "instruction")
    opcode = _require_string(instruction["opcode"], "opcode")
    arguments = instruction["arguments"]
    runtime_ms = 0
    if opcode == "CONFIGURE":
        normalized = _require_exact_keys(arguments, frozenset(), "CONFIGURE arguments")
    elif opcode == "SET_TEMPERATURE":
        values = _require_exact_keys(
            arguments,
            frozenset({"target_c", "ramp_c_per_min", "tolerance_c"}),
            "SET_TEMPERATURE arguments",
        )
        target = _require_finite_number(values["target_c"], "target_c")
        if target > limits.max_temperature_c:
            raise RecipeLimitError("target_c exceeds max_temperature_c")
        ramp = _require_finite_number(values["ramp_c_per_min"], "ramp_c_per_min")
        tolerance = _require_finite_number(values["tolerance_c"], "tolerance_c")
        if ramp <= 0 or tolerance < 0:
            raise RecipeLimitError("temperature ramp and tolerance must be non-negative")
        normalized = MappingProxyType(
            {"target_c": target, "ramp_c_per_min": ramp, "tolerance_c": tolerance}
        )
    elif opcode == "EVACUATE":
        values = _require_exact_keys(arguments, frozenset({"target_pa", "timeout_ms"}), "EVACUATE arguments")
        target = _require_finite_number(values["target_pa"], "target_pa")
        if target < 0:
            raise RecipeLimitError("target_pa must be non-negative")
        if target > limits.max_pressure_pa:
            raise RecipeLimitError("target_pa exceeds max_pressure_pa")
        timeout = _require_integer(values["timeout_ms"], "timeout_ms", minimum=1)
        normalized = MappingProxyType({"target_pa": target, "timeout_ms": timeout})
        runtime_ms = timeout
    elif opcode == "STABILIZE":
        values = _require_exact_keys(arguments, frozenset({"duration_ms"}), "STABILIZE arguments")
        duration = _require_integer(values["duration_ms"], "duration_ms", minimum=1)
        normalized = MappingProxyType({"duration_ms": duration})
        runtime_ms = duration
    elif opcode == "ALD_CYCLE":
        normalized, repeat = _validate_cycle_arguments(arguments, limits, precursors)
        runtime_ms = repeat * sum(
            normalized[field] for field in ("pulse_a_ms", "purge_a_ms", "pulse_b_ms", "purge_b_ms")
        )
    elif opcode == "MEASURE":
        values = _require_exact_keys(arguments, frozenset({"measurements"}), "MEASURE arguments")
        measurements = values["measurements"]
        if not isinstance(measurements, list) or not measurements:
            raise RecipeError("measurements must be a non-empty list")
        if any(not isinstance(value, str) or value not in _MEASUREMENTS for value in measurements):
            raise RecipeError("measurements contain unsupported value")
        if len(set(measurements)) != len(measurements):
            raise RecipeError("measurements must not contain duplicates")
        normalized = MappingProxyType({"measurements": tuple(measurements)})
    elif opcode == "SHUTDOWN":
        values = _require_exact_keys(
            arguments,
            frozenset({"heater_ramp_c_per_min", "vent_target_pa"}),
            "SHUTDOWN arguments",
        )
        ramp = _require_finite_number(values["heater_ramp_c_per_min"], "heater_ramp_c_per_min")
        target = _require_finite_number(values["vent_target_pa"], "vent_target_pa")
        if ramp <= 0:
            raise RecipeLimitError("heater_ramp_c_per_min must be positive")
        if target < 0:
            raise RecipeLimitError("vent_target_pa must be non-negative")
        if target > limits.max_pressure_pa:
            raise RecipeLimitError("vent_target_pa exceeds max_pressure_pa")
        normalized = MappingProxyType({"heater_ramp_c_per_min": ramp, "vent_target_pa": target})
    else:
        raise RecipeError(f"unsupported opcode: {opcode}")
    return MappingProxyType({"opcode": opcode, "arguments": normalized}), runtime_ms


def _validate_packet_arguments(opcode: str, arguments: Any) -> Mapping[str, JSONValue]:
    """Validate direct packet arguments without recipe-specific process limits."""
    if opcode == "CONFIGURE":
        return _require_exact_keys(arguments, frozenset(), "CONFIGURE arguments")
    if opcode == "SET_TEMPERATURE":
        values = _require_exact_keys(
            arguments,
            frozenset({"target_c", "ramp_c_per_min", "tolerance_c"}),
            "SET_TEMPERATURE arguments",
        )
        target = _require_finite_number(values["target_c"], "target_c")
        ramp = _require_finite_number(values["ramp_c_per_min"], "ramp_c_per_min")
        tolerance = _require_finite_number(values["tolerance_c"], "tolerance_c")
        if ramp <= 0 or tolerance < 0:
            raise RecipeLimitError("temperature ramp and tolerance must be non-negative")
        return {"target_c": target, "ramp_c_per_min": ramp, "tolerance_c": tolerance}
    if opcode == "EVACUATE":
        values = _require_exact_keys(arguments, frozenset({"target_pa", "timeout_ms"}), "EVACUATE arguments")
        target = _require_finite_number(values["target_pa"], "target_pa")
        if target < 0:
            raise RecipeLimitError("target_pa must be non-negative")
        timeout = _require_integer(values["timeout_ms"], "timeout_ms", minimum=1)
        return {"target_pa": target, "timeout_ms": timeout}
    if opcode == "STABILIZE":
        values = _require_exact_keys(arguments, frozenset({"duration_ms"}), "STABILIZE arguments")
        return {"duration_ms": _require_integer(values["duration_ms"], "duration_ms", minimum=1)}
    if opcode == "ALD_CYCLE":
        required = {
            "precursor_a",
            "pulse_a_ms",
            "purge_a_ms",
            "precursor_b",
            "pulse_b_ms",
            "purge_b_ms",
            "repeat",
        }
        optional = {"flow_a_sccm", "flow_b_sccm"}
        values = _require_mapping(arguments, "ALD_CYCLE arguments")
        unexpected = sorted(set(values) - required - optional)
        missing = sorted(required - set(values))
        if unexpected:
            raise RecipeError(f"ALD_CYCLE arguments: unexpected keys: {', '.join(unexpected)}")
        if missing:
            raise RecipeError(f"ALD_CYCLE arguments: missing keys: {', '.join(missing)}")
        precursor_a = _require_string(values["precursor_a"], "precursor_a")
        precursor_b = _require_string(values["precursor_b"], "precursor_b")
        if precursor_a != "A" or precursor_b != "B":
            raise RecipeError("ALD_CYCLE must reference declared precursors A and B")
        normalized: dict[str, JSONValue] = {
            "precursor_a": precursor_a,
            "pulse_a_ms": _require_integer(values["pulse_a_ms"], "pulse_a_ms", minimum=1),
            "purge_a_ms": _require_integer(values["purge_a_ms"], "purge_a_ms", minimum=1),
            "precursor_b": precursor_b,
            "pulse_b_ms": _require_integer(values["pulse_b_ms"], "pulse_b_ms", minimum=1),
            "purge_b_ms": _require_integer(values["purge_b_ms"], "purge_b_ms", minimum=1),
            "repeat": _require_integer(values["repeat"], "repeat", minimum=1),
        }
        for flow in ("flow_a_sccm", "flow_b_sccm"):
            if flow in values:
                amount = _require_finite_number(values[flow], flow)
                if amount < 0:
                    raise RecipeLimitError(f"{flow} must be non-negative")
                normalized[flow] = amount
        return normalized
    if opcode == "MEASURE":
        values = _require_exact_keys(arguments, frozenset({"measurements"}), "MEASURE arguments")
        measurements = values["measurements"]
        if not isinstance(measurements, (list, tuple)) or not measurements:
            raise RecipeError("measurements must be a non-empty list")
        if any(not isinstance(value, str) or value not in _MEASUREMENTS for value in measurements):
            raise RecipeError("measurements contain unsupported value")
        if len(set(measurements)) != len(measurements):
            raise RecipeError("measurements must not contain duplicates")
        return {"measurements": list(measurements)}
    if opcode == "SHUTDOWN":
        values = _require_exact_keys(
            arguments,
            frozenset({"heater_ramp_c_per_min", "vent_target_pa"}),
            "SHUTDOWN arguments",
        )
        ramp = _require_finite_number(values["heater_ramp_c_per_min"], "heater_ramp_c_per_min")
        target = _require_finite_number(values["vent_target_pa"], "vent_target_pa")
        if ramp <= 0:
            raise RecipeLimitError("heater_ramp_c_per_min must be positive")
        if target < 0:
            raise RecipeLimitError("vent_target_pa must be non-negative")
        return {"heater_ramp_c_per_min": ramp, "vent_target_pa": target}
    raise RecipeError(f"unsupported opcode: {opcode}")


def _is_exact_packet_arguments(opcode: object, arguments: object) -> bool:
    """Check the immutable normalized shape used by trusted packet values.

    ``CompiledRecipe`` is a frozen dataclass, but callers can still construct
    one with ``object.__new__`` or mutate fields with ``object.__setattr__``.
    This check therefore deliberately accepts only the concrete structures
    produced by ``Packet.__post_init__`` and rejects mapping/tuple/primitive
    subclasses before any equality or iteration can be attacker-controlled.
    """
    if type(opcode) is not str or type(arguments) is not MappingProxyType:
        return False
    try:
        keys = tuple(arguments.keys())
        if any(type(key) is not str for key in keys):
            return False
        key_set = set(keys)

        def exact_float(value: object) -> bool:
            return type(value) is float and math.isfinite(value)

        def exact_int(value: object, minimum: int = 1) -> bool:
            return type(value) is int and value >= minimum

        def exact_string(value: object) -> bool:
            return type(value) is str and bool(value)

        if opcode == "CONFIGURE":
            return not keys
        if opcode == "SET_TEMPERATURE":
            return (
                key_set == {"target_c", "ramp_c_per_min", "tolerance_c"}
                and exact_float(arguments["target_c"])
                and exact_float(arguments["ramp_c_per_min"])
                and exact_float(arguments["tolerance_c"])
                and arguments["ramp_c_per_min"] > 0
                and arguments["tolerance_c"] >= 0
            )
        if opcode == "EVACUATE":
            return (
                key_set == {"target_pa", "timeout_ms"}
                and exact_float(arguments["target_pa"])
                and arguments["target_pa"] >= 0
                and exact_int(arguments["timeout_ms"])
            )
        if opcode == "STABILIZE":
            return key_set == {"duration_ms"} and exact_int(arguments["duration_ms"])
        if opcode == "ALD_CYCLE":
            required = {
                "precursor_a",
                "pulse_a_ms",
                "purge_a_ms",
                "precursor_b",
                "pulse_b_ms",
                "purge_b_ms",
                "repeat",
            }
            optional = {"flow_a_sccm", "flow_b_sccm"}
            if not key_set.issubset(required | optional) or not required.issubset(key_set):
                return False
            if (
                arguments["precursor_a"] != "A"
                or arguments["precursor_b"] != "B"
                or not exact_string(arguments["precursor_a"])
                or not exact_string(arguments["precursor_b"])
            ):
                return False
            for field in ("pulse_a_ms", "purge_a_ms", "pulse_b_ms", "purge_b_ms", "repeat"):
                if not exact_int(arguments[field]):
                    return False
            return all(
                field not in arguments or (exact_float(arguments[field]) and arguments[field] >= 0)
                for field in optional
            )
        if opcode == "MEASURE":
            measurements = arguments["measurements"]
            return (
                key_set == {"measurements"}
                and type(measurements) is tuple
                and bool(measurements)
                and all(type(value) is str and value in _MEASUREMENTS for value in measurements)
                and len(set(measurements)) == len(measurements)
            )
        if opcode == "SHUTDOWN":
            return (
                key_set == {"heater_ramp_c_per_min", "vent_target_pa"}
                and exact_float(arguments["heater_ramp_c_per_min"])
                and exact_float(arguments["vent_target_pa"])
                and arguments["heater_ramp_c_per_min"] > 0
                and arguments["vent_target_pa"] >= 0
            )
    except Exception:
        return False
    return False


def validate_recipe(raw: Mapping[str, Any]) -> Recipe:
    """Validate a complete recipe and return a frozen, canonicalizable model."""
    recipe = _require_exact_keys(raw, _TOP_LEVEL_KEYS, "recipe")
    if recipe["protocol"] != _PROTOCOL:
        raise RecipeError("protocol must be ALD-MEDIA/1")
    recipe_id = _require_string(recipe["recipe_id"], "recipe_id")

    metadata = _require_mapping(recipe["metadata"], "metadata")
    _validate_json_value(metadata, "metadata")
    surface = _require_mapping(recipe["surface"], "surface")
    _validate_json_value(surface, "surface")

    precursor_values = _require_exact_keys(recipe["precursors"], frozenset({"A", "B"}), "precursors")
    precursors: dict[str, Mapping[str, JSONValue]] = {}
    for name in ("A", "B"):
        precursor = _require_exact_keys(precursor_values[name], frozenset({"label"}), f"precursors.{name}")
        precursors[name] = MappingProxyType({"label": _require_string(precursor["label"], f"precursors.{name}.label")})

    limits = _validate_limits(recipe["limits"])
    initial = _require_exact_keys(recipe["initial_conditions"], _INITIAL_CONDITION_KEYS, "initial_conditions")
    temperature = _require_finite_number(initial["temperature_c"], "initial_conditions.temperature_c")
    pressure = _require_finite_number(initial["pressure_pa"], "initial_conditions.pressure_pa")
    if temperature > limits.max_temperature_c:
        raise RecipeLimitError("initial temperature exceeds max_temperature_c")
    if pressure > limits.max_pressure_pa:
        raise RecipeLimitError("initial pressure exceeds max_pressure_pa")

    if not isinstance(recipe["instructions"], list) or not recipe["instructions"]:
        raise RecipeError("instructions must be a non-empty list")
    instructions: list[Mapping[str, JSONValue]] = []
    expanded_cycles = 0
    runtime_ms = 0
    for instruction in recipe["instructions"]:
        normalized, duration = _validate_instruction(instruction, limits, precursors)
        instructions.append(normalized)
        runtime_ms += duration
        if normalized["opcode"] == "ALD_CYCLE":
            expanded_cycles += normalized["arguments"]["repeat"]
        if expanded_cycles > limits.max_cycles:
            raise RecipeLimitError("expanded cycles exceed max_cycles")
        if runtime_ms > limits.max_runtime_ms:
            raise RecipeLimitError("expanded runtime exceeds max_runtime_ms")

    return Recipe(
        protocol=_PROTOCOL,
        recipe_id=recipe_id,
        metadata=_freeze_json(metadata),
        precursors=MappingProxyType(precursors),
        initial_conditions=MappingProxyType({"temperature_c": temperature, "pressure_pa": pressure}),
        limits=limits,
        surface=_freeze_json(surface),
        instructions=tuple(instructions),
    )


def canonical_packet_bytes(packet: Packet) -> bytes:
    payload = {
        "arguments": _json_ready(packet.arguments),
        "opcode": packet.opcode,
        "protocol": packet.protocol,
        "recipe_id": packet.recipe_id,
        "sequence": packet.sequence,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RecipeError(f"packet is not canonical JSON: {error}") from error
    if len(encoded) > _MAX_CANONICAL_PACKET_BYTES:
        raise RecipeLimitError("canonical packet exceeds 800 bytes")
    return encoded


def hash_packet(previous: bytes, payload: bytes) -> bytes:
    return hashlib.sha256(b"ALD1" + previous + payload).digest()


def compile_recipe(recipe: Recipe) -> CompiledRecipe:
    """Generate one canonical, chained packet per validated instruction."""
    previous = bytes(32)
    packets: list[HashedPacket] = []
    for sequence, instruction in enumerate(recipe.instructions):
        packet = Packet(
            protocol=recipe.protocol,
            recipe_id=recipe.recipe_id,
            sequence=sequence,
            opcode=instruction["opcode"],
            arguments=instruction["arguments"],
        )
        canonical = canonical_packet_bytes(packet)
        if len(canonical) > recipe.limits.max_packet_bytes:
            raise RecipeLimitError("canonical packet exceeds recipe max_packet_bytes")
        digest = hash_packet(previous, canonical)
        packets.append(
            HashedPacket(
                packet=packet,
                canonical_bytes=canonical,
                previous_digest=previous,
                digest=digest,
            )
        )
        previous = digest
    return CompiledRecipe(recipe=recipe, packets=tuple(packets), root_hash=previous)


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
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"
    SHUTDOWN = "SHUTDOWN"


ALLOWED_TRANSITIONS: Mapping[ControllerState, frozenset[ControllerState]] = MappingProxyType(
    {
        # A fault can be raised while idle when a packet fails preflight or a
        # recipe contains a command after shutdown.  Keep that fail-safe path
        # explicit in the transition table rather than bypassing validation.
        ControllerState.IDLE: frozenset({ControllerState.CONFIGURED, ControllerState.FAULT}),
        ControllerState.CONFIGURED: frozenset({ControllerState.HEATING, ControllerState.FAULT}),
        ControllerState.HEATING: frozenset({ControllerState.EVACUATING, ControllerState.FAULT}),
        ControllerState.EVACUATING: frozenset({ControllerState.READY, ControllerState.FAULT}),
        ControllerState.READY: frozenset(
            {ControllerState.A_PULSE, ControllerState.COMPLETE, ControllerState.FAULT}
        ),
        ControllerState.A_PULSE: frozenset({ControllerState.A_PURGE, ControllerState.FAULT}),
        ControllerState.A_PURGE: frozenset({ControllerState.B_PULSE, ControllerState.FAULT}),
        ControllerState.B_PULSE: frozenset({ControllerState.B_PURGE, ControllerState.FAULT}),
        ControllerState.B_PURGE: frozenset({ControllerState.READY, ControllerState.FAULT}),
        ControllerState.COMPLETE: frozenset({ControllerState.SHUTDOWN}),
        ControllerState.FAULT: frozenset({ControllerState.SHUTDOWN}),
        ControllerState.SHUTDOWN: frozenset({ControllerState.IDLE}),
    }
)


@dataclass(frozen=True)
class Interlocks:
    chamber_closed: bool = True
    vacuum_available: bool = True
    exhaust_available: bool = True
    temperature_controller_available: bool = True
    watchdog_healthy: bool = True

    def __post_init__(self) -> None:
        for name in (
            "chamber_closed",
            "vacuum_available",
            "exhaust_available",
            "temperature_controller_available",
            "watchdog_healthy",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")


@dataclass
class VirtualChamber:
    simulation_time_ms: int
    temperature_c: float
    pressure_pa: float
    valve_a_open: bool = False
    valve_b_open: bool = False
    inert_purge_open: bool = False
    pump_on: bool = False


@dataclass(frozen=True)
class ChamberSnapshot:
    simulation_time_ms: int
    temperature_c: float
    pressure_pa: float
    valve_a_open: bool
    valve_b_open: bool
    inert_purge_open: bool
    pump_on: bool

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "simulation_time_ms": self.simulation_time_ms,
            "temperature_c": self.temperature_c,
            "pressure_pa": self.pressure_pa,
            "valve_a_open": self.valve_a_open,
            "valve_b_open": self.valve_b_open,
            "inert_purge_open": self.inert_purge_open,
            "pump_on": self.pump_on,
        }


@dataclass(frozen=True)
class AuditEvent:
    record_number: int
    simulation_time_ms: int
    event_type: str
    state: ControllerState
    packet_sequence: int | None
    valve_a_open: bool
    valve_b_open: bool
    details: Mapping[str, JSONValue]


@dataclass(frozen=True)
class CycleMetric:
    cycle: int
    simulation_time_ms: int
    coverage: float
    thickness_nm: float
    utilization: float
    defect_fraction: float


@dataclass(frozen=True)
class FaultRecord:
    code: str
    packet_sequence: int | None
    state: ControllerState
    last_verified_digest: bytes
    chamber: ChamberSnapshot
    interlocks: Interlocks

    def as_dict(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "packet_sequence": self.packet_sequence,
            "state": self.state.value,
            "last_verified_digest": self.last_verified_digest.hex(),
            "chamber": self.chamber.as_dict(),
            "interlocks": {
                "chamber_closed": self.interlocks.chamber_closed,
                "vacuum_available": self.interlocks.vacuum_available,
                "exhaust_available": self.interlocks.exhaust_available,
                "temperature_controller_available": self.interlocks.temperature_controller_available,
                "watchdog_healthy": self.interlocks.watchdog_healthy,
            },
        }


@dataclass(frozen=True)
class SimulationResult:
    audit: tuple[AuditEvent, ...]
    cycles: tuple[CycleMetric, ...]
    surface: SurfaceSnapshot
    fault: FaultRecord | None
    final_state: ControllerState
    chamber: ChamberSnapshot
    # These fields make reports self-describing while retaining compatibility
    # with callers that construct SimulationResult positionally.
    protocol: str = _PROTOCOL
    recipe_id: str = ""
    root_hash: bytes = bytes(32)
    seed: int | None = None
    model_version: str = ""


class SimulatedALDController:
    """Deterministically execute verified recipe packets against a virtual chamber."""

    def __init__(self, interlocks: Interlocks | None = None) -> None:
        self.interlocks = Interlocks() if interlocks is None else interlocks
        if not isinstance(self.interlocks, Interlocks):
            raise TypeError("interlocks must be an Interlocks instance")
        self.state = ControllerState.IDLE
        self.chamber = VirtualChamber(simulation_time_ms=0, temperature_c=25.0, pressure_pa=101325.0)
        self._audit: list[AuditEvent] = []
        self._cycles: list[CycleMetric] = []
        self._current_packet: HashedPacket | None = None
        self._last_verified_digest = bytes(32)
        self._limits: ProcessLimits | None = None
        self._surface: SurfaceModel | None = None
        self._temperature_target: float | None = None
        self._temperature_tolerance = 0.0
        self._shutdown_completed = False

    def transition(
        self,
        next_state: ControllerState,
        *,
        packet_sequence: int | None = None,
        event_type: str = "TRANSITION",
        details: Mapping[str, JSONValue] | None = None,
    ) -> None:
        if next_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ControllerFault("INVALID_TRANSITION")
        self.state = next_state
        self._record(event_type, packet_sequence, details)

    def execute(self, compiled: CompiledRecipe, seed: int) -> SimulationResult:
        if type(compiled) is not CompiledRecipe:
            raise TypeError("compiled must be a CompiledRecipe")
        if type(seed) is not int:
            raise TypeError("seed must be an integer")
        try:
            self._start_run(compiled, seed)
            # Integrity verification returns the one exact tuple that will be
            # executed. Never iterate the caller-owned field a second time.
            trusted_packets = self._verify_compiled_integrity(compiled)
            # Surface randomness is seeded only after the complete packet
            # chain, identity bindings, and terminal root hash are verified.
            self._initialize_surface(compiled, seed)
            self._current_packet = None
            self._last_verified_digest = bytes(32)
            for expected_sequence, hashed_packet in enumerate(trusted_packets):
                self._current_packet = hashed_packet
                self._verify_packet(hashed_packet, expected_sequence)
                self._execute_packet(hashed_packet.packet)
                self._last_verified_digest = hashed_packet.digest
            if self.state is not ControllerState.IDLE:
                raise ControllerFault("RECIPE_DID_NOT_SHUTDOWN")
        except ControllerFault as error:
            self._handle_fault(error)
        except SurfaceModelError:
            self._handle_fault(ControllerFault("INVALID_SURFACE_CONFIG"))
        except Exception:
            # Any unexpected execution-boundary failure must leave a
            # deterministic, fail-closed result rather than escaping.
            self._handle_fault(ControllerFault("EXECUTION_FAULT"))
        surface = self._surface.snapshot() if self._surface is not None else _empty_surface_snapshot()
        return SimulationResult(
            audit=tuple(self._audit),
            cycles=tuple(self._cycles),
            surface=surface,
            fault=getattr(self, "_fault", None),
            final_state=self.state,
            chamber=self._chamber_snapshot(),
            protocol=getattr(self, "_compiled_protocol", _PROTOCOL),
            recipe_id=getattr(self, "_compiled_recipe_id", ""),
            root_hash=(compiled.root_hash if type(compiled.root_hash) is bytes and len(compiled.root_hash) == 32 else bytes(32)),
            seed=seed,
            model_version=(self._surface.config.model_version if self._surface is not None else ""),
        )

    def assert_precursor_safe(self, next_precursor: str) -> None:
        limits = self._require_limits()
        if not self.interlocks.chamber_closed:
            raise ControllerFault("CHAMBER_OPEN")
        if not self.interlocks.vacuum_available:
            raise ControllerFault("VACUUM_UNAVAILABLE")
        if not self.interlocks.exhaust_available:
            raise ControllerFault("EXHAUST_UNAVAILABLE")
        if not self.interlocks.temperature_controller_available:
            raise ControllerFault("TEMPERATURE_CONTROLLER_UNAVAILABLE")
        if not self.interlocks.watchdog_healthy:
            raise ControllerFault("WATCHDOG_UNHEALTHY")
        if self.chamber.valve_a_open or self.chamber.valve_b_open:
            raise ControllerFault("PRECURSOR_VALVE_ALREADY_OPEN")
        if not self.temperature_is_stable():
            raise ControllerFault("TEMPERATURE_UNSTABLE")
        if self.chamber.pressure_pa > limits.max_pressure_pa:
            raise ControllerFault("PRESSURE_OUT_OF_RANGE")
        if self.incompatible_residual(next_precursor) > limits.max_residual_fraction:
            raise ControllerFault("INCOMPATIBLE_RESIDUAL")

    def temperature_is_stable(self) -> bool:
        limits = self._require_limits()
        return (
            self._temperature_target is not None
            and self.chamber.temperature_c <= limits.max_temperature_c
            and abs(self.chamber.temperature_c - self._temperature_target) <= self._temperature_tolerance
        )

    def incompatible_residual(self, next_precursor: str) -> float:
        snapshot = self._require_surface().snapshot()
        residual = snapshot.residual_b if next_precursor == "A" else snapshot.residual_a
        return residual / len(snapshot.regions)

    def _start_run(self, compiled: CompiledRecipe, seed: int) -> None:
        # Establish a fresh, safe baseline before reading any recipe-derived
        # values so even initialization failures cannot leak stale state.
        self._limits = None
        self._surface = None
        self._current_packet = None
        self._fault = None
        self.state = ControllerState.IDLE
        self.chamber = VirtualChamber(simulation_time_ms=0, temperature_c=25.0, pressure_pa=101325.0)
        self._audit = []
        self._cycles = []
        self._last_verified_digest = bytes(32)
        self._temperature_target = None
        self._temperature_tolerance = 0.0
        self._cycle_index = 0
        self._shutdown_completed = False

        recipe = compiled.recipe
        self._compiled_protocol = recipe.protocol
        self._compiled_recipe_id = recipe.recipe_id
        self.chamber = VirtualChamber(
            simulation_time_ms=0,
            temperature_c=recipe.initial_conditions["temperature_c"],
            pressure_pa=recipe.initial_conditions["pressure_pa"],
        )
        self._limits = recipe.limits

    def _initialize_surface(self, compiled: CompiledRecipe, seed: int) -> None:
        recipe = compiled.recipe
        max_event_samples = recipe.surface.get("max_event_samples", 0)
        self._surface = SurfaceModel(
            self._surface_config(recipe),
            compiled.root_hash,
            seed,
            max_event_samples=max_event_samples,
        )

    def _surface_config(self, recipe: Recipe) -> SurfaceConfig:
        surface = recipe.surface
        regions = surface.get("regions", 1)
        if isinstance(regions, bool) or not isinstance(regions, int) or regions <= 0:
            raise SurfaceModelError("regions must be a positive integer")
        model_version = surface.get("model_version", "site-binomial/1")
        transport_factors = surface.get("transport_factors", (1.0,) * regions)
        return SurfaceConfig(
            model_version=model_version,
            regions=regions,
            sites_per_region=surface.get("sites_per_region", 1_000),
            transport_factors=transport_factors,
            blocked_fraction=surface.get("blocked_fraction", 0.0),
            defect_fraction=surface.get("defect_fraction", 0.0),
            k_a=surface.get("k_a", 1.5),
            k_b=surface.get("k_b", 1.4),
            growth_nm_per_reaction_fraction=surface.get("growth_nm_per_reaction_fraction", 0.11),
            purge_half_life_ms=surface.get("purge_half_life_ms", 800),
        )

    def _verify_compiled_integrity(self, compiled: CompiledRecipe) -> tuple[HashedPacket, ...]:
        """Validate and snapshot the externally supplied packet stream.

        All provenance fields are populated only from exact built-in values
        that passed this preflight. This keeps hostile tuple/bytes/object
        subclasses from changing behavior between verification and execution
        or from poisoning fault and audit records.
        """
        try:
            recipe = compiled.recipe
            packet_container = compiled.packets
            root_hash = compiled.root_hash
        except Exception as error:
            self._current_packet = None
            raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH") from error
        if type(recipe) is not Recipe or type(packet_container) is not tuple:
            self._current_packet = None
            raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
        if type(root_hash) is not bytes or len(root_hash) != 32:
            self._current_packet = None
            raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
        # An exact built-in tuple has no attacker-defined iterator. Use this
        # snapshot exclusively for both verification and execution.
        trusted_packets = tuple(packet_container)
        if recipe.protocol != _PROTOCOL:
            raise ControllerFault("RECIPE_PROTOCOL_MISMATCH")
        try:
            canonical_compiled = compile_recipe(recipe)
        except Exception as error:
            raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH") from error
        if len(trusted_packets) != len(canonical_compiled.packets):
            self._current_packet = None
            raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
        previous = bytes(32)
        self._last_verified_digest = previous
        for expected_sequence, hashed_packet in enumerate(trusted_packets):
            if not self._is_well_formed_hashed_packet(hashed_packet):
                # Never retain an arbitrary external object as trusted
                # current-packet provenance.
                self._current_packet = None
                raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
            try:
                self._verify_packet(hashed_packet, expected_sequence)
            except ControllerFault:
                # This candidate is not trusted until its local integrity and
                # recipe-stream binding both pass.
                self._current_packet = None
                raise
            except Exception as error:
                self._current_packet = None
                raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH") from error
            # A recomputed chain for a different instruction stream can pass
            # local hash checks, but it is not the recipe that was compiled.
            # Compare exact canonical bytes instead of dataclass/tuple
            # equality, which can dispatch attacker-defined ``__eq__``.
            expected_packet = canonical_compiled.packets[expected_sequence]
            if hashed_packet.canonical_bytes != expected_packet.canonical_bytes:
                self._current_packet = None
                raise ControllerFault("COMPILED_PACKET_STREAM_MISMATCH")
            self._current_packet = hashed_packet
            previous = hashed_packet.digest
            self._last_verified_digest = previous
        if root_hash != canonical_compiled.root_hash:
            raise ControllerFault("ROOT_HASH_MISMATCH")
        if root_hash != previous:
            raise ControllerFault("ROOT_HASH_MISMATCH")
        # Keep the fully verified root and first pending packet available for
        # startup/surface initialization faults. Execution resets these to
        # the zero digest immediately before processing packet zero.
        self._last_verified_digest = previous
        self._current_packet = trusted_packets[0] if trusted_packets else None
        return trusted_packets

    @staticmethod
    def _is_well_formed_hashed_packet(candidate: object) -> bool:
        if type(candidate) is not HashedPacket:
            return False
        try:
            packet = candidate.packet
            canonical_bytes = candidate.canonical_bytes
            previous_digest = candidate.previous_digest
            digest = candidate.digest
            if type(packet) is not Packet:
                return False
            if type(canonical_bytes) is not bytes or len(canonical_bytes) > _MAX_CANONICAL_PACKET_BYTES:
                return False
            if type(previous_digest) is not bytes or len(previous_digest) != 32:
                return False
            if type(digest) is not bytes or len(digest) != 32:
                return False
            if type(packet.protocol) is not str or not packet.protocol:
                return False
            if type(packet.recipe_id) is not str or not packet.recipe_id:
                return False
            if type(packet.sequence) is not int or packet.sequence < 0:
                return False
            if type(packet.opcode) is not str or not packet.opcode:
                return False
            return _is_exact_packet_arguments(packet.opcode, packet.arguments)
        except Exception:
            return False

    def _verify_packet(self, packet: HashedPacket, expected_sequence: int) -> None:
        if packet.packet.protocol != self._compiled_protocol:
            raise ControllerFault("PACKET_PROTOCOL_MISMATCH")
        if packet.packet.recipe_id != self._compiled_recipe_id:
            raise ControllerFault("PACKET_RECIPE_ID_MISMATCH")
        if packet.packet.sequence != expected_sequence:
            raise ControllerFault("PACKET_SEQUENCE_DISCONTINUITY")
        if packet.previous_digest != self._last_verified_digest:
            raise ControllerFault("PACKET_DIGEST_DISCONTINUITY")
        if canonical_packet_bytes(packet.packet) != packet.canonical_bytes:
            raise ControllerFault("PACKET_CANONICAL_MISMATCH")
        if hash_packet(packet.previous_digest, packet.canonical_bytes) != packet.digest:
            raise ControllerFault("PACKET_DIGEST_MISMATCH")

    def _execute_packet(self, packet: Packet) -> None:
        if self._shutdown_completed:
            raise ControllerFault("INVALID_TRANSITION")
        sequence = packet.sequence
        arguments = packet.arguments
        if packet.opcode == "CONFIGURE":
            self.transition(ControllerState.CONFIGURED, packet_sequence=sequence)
        elif packet.opcode == "SET_TEMPERATURE":
            if not self.interlocks.temperature_controller_available:
                raise ControllerFault("TEMPERATURE_CONTROLLER_UNAVAILABLE")
            self.transition(ControllerState.HEATING, packet_sequence=sequence)
            target = float(arguments["target_c"])
            ramp = float(arguments["ramp_c_per_min"])
            self._advance_time(math.ceil(abs(target - self.chamber.temperature_c) / ramp * 60_000))
            self.chamber.temperature_c = target
            self._temperature_target = target
            self._temperature_tolerance = float(arguments["tolerance_c"])
        elif packet.opcode == "EVACUATE":
            self.transition(ControllerState.EVACUATING, packet_sequence=sequence)
            if not self.interlocks.vacuum_available:
                raise ControllerFault("VACUUM_UNAVAILABLE")
            self.chamber.pump_on = True
            self._advance_time(int(arguments["timeout_ms"]))
            self.chamber.pressure_pa = float(arguments["target_pa"])
        elif packet.opcode == "STABILIZE":
            self._advance_time(int(arguments["duration_ms"]))
            self.transition(ControllerState.READY, packet_sequence=sequence)
        elif packet.opcode == "ALD_CYCLE":
            self._execute_cycles(arguments, sequence)
        elif packet.opcode == "MEASURE":
            if self.state is not ControllerState.READY:
                raise ControllerFault("INVALID_TRANSITION")
            self._record("MEASUREMENT", sequence, {"measurements": arguments["measurements"]})
        elif packet.opcode == "SHUTDOWN":
            self.transition(ControllerState.COMPLETE, packet_sequence=sequence)
            self.transition(ControllerState.SHUTDOWN, packet_sequence=sequence)
            self._shutdown(float(arguments["heater_ramp_c_per_min"]), float(arguments["vent_target_pa"]))
            self.transition(ControllerState.IDLE, packet_sequence=sequence)
            self._shutdown_completed = True
        else:
            raise ControllerFault("UNSUPPORTED_OPCODE")

    def _execute_cycles(self, arguments: Mapping[str, JSONValue], sequence: int) -> None:
        if self.state is not ControllerState.READY:
            raise ControllerFault("INVALID_TRANSITION")
        for _ in range(int(arguments["repeat"])):
            self._cycle_index += 1
            cycle = self._cycle_index
            self.assert_precursor_safe("A")
            self.chamber.valve_a_open = True
            self.transition(ControllerState.A_PULSE, packet_sequence=sequence, details={"cycle": cycle})
            pulse_a_ms = int(arguments["pulse_a_ms"])
            self._advance_time(pulse_a_ms)
            self._require_surface().expose_a(cycle, self._dose(arguments, "a"))
            self.chamber.valve_a_open = False
            self.chamber.inert_purge_open = True
            self.transition(ControllerState.A_PURGE, packet_sequence=sequence, details={"cycle": cycle})
            purge_a_ms = int(arguments["purge_a_ms"])
            self._advance_time(purge_a_ms)
            self._require_surface().purge(purge_a_ms)
            self.chamber.inert_purge_open = False
            self.assert_precursor_safe("B")
            self.chamber.valve_b_open = True
            self.transition(ControllerState.B_PULSE, packet_sequence=sequence, details={"cycle": cycle})
            pulse_b_ms = int(arguments["pulse_b_ms"])
            self._advance_time(pulse_b_ms)
            self._require_surface().expose_b(cycle, self._dose(arguments, "b"))
            self.chamber.valve_b_open = False
            self.chamber.inert_purge_open = True
            self.transition(ControllerState.B_PURGE, packet_sequence=sequence, details={"cycle": cycle})
            purge_b_ms = int(arguments["purge_b_ms"])
            self._advance_time(purge_b_ms)
            self._require_surface().purge(purge_b_ms)
            self.chamber.inert_purge_open = False
            self.transition(ControllerState.READY, packet_sequence=sequence, details={"cycle": cycle})
            surface = self._require_surface().snapshot()
            self._cycles.append(
                CycleMetric(
                    cycle=cycle,
                    simulation_time_ms=self.chamber.simulation_time_ms,
                    coverage=surface.coverage,
                    thickness_nm=surface.thickness_nm,
                    utilization=surface.utilization,
                    defect_fraction=surface.defect_fraction,
                )
            )

    def _dose(self, arguments: Mapping[str, JSONValue], precursor: str) -> float:
        return float(arguments.get(f"flow_{precursor}_sccm", 1.0)) * int(arguments[f"pulse_{precursor}_ms"]) / 100_000

    def _advance_time(self, duration_ms: int, *, safety_shutdown: bool = False) -> None:
        if duration_ms < 0:
            raise ControllerFault("NEGATIVE_SIMULATION_DURATION")
        new_time = self.chamber.simulation_time_ms + duration_ms
        if not safety_shutdown and new_time > self._require_limits().max_runtime_ms:
            raise ControllerFault("RUNTIME_LIMIT_EXCEEDED")
        self.chamber.simulation_time_ms = new_time

    def _shutdown(self, ramp_c_per_min: float, vent_target_pa: float) -> None:
        self.chamber.valve_a_open = False
        self.chamber.valve_b_open = False
        self.chamber.inert_purge_open = self.interlocks.exhaust_available
        self.chamber.pump_on = False
        self._advance_time(
            math.ceil(abs(self.chamber.temperature_c - 25.0) / ramp_c_per_min * 60_000),
            safety_shutdown=True,
        )
        self.chamber.temperature_c = 25.0
        self.chamber.pressure_pa = vent_target_pa
        self.chamber.inert_purge_open = False

    def _handle_fault(self, error: ControllerFault) -> None:
        packet_sequence = self._fault_packet_sequence()
        fault_state = self.state
        self.chamber.valve_a_open = False
        self.chamber.valve_b_open = False
        self._fault = FaultRecord(
            code=error.code,
            packet_sequence=packet_sequence,
            state=fault_state,
            last_verified_digest=self._last_verified_digest,
            chamber=self._chamber_snapshot(),
            interlocks=self.interlocks,
        )
        if self.state is not ControllerState.FAULT:
            self.transition(
                ControllerState.FAULT,
                packet_sequence=packet_sequence,
                event_type="FAULT",
                details={"code": error.code},
            )
        self.transition(ControllerState.SHUTDOWN, packet_sequence=packet_sequence, event_type="SHUTDOWN")
        self._shutdown(20.0, self._safe_shutdown_pressure())
        self.transition(ControllerState.IDLE, packet_sequence=packet_sequence, event_type="SHUTDOWN_COMPLETE")

    def _fault_packet_sequence(self) -> int | None:
        """Extract a safe packet sequence from possibly untrusted provenance."""
        current = self._current_packet
        if type(current) is not HashedPacket:
            return None
        try:
            packet = current.packet
            sequence = packet.sequence
        except Exception:
            return None
        if type(packet) is not Packet:
            return None
        return sequence if type(sequence) is int and sequence >= 0 else None

    def _safe_shutdown_pressure(self) -> float:
        """Choose a deterministic vent target within the active pressure cap."""
        limits = self._limits
        if limits is None:
            return 101325.0
        maximum = limits.max_pressure_pa
        if isinstance(maximum, (int, float)) and math.isfinite(maximum):
            return min(101325.0, max(0.0, float(maximum)))
        return 0.0

    def _record(
        self,
        event_type: str,
        packet_sequence: int | None,
        details: Mapping[str, JSONValue] | None = None,
    ) -> None:
        record_details: dict[str, JSONValue] = dict(details or {})
        record_details["pressure_pa"] = self.chamber.pressure_pa
        provenance = self._audit_provenance()
        if provenance is not None:
            packet_digest, last_verified_digest = provenance
            record_details["packet_digest"] = packet_digest.hex()
            record_details["last_verified_digest"] = last_verified_digest.hex()
        self._audit.append(
            AuditEvent(
                record_number=len(self._audit) + 1,
                simulation_time_ms=self.chamber.simulation_time_ms,
                event_type=event_type,
                state=self.state,
                packet_sequence=packet_sequence,
                valve_a_open=self.chamber.valve_a_open,
                valve_b_open=self.chamber.valve_b_open,
                details=_freeze_json(record_details),
            )
        )

    def _audit_provenance(self) -> tuple[bytes, bytes] | None:
        """Read audit digest fields only from verified exact packet values."""
        current = self._current_packet
        try:
            if type(current) is not HashedPacket or type(current.packet) is not Packet:
                return None
            packet_digest = current.digest
            last_verified_digest = self._last_verified_digest
        except Exception:
            return None
        if (
            type(packet_digest) is not bytes
            or len(packet_digest) != 32
            or type(last_verified_digest) is not bytes
            or len(last_verified_digest) != 32
        ):
            return None
        return packet_digest, last_verified_digest

    def _chamber_snapshot(self) -> ChamberSnapshot:
        return ChamberSnapshot(
            simulation_time_ms=self.chamber.simulation_time_ms,
            temperature_c=self.chamber.temperature_c,
            pressure_pa=self.chamber.pressure_pa,
            valve_a_open=self.chamber.valve_a_open,
            valve_b_open=self.chamber.valve_b_open,
            inert_purge_open=self.chamber.inert_purge_open,
            pump_on=self.chamber.pump_on,
        )

    def _require_limits(self) -> ProcessLimits:
        if self._limits is None:
            raise ControllerFault("CONTROLLER_NOT_CONFIGURED")
        return self._limits

    def _require_surface(self) -> SurfaceModel:
        if self._surface is None:
            raise ControllerFault("CONTROLLER_NOT_CONFIGURED")
        return self._surface


def _report_ready(value: Any) -> Any:
    """Convert report values without changing caller-owned immutable data."""
    if isinstance(value, Enum):
        return _report_ready(value.value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _report_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_report_ready(item) for item in value]
    if value is None or type(value) in (str, int, float, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise OutputError("report contains a non-finite number")
        return value
    raise OutputError(f"report value is not JSON-safe: {type(value).__name__}")


def write_json(value: Any, path: Path) -> None:
    """Write one canonical, finite JSON value with a stable trailing newline."""
    try:
        ready = _report_ready(value)
        encoded = json.dumps(
            ready,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    except OutputError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise OutputError(f"unable to write report {path}: {error}") from error


def _audit_dict(event: AuditEvent, *, protocol: str, recipe_id: str) -> dict[str, Any]:
    return {
        "protocol": protocol,
        "recipe_id": recipe_id,
        "record_number": event.record_number,
        "simulation_time_ms": event.simulation_time_ms,
        "event_type": event.event_type,
        "state": event.state.value,
        "packet_sequence": event.packet_sequence,
        "valve_a_open": event.valve_a_open,
        "valve_b_open": event.valve_b_open,
        "details": event.details,
    }


def write_audit_jsonl(
    audit: Sequence[AuditEvent],
    path: Path,
    *,
    protocol: str = _PROTOCOL,
    recipe_id: str = "",
) -> None:
    """Write ordered audit records, one canonical JSON object per line."""
    try:
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for event in audit:
                record = _audit_dict(event, protocol=protocol, recipe_id=recipe_id)
                stream.write(
                    json.dumps(
                        _report_ready(record),
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    except OutputError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise OutputError(f"unable to write report {path}: {error}") from error


def write_cycle_csv(cycles: Sequence[CycleMetric], path: Path) -> None:
    """Write cycle metrics with a fixed, machine-readable column order."""
    columns = (
        "cycle",
        "simulation_time_ms",
        "coverage",
        "thickness_nm",
        "utilization",
        "defect_fraction",
    )
    # Validate every row before opening the destination. This keeps direct
    # callers from receiving a truncated CSV when a later metric is invalid.
    rows: list[tuple[Any, ...]] = []
    try:
        for metric in cycles:
            row = tuple(getattr(metric, column) for column in columns)
            for index, value in enumerate(row):
                if index < 2:
                    if type(value) is not int:
                        raise OutputError(f"cycle metric {columns[index]} must be an integer")
                elif type(value) not in (int, float) or not math.isfinite(value):
                    raise OutputError(f"cycle metric {columns[index]} must be finite")
            rows.append(row)
    except OutputError:
        raise
    except Exception as error:
        raise OutputError(f"invalid cycle metric: {error}") from error
    try:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            writer.writerows(rows)
    except (OSError, TypeError, ValueError, OverflowError) as error:
        raise OutputError(f"unable to write report {path}: {error}") from error


@dataclass
class _OwnedDirectory:
    """A directory descriptor owned for one publication transaction.

    The descriptor binding makes the local transaction independent of later
    path traversal changes.  It does not protect against an actively hostile
    same-UID process with write access to the parent: Linux ``renameat2`` has
    no exact source-FD binding for directory rename/unlink.  This is therefore
    a single-user local simulator boundary, not a privileged or multi-tenant
    publication service.
    """

    fd: int
    identity: tuple[int, int]

    @classmethod
    def from_fd(cls, fd: int) -> "_OwnedDirectory":
        try:
            info = os.fstat(fd)
        except OSError as error:
            raise OutputError(f"unable to inspect directory descriptor: {error}") from error
        if not stat.S_ISDIR(info.st_mode):
            raise OutputError("publication descriptor is not a directory")
        return cls(fd=fd, identity=(info.st_dev, info.st_ino))

    def assert_identity(self) -> None:
        try:
            current = os.fstat(self.fd)
        except OSError as error:
            raise OutputError(f"unable to inspect directory descriptor: {error}") from error
        if (current.st_dev, current.st_ino) != self.identity or not stat.S_ISDIR(current.st_mode):
            raise OutputError("publication directory identity changed")

    def close(self) -> None:
        fd = self.fd
        if fd < 0:
            return
        os.close(fd)
        self.fd = -1

    def __enter__(self) -> "_OwnedDirectory":
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        try:
            self.close()
        except BaseException:
            if exc_type is None:
                raise


@dataclass
class _PublisherLock:
    """Cooperative lock held from staging creation through cleanup."""

    fd: int

    def close(self) -> None:
        fd = self.fd
        if fd < 0:
            return
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        self.fd = -1


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_LOCK_NAME = b".ald-media-controller.lock"
_DEFERRED_CLOSES: list[Any] = []
_CLOSE_RETRIES = 3


@dataclass
class _OwnedFD:
    """Raw descriptor owner used while constructing a report stream."""

    fd: int

    def close(self) -> None:
        fd = self.fd
        if fd < 0:
            return
        os.close(fd)
        self.fd = -1


def _fd_is_closed(resource: Any) -> bool:
    fd = getattr(resource, "fd", -1)
    if fd < 0:
        return True
    try:
        os.fstat(fd)
    except OSError as error:
        if error.errno == errno.EBADF:
            # A close implementation may have completed but reported an
            # error.  EBADF proves that the descriptor is no longer live.
            resource.fd = -1
            return True
        return False
    return False


def _defer_close(resource: Any) -> None:
    if resource is None or getattr(resource, "fd", -1) < 0:
        return
    if not any(existing is resource for existing in _DEFERRED_CLOSES):
        _DEFERRED_CLOSES.append(resource)


def _finalize_close(resource: Any, *, defer: bool = True) -> bool:
    """Close a resource without blind retries or masking a primary error."""
    if resource is None:
        return True
    for _ in range(_CLOSE_RETRIES):
        if getattr(resource, "fd", -1) < 0:
            return True
        try:
            resource.close()
        except BaseException:
            if _fd_is_closed(resource):
                return True
            continue
        if getattr(resource, "fd", -1) < 0 or _fd_is_closed(resource):
            return True
    if defer:
        _defer_close(resource)
    return False


def _drain_deferred_closes() -> None:
    for resource in list(_DEFERRED_CLOSES):
        if _finalize_close(resource, defer=False):
            for index, candidate in enumerate(_DEFERRED_CLOSES):
                if candidate is resource:
                    del _DEFERRED_CLOSES[index]
                    break


def _open_publisher_lock(parent: _OwnedDirectory) -> _PublisherLock:
    """Open and hold the cooperative publisher lock in *parent*.

    The lock is deliberately a regular, no-follow file and remains held for
    the complete staging/write/publish/cleanup transaction.  This serializes
    cooperating local publishers; the descriptor trust boundary above still
    applies to non-cooperating writers.
    """
    if fcntl is None:
        raise OutputError("cooperative publication locking is unavailable")
    parent.assert_identity()
    fd = -1
    raw_fd: _OwnedFD | None = None
    try:
        fd = os.open(
            _LOCK_NAME,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent.fd,
        )
        raw_fd = _OwnedFD(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OutputError("publisher lock entry is not a regular file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw_fd.fd = -1
        return _PublisherLock(fd)
    except BaseException as error:
        if raw_fd is not None:
            _finalize_close(raw_fd)
        if isinstance(error, OutputError):
            raise
        raise OutputError(f"unable to acquire publisher lock: {error}") from error


def _close_quietly(resource: Any) -> None:
    """Finalize cleanup without masking the transaction exception."""
    _finalize_close(resource)


def _open_parent_directory(path: Path) -> tuple[_OwnedDirectory, bytes]:
    """Open/create path parents one component at a time without symlinks."""
    if not sys.platform.startswith("linux") or not os.path.isabs(os.fspath(path)):
        raise OutputError("descriptor-relative publication requires an absolute Linux path")
    absolute = Path(os.path.abspath(os.fspath(path)))
    name = os.fsencode(absolute.name)
    components = [part for part in absolute.parts[1:-1] if part]
    try:
        fd = os.open("/", _DIR_FLAGS)
    except OSError as error:
        raise OutputError(f"unable to open publication root: {error}") from error
    try:
        for component in components:
            component_bytes = os.fsencode(component)
            try:
                next_fd = os.open(component_bytes, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component_bytes, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component_bytes, _DIR_FLAGS, dir_fd=fd)
            prior_fd = fd
            try:
                os.close(prior_fd)
            except BaseException:
                # The newly opened descriptor is not transferred to the
                # caller if the old descriptor could not be closed.
                _finalize_close(_OwnedFD(next_fd))
                raise
            fd = next_fd
        opened = _OwnedDirectory.from_fd(fd)
        fd = -1
        return opened, name
    except BaseException as error:
        if fd >= 0:
            _finalize_close(_OwnedFD(fd))
        if isinstance(error, OutputError):
            raise
        raise OutputError(f"unable to open publication parent: {error}") from error


def _open_child_directory(parent_fd: int, name: bytes) -> _OwnedDirectory:
    fd = -1
    raw_fd: _OwnedFD | None = None
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        raw_fd = _OwnedFD(fd)
        opened = _OwnedDirectory.from_fd(fd)
        raw_fd.fd = -1
        fd = -1
        return opened
    except BaseException as error:
        if raw_fd is not None:
            _finalize_close(raw_fd)
        if isinstance(error, OutputError):
            raise
        raise OutputError(f"publication child is not a safe directory: {name!r}") from error


def _create_staging_directory(parent: _OwnedDirectory, output_name: bytes) -> tuple[_OwnedDirectory, bytes]:
    parent.assert_identity()
    for _ in range(100):
        name = os.fsencode(f".{os.fsdecode(output_name)}-{secrets.token_hex(12)}")
        try:
            os.mkdir(name, 0o700, dir_fd=parent.fd)
        except FileExistsError:
            continue
        except OSError as error:
            raise OutputError(f"unable to create staging directory {name!r}: {error}") from error
        try:
            staging = _open_child_directory(parent.fd, name)
        except BaseException as error:
            # mkdir succeeded, so do not silently orphan the entry.  A
            # second descriptor-relative open binds cleanup to this exact
            # directory.  If that cannot be established, retain the entry
            # under its unique name for recovery rather than guessing.
            try:
                recovered = _open_child_directory(parent.fd, name)
                try:
                    _remove_empty_owned_entry(parent, name, recovered.identity)
                finally:
                    _close_quietly(recovered)
            except BaseException as cleanup_error:
                raise OutputError(
                    f"unable to open staging directory {name!r}; retained for recovery: {error}"
                ) from cleanup_error
            if isinstance(error, OutputError):
                raise
            raise OutputError(f"unable to open staging directory {name!r}: {error}") from error
        return staging, name
    raise OutputError("unable to allocate a unique staging directory")


def _open_existing_directory(parent: _OwnedDirectory, name: bytes) -> _OwnedDirectory | None:
    try:
        return _open_child_directory(parent.fd, name)
    except OutputError as error:
        try:
            os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        raise error


def _rename_noreplace(
    parent_fd: int,
    source_name: bytes,
    destination_name: bytes,
    expected_source: tuple[int, int] | None = None,
) -> None:
    """Atomically rename a directory entry only when destination is absent."""
    if not sys.platform.startswith("linux"):
        raise OutputError("safe no-replace directory publication is unavailable on this platform")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as error:
        raise OutputError("safe no-replace directory publication is unavailable") from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if expected_source is not None:
        source_fd = _open_child_directory(parent_fd, source_name)
        try:
            if source_fd.identity != expected_source:
                raise OutputError("staging directory identity changed")
        finally:
            _close_quietly(source_fd)
    result = renameat2(
        parent_fd, source_name, parent_fd, destination_name, 1
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OutputError(
            f"renameat2 no-replace failed for destination {destination_name!r}: "
            f"[{error_number}] {os.strerror(error_number)}"
        ) from OSError(error_number, os.strerror(error_number), destination_name)


def _rename_exchange(
    parent_fd: int,
    source_name: bytes,
    destination_name: bytes,
    expected_source: tuple[int, int] | None = None,
) -> None:
    """Atomically exchange two existing directory entries on Linux."""
    if not sys.platform.startswith("linux"):
        raise OutputError("safe atomic directory exchange is unavailable on this platform")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as error:
        raise OutputError("safe atomic directory exchange is unavailable") from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if expected_source is not None:
        source_fd = _open_child_directory(parent_fd, source_name)
        try:
            if source_fd.identity != expected_source:
                raise OutputError("staging directory identity changed")
        finally:
            _close_quietly(source_fd)
    result = renameat2(
        parent_fd, source_name, parent_fd, destination_name, 2
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OutputError(
            f"renameat2 exchange failed for destination {destination_name!r}: "
            f"[{error_number}] {os.strerror(error_number)}"
        ) from OSError(error_number, os.strerror(error_number), destination_name)


def _write_fd_text(staging: _OwnedDirectory, name: bytes, text: str) -> None:
    raw_fd: _OwnedFD | None = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=staging.fd)
        raw_fd = _OwnedFD(fd)
        try:
            stream = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        except Exception as error:
            _close_quietly(raw_fd)
            raise OutputError(f"unable to write report {name!r}: {error}") from error
        # Ownership transferred to the Python stream after successful
        # construction; its context manager now closes the descriptor.
        raw_fd.fd = -1
        with stream:
            stream.write(text)
    except OutputError:
        raise
    except Exception as error:
        raise OutputError(f"unable to write report {name!r}: {error}") from error
    except BaseException:
        if raw_fd is not None:
            _close_quietly(raw_fd)
        raise


def _write_json_fd(value: Any, staging: _OwnedDirectory, name: bytes) -> None:
    try:
        text = json.dumps(_report_ready(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    except OutputError:
        raise
    except (TypeError, ValueError) as error:
        raise OutputError(f"unable to serialize report {name!r}: {error}") from error
    _write_fd_text(staging, name, text)


def _write_audit_fd(audit: Sequence[AuditEvent], staging: _OwnedDirectory, *, protocol: str, recipe_id: str) -> None:
    try:
        text = "".join(
            json.dumps(_report_ready(_audit_dict(event, protocol=protocol, recipe_id=recipe_id)), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
            for event in audit
        )
    except (OutputError, TypeError, ValueError) as error:
        if isinstance(error, OutputError):
            raise
        raise OutputError(f"unable to serialize audit report: {error}") from error
    _write_fd_text(staging, b"audit.jsonl", text)


def _write_cycles_fd(cycles: Sequence[CycleMetric], staging: _OwnedDirectory) -> None:
    columns = ("cycle", "simulation_time_ms", "coverage", "thickness_nm", "utilization", "defect_fraction")
    rows: list[tuple[Any, ...]] = []
    try:
        for metric in cycles:
            row = tuple(getattr(metric, column) for column in columns)
            for index, value in enumerate(row):
                if index < 2 and type(value) is not int:
                    raise OutputError(f"cycle metric {columns[index]} must be an integer")
                if index >= 2 and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise OutputError(f"cycle metric {columns[index]} must be finite")
            rows.append(row)
    except OutputError:
        raise
    except Exception as error:
        raise OutputError(f"invalid cycle metric: {error}") from error
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    _write_fd_text(staging, b"cycles.csv", output.getvalue())


def _remove_tree_fd(directory_fd: int) -> None:
    for child in os.listdir(directory_fd):
        name = os.fsencode(child)
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = (info.st_dev, info.st_ino)
        if stat.S_ISDIR(info.st_mode):
            child_dir = _open_child_directory(directory_fd, name)
            try:
                if child_dir.identity != identity:
                    raise OutputError("cleanup directory identity changed")
                _remove_tree_fd(child_dir.fd)
            finally:
                _close_quietly(child_dir)
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity or not stat.S_ISDIR(current.st_mode):
                raise OutputError("cleanup directory identity changed")
            os.rmdir(name, dir_fd=directory_fd)
        else:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity:
                raise OutputError("cleanup entry identity changed")
            os.unlink(name, dir_fd=directory_fd)


def _remove_owned_entry(parent: _OwnedDirectory, name: bytes, identity: tuple[int, int]) -> None:
    child = _open_child_directory(parent.fd, name)
    try:
        if child.identity != identity:
            raise OutputError("cleanup entry identity changed")
        _remove_tree_fd(child.fd)
    finally:
        _close_quietly(child)
    current = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != identity or not stat.S_ISDIR(current.st_mode):
        raise OutputError("cleanup entry identity changed")
    os.rmdir(name, dir_fd=parent.fd)


def _remove_empty_owned_entry(parent: _OwnedDirectory, name: bytes, identity: tuple[int, int]) -> None:
    """Remove only an identity-verified, still-empty staging entry."""
    child = _open_child_directory(parent.fd, name)
    try:
        if child.identity != identity:
            raise OutputError("cleanup entry identity changed")
        if os.listdir(child.fd):
            raise OutputError("new staging directory is no longer empty")
    finally:
        _close_quietly(child)
    current = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != identity or not stat.S_ISDIR(current.st_mode):
        raise OutputError("cleanup entry identity changed")
    os.rmdir(name, dir_fd=parent.fd)


def _publish_handles(parent: _OwnedDirectory, staging: _OwnedDirectory, staging_name: bytes, output_name: bytes, *, overwrite: bool) -> None:
    parent.assert_identity()
    existing = _open_existing_directory(parent, output_name)
    if existing is None:
        published: _OwnedDirectory | None = None
        try:
            _rename_noreplace(parent.fd, staging_name, output_name, staging.identity)
            published = _open_existing_directory(parent, output_name)
            if published is None or published.identity != staging.identity:
                raise OutputError("published staging identity mismatch")
        except BaseException as error:
            if isinstance(error, OutputError):
                raise
            raise OutputError(f"unable to publish reports: {error}") from error
        finally:
            if published is not None:
                _close_quietly(published)
        return
    if not overwrite:
        _close_quietly(existing)
        raise OutputError("output exists")
    old_identity = existing.identity
    exchanged = False
    published: _OwnedDirectory | None = None
    old_entry: _OwnedDirectory | None = None
    try:
        _rename_exchange(parent.fd, staging_name, output_name, staging.identity)
        exchanged = True
        published = _open_existing_directory(parent, output_name)
        old_entry = _open_existing_directory(parent, staging_name)
        if published is None or old_entry is None or published.identity != staging.identity or old_entry.identity != old_identity:
            raise OutputError("published directory identity mismatch")
    except BaseException as error:
        if not exchanged:
            # A wrapper or injected syscall failure may occur after the
            # kernel has completed the exchange.  Confirm that state by the
            # two held entry identities before attempting any rollback.
            probe_output: _OwnedDirectory | None = None
            probe_old: _OwnedDirectory | None = None
            try:
                probe_output = _open_existing_directory(parent, output_name)
                probe_old = _open_existing_directory(parent, staging_name)
                exchanged = (
                    probe_output is not None
                    and probe_old is not None
                    and probe_output.identity == staging.identity
                    and probe_old.identity == old_identity
                )
            except BaseException:
                exchanged = False
            finally:
                if probe_output is not None:
                    _close_quietly(probe_output)
                if probe_old is not None:
                    _close_quietly(probe_old)
        if exchanged:
            rollback_published: _OwnedDirectory | None = None
            rollback_old: _OwnedDirectory | None = None
            try:
                rollback_published = _open_existing_directory(parent, output_name)
                rollback_old = _open_existing_directory(parent, staging_name)
                if rollback_published is None or rollback_old is None or rollback_published.identity != staging.identity or rollback_old.identity != old_identity:
                    raise OutputError("cannot safely roll back exchanged directories")
                _close_quietly(rollback_published)
                _close_quietly(rollback_old)
                _rename_exchange(parent.fd, staging_name, output_name, old_identity)
            except BaseException as restore_error:
                raise OutputError(
                    f"unable to publish reports: {error}; recoverable backup retained at {staging_name!r}"
                ) from restore_error
            finally:
                if rollback_published is not None:
                    _close_quietly(rollback_published)
                if rollback_old is not None:
                    _close_quietly(rollback_old)
        if isinstance(error, OutputError):
            raise
        raise OutputError(f"unable to publish reports: {error}") from error
    finally:
        if published is not None:
            _close_quietly(published)
        if old_entry is not None:
            _close_quietly(old_entry)
        _close_quietly(existing)
    try:
        _remove_owned_entry(parent, staging_name, old_identity)
    except BaseException:
        return


def replace_output_directory(temporary: Path, output: Path, *, overwrite: bool = False) -> None:
    """Atomically publish a completed directory using descriptor-relative names."""
    _drain_deferred_closes()
    temporary = _absolute_output_path(temporary)
    output = _absolute_output_path(output)
    parent, output_name = _open_parent_directory(output)
    lock: _PublisherLock | None = None
    try:
        lock = _open_publisher_lock(parent)
    except BaseException:
        _close_quietly(parent)
        raise
    try:
        staging_parent, staging_name = _open_parent_directory(temporary)
    except BaseException:
        _close_quietly(lock)
        _close_quietly(parent)
        raise
    staging: _OwnedDirectory | None = None
    try:
        if staging_parent.identity != parent.identity:
            raise OutputError("temporary and output directories must share a safe parent")
        if staging_name == output_name:
            raise OutputError("temporary and output directories must be different entries")
        staging = _open_child_directory(parent.fd, staging_name)
        _publish_handles(parent, staging, staging_name, output_name, overwrite=overwrite)
    finally:
        if staging is not None:
            _close_quietly(staging)
        _close_quietly(staging_parent)
        _close_quietly(lock)
        _close_quietly(parent)
        _drain_deferred_closes()


def _absolute_output_path(output: Path) -> Path:
    try:
        candidate = Path(output)
    except (TypeError, ValueError) as error:
        raise OutputError(f"invalid output path: {output!r}") from error
    if not candidate.name or candidate.name in {".", ".."}:
        raise OutputError(f"invalid output directory: {candidate}")
    if "\x00" in os.fspath(candidate):
        raise OutputError("invalid output directory: path contains NUL")
    return Path(os.path.abspath(os.fspath(candidate)))


def _reject_recipe_output_overlap(recipe_path: Path, output: Path) -> None:
    """Reject destinations that could replace the recipe or its ancestors."""
    try:
        recipe_real = Path(os.path.realpath(os.fspath(recipe_path)))
        output_real = Path(os.path.realpath(os.fspath(output)))
    except (OSError, TypeError, ValueError) as error:
        raise OutputError(f"unable to resolve recipe/output paths safely: {error}") from error
    if (
        recipe_real == output_real
        or recipe_real in output_real.parents
        or output_real in recipe_real.parents
    ):
        raise OutputError("output directory overlaps the recipe path or its ancestors")


def publish_reports(result: SimulationResult, output: Path, overwrite: bool = False) -> None:
    """Build reports through held descriptors and atomically publish them."""
    _drain_deferred_closes()
    output = _absolute_output_path(output)
    parent, output_name = _open_parent_directory(output)
    lock: _PublisherLock | None = None
    staging: _OwnedDirectory | None = None
    staging_name: bytes | None = None
    published = False
    try:
        lock = _open_publisher_lock(parent)
        staging, staging_name = _create_staging_directory(parent, output_name)
        _write_audit_fd(result.audit, staging, protocol=result.protocol, recipe_id=result.recipe_id)
        _write_cycles_fd(result.cycles, staging)
        surface = result.surface.as_dict()
        surface.update({"protocol": result.protocol, "recipe_id": result.recipe_id, "root_hash": result.root_hash.hex(), "seed": result.seed, "model_version": result.model_version})
        _write_json_fd(surface, staging, b"surface-final.json")
        if result.fault is not None:
            fault = result.fault.as_dict()
            fault.update({"protocol": result.protocol, "recipe_id": result.recipe_id, "root_hash": result.root_hash.hex(), "seed": result.seed, "model_version": result.model_version})
            _write_json_fd(fault, staging, b"fault.json")
        _publish_handles(parent, staging, staging_name, output_name, overwrite=overwrite)
        published = True
    finally:
        if staging is not None:
            _close_quietly(staging)
        if not published and staging_name is not None:
            try:
                _remove_owned_entry(parent, staging_name, staging.identity if staging is not None else (-1, -1))
            except BaseException:
                pass
        _close_quietly(lock)
        _close_quietly(parent)
        _drain_deferred_closes()


def _expanded_cycle_count(recipe: Recipe) -> int:
    return sum(
        int(instruction["arguments"]["repeat"])
        for instruction in recipe.instructions
        if instruction["opcode"] == "ALD_CYCLE"
    )


def _expanded_runtime_ms(recipe: Recipe) -> int:
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
    return runtime


def _validation_report(compiled: CompiledRecipe) -> dict[str, Any]:
    packets = compiled.packets
    return {
        "protocol": compiled.recipe.protocol,
        "recipe_id": compiled.recipe.recipe_id,
        "root_hash": compiled.root_hash.hex(),
        "packet_count": len(packets),
        "canonical_bytes": sum(len(item.canonical_bytes) for item in packets),
        "packet_sequences": [item.packet.sequence for item in packets],
        "packet_digests": [item.digest.hex() for item in packets],
        "expanded_cycles": _expanded_cycle_count(compiled.recipe),
        "expanded_runtime_ms": _expanded_runtime_ms(compiled.recipe),
        "max_cycles": compiled.recipe.limits.max_cycles,
        "max_runtime_ms": compiled.recipe.limits.max_runtime_ms,
    }


def _run_validate(recipe_path: Path) -> int:
    recipe = validate_recipe(load_recipe(recipe_path))
    compiled = compile_recipe(recipe)
    print(json.dumps(_report_ready(_validation_report(compiled)), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))
    return int(ExitCode.OK)


def _run_simulate(recipe_path: Path, seed: int, output: Path, overwrite: bool) -> int:
    recipe = validate_recipe(load_recipe(recipe_path))
    compiled = compile_recipe(recipe)
    _reject_recipe_output_overlap(recipe_path, output)
    result = SimulatedALDController().execute(compiled, seed)
    publish_reports(result, output, overwrite=overwrite)
    return int(ExitCode.CONTROLLER if result.fault is not None else ExitCode.OK)


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _add_log_level(parser: argparse.ArgumentParser, *, default: Any = argparse.SUPPRESS) -> None:
    parser.add_argument("--log-level", type=str.upper, choices=_LOG_LEVELS, default=default)


class _CLIArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Keep usage failures on the same structured stderr boundary as all
        # other command failures.  argparse's successful --help SystemExit(0)
        # is still handled separately by main().
        usage = self.format_usage().strip()
        raise ALDError(f"{usage} {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _CLIArgumentParser(prog="ald-media-controller")
    _add_log_level(parser, default="INFO")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate and compile a recipe")
    validate.add_argument("recipe", type=Path)
    _add_log_level(validate)

    simulate = commands.add_parser("simulate", help="run a recipe in the deterministic simulator")
    simulate.add_argument("recipe", type=Path)
    simulate.add_argument("--seed", type=int, required=True)
    simulate.add_argument("--output", type=Path, required=True)
    simulate.add_argument("--overwrite", action="store_true")
    _add_log_level(simulate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        # argparse uses status 0 for successful --help and 2 for usage
        # failures. Preserve that distinction for API callers.
        return int(error.code) if isinstance(error.code, int) else int(ExitCode.USAGE)
    except ALDError as error:
        payload = {
            "error": {
                "type": type(error).__name__,
                "code": error.exit_code.name,
                "exit_code": int(error.exit_code),
                "message": str(error),
            }
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return int(error.exit_code)
    log_level = getattr(arguments, "log_level", getattr(arguments, "global_log_level", "INFO"))
    try:
        if arguments.command == "validate":
            return _run_validate(arguments.recipe)
        if arguments.command == "simulate":
            return _run_simulate(arguments.recipe, arguments.seed, arguments.output, arguments.overwrite)
        raise ALDError(f"unsupported command: {arguments.command}")
    except ALDError as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        payload = {
            "error": {
                "type": type(error).__name__,
                "code": error.exit_code.name,
                "exit_code": int(error.exit_code),
                "message": str(error),
            }
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return int(error.exit_code)
    except Exception as error:
        if log_level == "DEBUG":
            traceback.print_exc()
        payload = {
            "error": {
                "type": type(error).__name__,
                "code": ExitCode.DEPENDENCY.name,
                "exit_code": int(ExitCode.DEPENDENCY),
                "message": str(error),
            }
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return int(ExitCode.DEPENDENCY)


if __name__ == "__main__":
    raise SystemExit(main())
