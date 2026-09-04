"""Deterministic public-reference product scene model for ALD product media.

This module treats Majorana 2 metadata as a display/reference source only. It
never derives fabrication parameters or executable process instructions from
public device geometry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

import ald_hardened_core as core


SCENE_PROTOCOL = "ALD-PRODUCT-SCENE/1"
PRODUCT_STAGES = (
    "reference-stack",
    "tetron",
    "gates",
    "quantum-dots",
    "simulation-status",
    "final",
)
_UNSPECIFIED_TEXT_PREFIXES = ("not publicly specified", "unspecified")


@dataclass(frozen=True)
class ProductLayer:
    role: str
    material: str | None
    thickness_nm: float | None
    specified: bool


@dataclass(frozen=True)
class ProductTetron:
    shape: str
    horizontal_nanowires: int
    horizontal_nanowire_length_um: float
    horizontal_nanowire_width_nm: float
    backbone_length_um: float
    backbone_width_nm: float
    target_majorana_zero_modes: int


@dataclass(frozen=True)
class ProductGateLayer:
    index: int
    function: str
    schematic: bool = True


@dataclass(frozen=True)
class ProductQuantumDot:
    index: int
    label: str
    shared_with_vertical_neighbor: bool
    schematic: bool = True


@dataclass(frozen=True)
class SimulationOverlay:
    seed: int
    coverage: float
    thickness_nm: float
    defect_fraction: float
    label: str = "generic A/B surrogate simulation status"


@dataclass(frozen=True)
class ProductScene:
    protocol: str
    recipe_id: str
    reference_target: str
    reference_status: str
    scientific_caveat: str
    physical_fabrication_mapping: bool
    stage: str
    layers: tuple[ProductLayer, ...]
    tetron: ProductTetron
    gate_layers: tuple[ProductGateLayer, ...]
    quantum_dots: tuple[ProductQuantumDot, ...]
    unspecified_fields: tuple[str, ...]
    overlay: SimulationOverlay | None


@dataclass(frozen=True)
class ProductDocument:
    scene: ProductScene
    recipe_sha256: bytes
    root_hash: bytes
    view_sha256: Mapping[str, str]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise core.RecipeError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise core.RecipeError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise core.RecipeError(f"{label} must be an integer >= {minimum}")
    return value


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        raise core.RecipeError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise core.RecipeError(f"{label} must be a finite number >= {minimum:g}")
    return result


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    text = _string(value, label)
    normalized = text.strip().casefold()
    if any(normalized.startswith(prefix) for prefix in _UNSPECIFIED_TEXT_PREFIXES):
        return None
    return text


def _optional_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    return _number(value, label)


def _layer_from_record(role: str, record: Any) -> ProductLayer:
    value = _mapping(record, f"material_stack.{role}")
    material = _optional_string(value.get("composition"), f"material_stack.{role}.composition")
    thickness = _optional_number(value.get("thickness_nm"), f"material_stack.{role}.thickness_nm")
    return ProductLayer(
        role=role,
        material=material,
        thickness_nm=thickness,
        specified=material is not None and thickness is not None,
    )


def _build_layers(public_reference: Mapping[str, Any]) -> tuple[ProductLayer, ...]:
    stack = _mapping(public_reference.get("material_stack"), "public_device_reference.material_stack")
    substrate = _string(stack.get("substrate"), "material_stack.substrate")
    quantum_well = stack.get("quantum_well")
    if not isinstance(quantum_well, Sequence) or isinstance(quantum_well, (str, bytes)):
        raise core.RecipeError("material_stack.quantum_well must be an array")
    wells = tuple(quantum_well)
    if len(wells) != 2:
        raise core.RecipeError("material_stack.quantum_well must contain exactly two public reference layers")
    inas = _mapping(wells[0], "material_stack.quantum_well[0]")
    inassb = _mapping(wells[1], "material_stack.quantum_well[1]")
    superconductor = _mapping(stack.get("superconductor"), "material_stack.superconductor")

    return (
        ProductLayer("substrate", substrate, None, False),
        _layer_from_record("buffer", stack.get("buffer")),
        _layer_from_record("bottom_barrier", stack.get("bottom_barrier")),
        ProductLayer(
            "quantum_well_inas",
            _string(inas.get("material"), "quantum_well[0].material"),
            _number(inas.get("thickness_nm"), "quantum_well[0].thickness_nm"),
            True,
        ),
        ProductLayer(
            "quantum_well_inassb",
            _string(inassb.get("material"), "quantum_well[1].material"),
            _number(inassb.get("thickness_nm"), "quantum_well[1].thickness_nm"),
            True,
        ),
        _layer_from_record("top_barrier", stack.get("top_barrier")),
        ProductLayer(
            "superconductor",
            _string(superconductor.get("material"), "material_stack.superconductor.material"),
            _number(superconductor.get("thickness_nm"), "material_stack.superconductor.thickness_nm"),
            True,
        ),
    )


def _build_tetron(public_reference: Mapping[str, Any]) -> ProductTetron:
    value = _mapping(public_reference.get("tetron_geometry"), "public_device_reference.tetron_geometry")
    return ProductTetron(
        shape=_string(value.get("shape"), "tetron_geometry.shape"),
        horizontal_nanowires=_integer(value.get("horizontal_nanowires"), "tetron_geometry.horizontal_nanowires", minimum=1),
        horizontal_nanowire_length_um=_number(value.get("horizontal_nanowire_length_um"), "tetron_geometry.horizontal_nanowire_length_um"),
        horizontal_nanowire_width_nm=_number(value.get("horizontal_nanowire_width_nm"), "tetron_geometry.horizontal_nanowire_width_nm"),
        backbone_length_um=_number(value.get("backbone_length_um"), "tetron_geometry.backbone_length_um"),
        backbone_width_nm=_number(value.get("backbone_width_nm"), "tetron_geometry.backbone_width_nm"),
        target_majorana_zero_modes=_integer(value.get("target_majorana_zero_modes_per_tetron"), "tetron_geometry.target_majorana_zero_modes_per_tetron", minimum=1),
    )


def _build_gates_and_dots(
    public_reference: Mapping[str, Any],
) -> tuple[tuple[ProductGateLayer, ...], tuple[ProductQuantumDot, ...]]:
    value = _mapping(public_reference.get("gate_architecture"), "public_device_reference.gate_architecture")
    layer_count = _integer(value.get("functional_gate_layers"), "gate_architecture.functional_gate_layers", minimum=1)
    functions = value.get("functions")
    if not isinstance(functions, Sequence) or isinstance(functions, (str, bytes)):
        raise core.RecipeError("gate_architecture.functions must be an array")
    function_values = tuple(functions)
    if len(function_values) != layer_count:
        raise core.RecipeError("gate_architecture.functions must match functional_gate_layers")
    gate_layers = tuple(
        ProductGateLayer(index=index + 1, function=_string(function, f"gate_architecture.functions[{index}]"))
        for index, function in enumerate(function_values)
    )

    dot_count = _integer(value.get("quantum_dots_per_tetron"), "gate_architecture.quantum_dots_per_tetron", minimum=1)
    shared_count = _integer(
        value.get("shared_quantum_dots_with_vertical_neighbors"),
        "gate_architecture.shared_quantum_dots_with_vertical_neighbors",
        minimum=0,
    )
    if shared_count > dot_count:
        raise core.RecipeError("shared quantum-dot count exceeds quantum_dots_per_tetron")
    quantum_dots = tuple(
        ProductQuantumDot(
            index=index + 1,
            label=f"QD{index + 1}",
            shared_with_vertical_neighbor=index < shared_count,
        )
        for index in range(dot_count)
    )
    return gate_layers, quantum_dots


def _build_overlay(simulation: core.SimulationResult | None) -> SimulationOverlay | None:
    if simulation is None:
        return None
    if type(simulation) is not core.SimulationResult:
        raise core.RecipeError("product simulation overlay must use a SimulationResult")
    if simulation.fault is not None:
        raise core.RecipeError("faulted simulation cannot populate product visualization")
    if type(simulation.seed) is not int:
        raise core.RecipeError("product simulation overlay requires an integer seed")
    return SimulationOverlay(
        seed=simulation.seed,
        coverage=float(simulation.surface.coverage),
        thickness_nm=float(simulation.surface.thickness_nm),
        defect_fraction=float(simulation.surface.defect_fraction),
    )


def build_product_scene(
    recipe: core.Recipe,
    *,
    stage: str,
    simulation: core.SimulationResult | None = None,
) -> ProductScene:
    """Build one deterministic Majorana 2 public-reference display scene."""
    if type(recipe) is not core.Recipe:
        raise core.RecipeError("product scene requires a validated recipe")
    if type(stage) is not str or stage not in PRODUCT_STAGES:
        raise core.RecipeError("unsupported product visualization stage")

    metadata = _mapping(recipe.metadata, "metadata")
    public_reference = _mapping(
        metadata.get("public_device_reference"),
        "metadata.public_device_reference",
    )
    simulation_mapping = _mapping(metadata.get("simulation_mapping"), "metadata.simulation_mapping")
    if simulation_mapping.get("physical_fabrication_mapping") is not False:
        raise core.RecipeError("product visualization requires physical_fabrication_mapping=false")

    layers = _build_layers(public_reference)
    gate_layers, quantum_dots = _build_gates_and_dots(public_reference)
    unspecified: list[str] = []
    for layer in layers:
        if layer.material is None:
            unspecified.append(f"material_stack.{layer.role}.material")
        if layer.thickness_nm is None:
            unspecified.append(f"material_stack.{layer.role}.thickness_nm")

    overlay = _build_overlay(simulation) if stage in {"simulation-status", "final"} else None

    return ProductScene(
        protocol=SCENE_PROTOCOL,
        recipe_id=recipe.recipe_id,
        reference_target=_string(metadata.get("reference_target"), "metadata.reference_target"),
        reference_status=_string(metadata.get("reference_status"), "metadata.reference_status"),
        scientific_caveat=_string(metadata.get("scientific_caveat"), "metadata.scientific_caveat"),
        physical_fabrication_mapping=False,
        stage=stage,
        layers=layers,
        tetron=_build_tetron(public_reference),
        gate_layers=gate_layers,
        quantum_dots=quantum_dots,
        unspecified_fields=tuple(unspecified),
        overlay=overlay,
    )
