"""Deterministic sequential surface model for multi-precursor ALD/MLD simulation.

This module models ordered, abstract surface-state transitions for two through
six named precursor identities.  Chemical identities are descriptive; dose,
kinetic factors, transport factors, and growth scaling are synthetic simulator
quantities and are not calibrated process parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np


class SequentialSurfaceError(ValueError):
    """Raised when a sequential surface configuration or transition is invalid."""


def _finite_non_negative(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise SequentialSurfaceError(f"{field} must be finite and non-negative")
    return float(value)


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise SequentialSurfaceError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class SequentialSurfaceConfig:
    model_version: str
    regions: int
    sites_per_region: int
    transport_factors: tuple[float, ...]
    blocked_fraction: float
    defect_fraction: float
    reaction_factors: tuple[float, ...]
    growth_nm_per_completion_fraction: float
    purge_half_life_ms: int
    precursor_ids: tuple[str, ...]
    exposure_signature: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.model_version != "site-sequential/1":
            raise SequentialSurfaceError("model_version must be site-sequential/1")
        _positive_int(self.regions, "regions")
        _positive_int(self.sites_per_region, "sites_per_region")
        _positive_int(self.purge_half_life_ms, "purge_half_life_ms")

        if type(self.transport_factors) is not tuple or len(self.transport_factors) != self.regions:
            raise SequentialSurfaceError("transport_factors must have one value per region")
        transport = tuple(
            _finite_non_negative(value, "transport_factors") for value in self.transport_factors
        )

        blocked = _finite_non_negative(self.blocked_fraction, "blocked_fraction")
        defects = _finite_non_negative(self.defect_fraction, "defect_fraction")
        if blocked + defects > 1.0:
            raise SequentialSurfaceError("blocked_fraction and defect_fraction must sum to at most one")

        if type(self.exposure_signature) is not tuple or not 2 <= len(self.exposure_signature) <= 12:
            raise SequentialSurfaceError("exposure_signature must contain 2 to 12 steps")
        if any(type(value) is not str or not value for value in self.exposure_signature):
            raise SequentialSurfaceError("exposure_signature values must be non-empty strings")
        if type(self.precursor_ids) is not tuple or not 2 <= len(self.precursor_ids) <= 6:
            raise SequentialSurfaceError("precursor_ids must contain 2 to 6 identifiers")
        if any(type(value) is not str or not value for value in self.precursor_ids):
            raise SequentialSurfaceError("precursor_ids values must be non-empty strings")
        if len(set(self.precursor_ids)) != len(self.precursor_ids):
            raise SequentialSurfaceError("precursor_ids must be unique")
        if set(self.exposure_signature) != set(self.precursor_ids):
            raise SequentialSurfaceError("exposure_signature must use every declared precursor")

        if type(self.reaction_factors) is not tuple or len(self.reaction_factors) != len(self.exposure_signature):
            raise SequentialSurfaceError("reaction_factors must have one value per exposure step")
        reaction = tuple(
            _finite_non_negative(value, "reaction_factors") for value in self.reaction_factors
        )
        growth = _finite_non_negative(
            self.growth_nm_per_completion_fraction,
            "growth_nm_per_completion_fraction",
        )

        object.__setattr__(self, "transport_factors", transport)
        object.__setattr__(self, "blocked_fraction", blocked)
        object.__setattr__(self, "defect_fraction", defects)
        object.__setattr__(self, "reaction_factors", reaction)
        object.__setattr__(self, "growth_nm_per_completion_fraction", growth)


@dataclass(frozen=True)
class SequentialRegionSnapshot:
    state_counts: tuple[int, ...]
    blocked: int
    defects: int
    residuals: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "state_counts": list(self.state_counts),
            "blocked": self.blocked,
            "defects": self.defects,
            "residuals": dict(self.residuals),
        }


@dataclass(frozen=True)
class SequentialEventSample:
    cycle: int
    step_index: int
    precursor: str
    region: int
    source_state: int
    destination_state: int
    sample_id: str


@dataclass(frozen=True)
class SequentialExposureResult:
    cycle: int
    step_index: int
    precursor: str
    dose: float
    reactions_by_region: tuple[int, ...]
    event_samples: tuple[SequentialEventSample, ...]

    @property
    def total_reactions(self) -> int:
        return sum(self.reactions_by_region)


@dataclass(frozen=True)
class SequentialSurfaceSnapshot:
    model_version: str
    regions: tuple[SequentialRegionSnapshot, ...]
    total_sites: int
    coverage: float
    thickness_nm: float
    utilization: float
    defect_fraction: float
    completed_depositions: int
    residuals: Mapping[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "states_by_region": [list(region.state_counts) for region in self.regions],
            "residuals_by_region": [dict(region.residuals) for region in self.regions],
            "blocked_by_region": [region.blocked for region in self.regions],
            "defects_by_region": [region.defects for region in self.regions],
            "total_sites": self.total_sites,
            "coverage": self.coverage,
            "thickness_nm": self.thickness_nm,
            "utilization": self.utilization,
            "defect_fraction": self.defect_fraction,
            "completed_depositions": self.completed_depositions,
            "residuals": dict(self.residuals),
        }


@dataclass
class _SequentialRegion:
    state_counts: list[int]
    blocked: int
    defects: int
    residuals: dict[str, float]


def _apportion_unavailable(config: SequentialSurfaceConfig) -> tuple[int, int]:
    quotas = (
        config.sites_per_region * config.blocked_fraction,
        config.sites_per_region * config.defect_fraction,
    )
    counts = [math.floor(quota) for quota in quotas]
    target = min(config.sites_per_region, math.floor(sum(quotas) + 0.5))
    remaining = target - sum(counts)
    order = sorted(
        range(2),
        key=lambda index: (-(quotas[index] - counts[index]), index),
    )
    for index in order[:remaining]:
        counts[index] += 1
    return counts[0], counts[1]


def sequential_rng_material(
    root_hash: bytes,
    model_version: str,
    seed: int,
    cycle: int,
    step_index: int,
    precursor: str,
    region: int,
    domain: str,
) -> bytes:
    if type(root_hash) is not bytes or len(root_hash) != 32:
        raise SequentialSurfaceError("root_hash must be exactly 32 bytes")
    for value, field in (
        (seed, "seed"),
        (cycle, "cycle"),
        (step_index, "step_index"),
        (region, "region"),
    ):
        if type(value) is not int or value < 0:
            raise SequentialSurfaceError(f"{field} must be a non-negative integer")
    for value, field in (
        (model_version, "model_version"),
        (precursor, "precursor"),
        (domain, "domain"),
    ):
        if type(value) is not str or not value:
            raise SequentialSurfaceError(f"{field} must be a non-empty string")

    components = (
        root_hash,
        model_version.encode("utf-8"),
        str(seed).encode("ascii"),
        str(cycle).encode("ascii"),
        str(step_index).encode("ascii"),
        precursor.encode("utf-8"),
        str(region).encode("ascii"),
        domain.encode("utf-8"),
    )
    material = bytearray(b"ALD-SEQUENTIAL-RNG/1")
    for component in components:
        material.extend(len(component).to_bytes(8, "big"))
        material.extend(component)
    return bytes(material)


class SequentialSurfaceModel:
    def __init__(
        self,
        config: SequentialSurfaceConfig,
        root_hash: bytes,
        user_seed: int,
        max_event_samples: int = 0,
    ) -> None:
        if type(config) is not SequentialSurfaceConfig:
            raise SequentialSurfaceError("config must be an exact SequentialSurfaceConfig")
        if type(root_hash) is not bytes or len(root_hash) != 32:
            raise SequentialSurfaceError("root_hash must be exactly 32 bytes")
        if type(user_seed) is not int:
            raise SequentialSurfaceError("user_seed must be an integer")
        if type(max_event_samples) is not int or max_event_samples < 0:
            raise SequentialSurfaceError("max_event_samples must be a non-negative integer")
        self.config = config
        self.root_hash = root_hash
        self.user_seed = user_seed
        self.max_event_samples = max_event_samples
        blocked, defects = _apportion_unavailable(config)
        ready = config.sites_per_region - blocked - defects
        self._regions = []
        for _ in range(config.regions):
            states = [0] * len(config.exposure_signature)
            states[0] = ready
            self._regions.append(
                _SequentialRegion(
                    state_counts=states,
                    blocked=blocked,
                    defects=defects,
                    residuals={precursor: 0.0 for precursor in config.precursor_ids},
                )
            )
        self._completed_depositions = 0
        self._expected_step = 0
        self._current_cycle: int | None = None
        self._last_completed_cycle = 0
        self._assert_conserved()

    @property
    def total_sites(self) -> int:
        return self.config.regions * self.config.sites_per_region

    def _reaction_rng_material(
        self,
        cycle: int,
        step_index: int,
        precursor: str,
        region: int,
        domain: str,
    ) -> bytes:
        return sequential_rng_material(
            self.root_hash,
            self.config.model_version,
            self.user_seed,
            cycle,
            step_index,
            precursor,
            region,
            domain,
        )

    def _rng(
        self,
        cycle: int,
        step_index: int,
        precursor: str,
        region: int,
        domain: str,
    ) -> np.random.Generator:
        material = self._reaction_rng_material(cycle, step_index, precursor, region, domain)
        entropy = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
        return np.random.Generator(np.random.PCG64(entropy))

    def expose_step(
        self,
        cycle: int,
        step_index: int,
        precursor: str,
        dose: float,
    ) -> SequentialExposureResult:
        if type(cycle) is not int or cycle <= 0:
            raise SequentialSurfaceError("cycle must be a positive integer")
        if type(step_index) is not int or not 0 <= step_index < len(self.config.exposure_signature):
            raise SequentialSurfaceError("step_index is out of range")
        if precursor != self.config.exposure_signature[step_index]:
            raise SequentialSurfaceError("precursor does not match exposure signature")
        amount = _finite_non_negative(dose, "dose")
        self._assert_step_order(cycle, step_index)

        reactions_by_region: list[int] = []
        samples: list[SequentialEventSample] = []
        sample_budget = self.max_event_samples
        final_step = step_index == len(self.config.exposure_signature) - 1
        destination_state = 0 if final_step else step_index + 1

        for region_index, region in enumerate(self._regions):
            eligible = region.state_counts[step_index]
            probability = -math.expm1(
                -self.config.reaction_factors[step_index]
                * amount
                * self.config.transport_factors[region_index]
            )
            rng = self._rng(cycle, step_index, precursor, region_index, "reaction")
            reactions = int(rng.binomial(eligible, probability))
            region.state_counts[step_index] -= reactions
            region.state_counts[destination_state] += reactions
            region.residuals[precursor] += amount
            if final_step:
                self._completed_depositions += reactions
            reactions_by_region.append(reactions)

            if sample_budget and reactions:
                count = min(sample_budget, reactions)
                sample_rng = self._rng(cycle, step_index, precursor, region_index, "sample")
                sampled = sample_rng.choice(reactions, size=count, replace=False)
                for sampled_index in sorted(int(value) for value in sampled):
                    samples.append(
                        SequentialEventSample(
                            cycle=cycle,
                            step_index=step_index,
                            precursor=precursor,
                            region=region_index,
                            source_state=step_index,
                            destination_state=destination_state,
                            sample_id=f"{region_index}:{sampled_index}",
                        )
                    )
                sample_budget -= count

        self._advance_expected_step(cycle, step_index)
        self._assert_conserved()
        return SequentialExposureResult(
            cycle=cycle,
            step_index=step_index,
            precursor=precursor,
            dose=amount,
            reactions_by_region=tuple(reactions_by_region),
            event_samples=tuple(samples),
        )

    def _assert_step_order(self, cycle: int, step_index: int) -> None:
        if step_index != self._expected_step:
            raise SequentialSurfaceError("exposure step order is invalid")
        if step_index == 0:
            if cycle != self._last_completed_cycle + 1:
                raise SequentialSurfaceError("exposure cycle order is invalid")
            self._current_cycle = cycle
        elif self._current_cycle != cycle:
            raise SequentialSurfaceError("exposure step order is invalid")

    def _advance_expected_step(self, cycle: int, step_index: int) -> None:
        if step_index == len(self.config.exposure_signature) - 1:
            self._last_completed_cycle = cycle
            self._current_cycle = None
            self._expected_step = 0
        else:
            self._expected_step = step_index + 1

    def purge(self, duration_ms: int) -> None:
        if type(duration_ms) is not int or duration_ms < 0:
            raise SequentialSurfaceError("purge duration must be a non-negative integer")
        factor = math.exp(
            -math.log(2.0) * duration_ms / self.config.purge_half_life_ms
        )
        for region in self._regions:
            for precursor in self.config.precursor_ids:
                region.residuals[precursor] *= factor

    def max_incompatible_residual(self, next_precursor: str) -> float:
        if next_precursor not in self.config.precursor_ids:
            raise SequentialSurfaceError("next_precursor is not declared")
        if self.config.regions == 0:
            return 0.0
        means = []
        for precursor in self.config.precursor_ids:
            if precursor == next_precursor:
                continue
            means.append(
                sum(region.residuals[precursor] for region in self._regions)
                / self.config.regions
            )
        return max(means, default=0.0)

    def snapshot(self) -> SequentialSurfaceSnapshot:
        self._assert_conserved()
        regions = tuple(
            SequentialRegionSnapshot(
                state_counts=tuple(region.state_counts),
                blocked=region.blocked,
                defects=region.defects,
                residuals=MappingProxyType(dict(region.residuals)),
            )
            for region in self._regions
        )
        blocked = sum(region.blocked for region in self._regions)
        defects = sum(region.defects for region in self._regions)
        reactive = self.total_sites - blocked - defects
        residual_means = MappingProxyType(
            {
                precursor: (
                    sum(region.residuals[precursor] for region in self._regions)
                    / self.config.regions
                )
                for precursor in self.config.precursor_ids
            }
        )
        utilization = self._completed_depositions / reactive if reactive else 0.0
        coverage = min(1.0, utilization)
        thickness = (
            self._completed_depositions
            / self.total_sites
            * self.config.growth_nm_per_completion_fraction
            if self.total_sites
            else 0.0
        )
        return SequentialSurfaceSnapshot(
            model_version=self.config.model_version,
            regions=regions,
            total_sites=self.total_sites,
            coverage=coverage,
            thickness_nm=thickness,
            utilization=utilization,
            defect_fraction=defects / self.total_sites if self.total_sites else 0.0,
            completed_depositions=self._completed_depositions,
            residuals=residual_means,
        )

    def _assert_conserved(self) -> None:
        for region in self._regions:
            if min(region.state_counts, default=0) < 0:
                raise SequentialSurfaceError("surface state contains a negative site count")
            if (
                sum(region.state_counts) + region.blocked + region.defects
                != self.config.sites_per_region
            ):
                raise SequentialSurfaceError("surface region site count is not conserved")
            if any(value < 0 or not math.isfinite(value) for value in region.residuals.values()):
                raise SequentialSurfaceError("surface residual inventory is invalid")
