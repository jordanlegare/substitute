"""Deterministic public-reference product scene model for ALD product media.

This module treats Majorana 2 metadata as a display/reference source only. It
never derives fabrication parameters or executable process instructions from
public device geometry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from types import MappingProxyType
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
_VIEW_KEYS = frozenset({"top", "stack", "final"})
_PRODUCT_KEYS = frozenset(
    {
        "gate_layers",
        "layers",
        "packet_root_hash",
        "physical_fabrication_mapping",
        "protocol",
        "quantum_dots",
        "recipe_id",
        "recipe_sha256",
        "reference_status",
        "reference_target",
        "scientific_caveat",
        "simulation_overlay",
        "stage",
        "tetron",
        "unspecified_fields",
        "views",
    }
)
_LAYER_KEYS = frozenset({"material", "role", "specified", "thickness_nm"})
_GATE_KEYS = frozenset({"function", "index", "schematic"})
_DOT_KEYS = frozenset({"index", "label", "schematic", "shared_with_vertical_neighbor"})
_TETRON_KEYS = frozenset(
    {
        "backbone_length_um",
        "backbone_width_nm",
        "horizontal_nanowire_length_um",
        "horizontal_nanowire_width_nm",
        "horizontal_nanowires",
        "shape",
        "target_majorana_zero_modes",
    }
)
_OVERLAY_KEYS = frozenset({"coverage", "defect_fraction", "label", "seed", "thickness_nm"})


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


def _exact_dict(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise core.RecipeError(f"{label} has unexpected or missing fields")
    return value


def _string(value: Any, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise core.RecipeError(f"{label} must be a non-empty plain string")
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


def _digest_bytes(value: Any, label: str) -> bytes:
    if type(value) is not bytes or len(value) != 32:
        raise core.RecipeError(f"{label} must be exactly 32 bytes")
    return value


def _digest_hex(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        raise core.RecipeError(f"{label} must be 64 lowercase hexadecimal characters")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise core.RecipeError(f"{label} must be hexadecimal") from error
    if len(decoded) != 32:
        raise core.RecipeError(f"{label} must decode to 32 bytes")
    return value


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


def build_product_document(
    scene: ProductScene,
    *,
    recipe_sha256: bytes,
    root_hash: bytes,
    view_sha256: Mapping[str, str],
) -> ProductDocument:
    if type(scene) is not ProductScene:
        raise core.RecipeError("product document requires a ProductScene")
    recipe_digest = _digest_bytes(recipe_sha256, "product recipe SHA-256")
    packet_root = _digest_bytes(root_hash, "product packet root hash")
    if not isinstance(view_sha256, Mapping) or set(view_sha256) != _VIEW_KEYS:
        raise core.RecipeError("product view digests must contain top, stack, and final")
    views = {
        key: _digest_hex(view_sha256[key], f"product {key} SVG SHA-256")
        for key in sorted(_VIEW_KEYS)
    }
    return ProductDocument(
        scene=scene,
        recipe_sha256=recipe_digest,
        root_hash=packet_root,
        view_sha256=MappingProxyType(views),
    )


def _product_payload(document: ProductDocument) -> dict[str, Any]:
    scene = document.scene
    return {
        "gate_layers": [
            {"function": item.function, "index": item.index, "schematic": item.schematic}
            for item in scene.gate_layers
        ],
        "layers": [
            {
                "material": item.material,
                "role": item.role,
                "specified": item.specified,
                "thickness_nm": item.thickness_nm,
            }
            for item in scene.layers
        ],
        "packet_root_hash": document.root_hash.hex(),
        "physical_fabrication_mapping": False,
        "protocol": SCENE_PROTOCOL,
        "quantum_dots": [
            {
                "index": item.index,
                "label": item.label,
                "schematic": item.schematic,
                "shared_with_vertical_neighbor": item.shared_with_vertical_neighbor,
            }
            for item in scene.quantum_dots
        ],
        "recipe_id": scene.recipe_id,
        "recipe_sha256": document.recipe_sha256.hex(),
        "reference_status": scene.reference_status,
        "reference_target": scene.reference_target,
        "scientific_caveat": scene.scientific_caveat,
        "simulation_overlay": None
        if scene.overlay is None
        else {
            "coverage": scene.overlay.coverage,
            "defect_fraction": scene.overlay.defect_fraction,
            "label": scene.overlay.label,
            "seed": scene.overlay.seed,
            "thickness_nm": scene.overlay.thickness_nm,
        },
        "stage": scene.stage,
        "tetron": {
            "backbone_length_um": scene.tetron.backbone_length_um,
            "backbone_width_nm": scene.tetron.backbone_width_nm,
            "horizontal_nanowire_length_um": scene.tetron.horizontal_nanowire_length_um,
            "horizontal_nanowire_width_nm": scene.tetron.horizontal_nanowire_width_nm,
            "horizontal_nanowires": scene.tetron.horizontal_nanowires,
            "shape": scene.tetron.shape,
            "target_majorana_zero_modes": scene.tetron.target_majorana_zero_modes,
        },
        "unspecified_fields": list(scene.unspecified_fields),
        "views": dict(sorted(document.view_sha256.items())),
    }


def canonical_product_json(document: ProductDocument) -> bytes:
    if type(document) is not ProductDocument:
        raise core.RecipeError("product JSON requires a ProductDocument")
    try:
        text = json.dumps(
            _product_payload(document),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise core.RecipeError(f"unable to canonicalize product JSON: {error}") from error
    return text.encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if type(key) is not str:
            raise core.RecipeError("product JSON object key must be a string")
        if key in value:
            raise core.RecipeError(f"product JSON contains duplicate key: {key}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> None:
    raise core.RecipeError(f"product JSON contains non-finite number: {value}")


def _parse_layer(value: Any, index: int) -> ProductLayer:
    raw = _exact_dict(value, _LAYER_KEYS, f"product layer {index}")
    role = _string(raw["role"], f"product layer {index} role")
    material = raw["material"]
    if material is not None:
        material = _string(material, f"product layer {index} material")
    thickness = raw["thickness_nm"]
    if thickness is not None:
        thickness = _number(thickness, f"product layer {index} thickness")
    if type(raw["specified"]) is not bool:
        raise core.RecipeError("product layer specified must be boolean")
    if raw["specified"] is not (material is not None and thickness is not None):
        raise core.RecipeError("product layer specified flag does not match source fields")
    return ProductLayer(role, material, thickness, raw["specified"])


def _parse_gate(value: Any, index: int) -> ProductGateLayer:
    raw = _exact_dict(value, _GATE_KEYS, f"product gate layer {index}")
    if raw["schematic"] is not True:
        raise core.RecipeError("product gate layer must remain schematic")
    return ProductGateLayer(
        index=_integer(raw["index"], f"product gate layer {index} index", minimum=1),
        function=_string(raw["function"], f"product gate layer {index} function"),
        schematic=True,
    )


def _parse_dot(value: Any, index: int) -> ProductQuantumDot:
    raw = _exact_dict(value, _DOT_KEYS, f"product quantum dot {index}")
    if raw["schematic"] is not True or type(raw["shared_with_vertical_neighbor"]) is not bool:
        raise core.RecipeError("product quantum-dot schematic fields are invalid")
    return ProductQuantumDot(
        index=_integer(raw["index"], f"product quantum dot {index} index", minimum=1),
        label=_string(raw["label"], f"product quantum dot {index} label"),
        shared_with_vertical_neighbor=raw["shared_with_vertical_neighbor"],
        schematic=True,
    )


def parse_product_json(raw: bytes) -> ProductDocument:
    if type(raw) is not bytes or not raw:
        raise core.RecipeError("product JSON must be non-empty exact bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise core.RecipeError("product JSON is not valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except core.RecipeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise core.RecipeError("product JSON is not valid JSON") from error

    root = _exact_dict(value, _PRODUCT_KEYS, "product JSON")
    if root["protocol"] != SCENE_PROTOCOL:
        raise core.RecipeError(f"product JSON protocol must be {SCENE_PROTOCOL}")
    if root["physical_fabrication_mapping"] is not False:
        raise core.RecipeError("product JSON physical_fabrication_mapping must be false")
    stage = _string(root["stage"], "product stage")
    if stage not in PRODUCT_STAGES:
        raise core.RecipeError("product JSON stage is unsupported")

    layers_raw = root["layers"]
    gates_raw = root["gate_layers"]
    dots_raw = root["quantum_dots"]
    unspecified_raw = root["unspecified_fields"]
    if type(layers_raw) is not list or not layers_raw:
        raise core.RecipeError("product JSON layers must be a non-empty array")
    if type(gates_raw) is not list or not gates_raw:
        raise core.RecipeError("product JSON gate_layers must be a non-empty array")
    if type(dots_raw) is not list or not dots_raw:
        raise core.RecipeError("product JSON quantum_dots must be a non-empty array")
    if type(unspecified_raw) is not list or any(type(item) is not str for item in unspecified_raw):
        raise core.RecipeError("product JSON unspecified_fields must be a string array")

    tetron_raw = _exact_dict(root["tetron"], _TETRON_KEYS, "product tetron")
    tetron = ProductTetron(
        shape=_string(tetron_raw["shape"], "product tetron shape"),
        horizontal_nanowires=_integer(
            tetron_raw["horizontal_nanowires"], "product tetron horizontal_nanowires", minimum=1
        ),
        horizontal_nanowire_length_um=_number(
            tetron_raw["horizontal_nanowire_length_um"], "product tetron horizontal_nanowire_length_um"
        ),
        horizontal_nanowire_width_nm=_number(
            tetron_raw["horizontal_nanowire_width_nm"], "product tetron horizontal_nanowire_width_nm"
        ),
        backbone_length_um=_number(tetron_raw["backbone_length_um"], "product tetron backbone_length_um"),
        backbone_width_nm=_number(tetron_raw["backbone_width_nm"], "product tetron backbone_width_nm"),
        target_majorana_zero_modes=_integer(
            tetron_raw["target_majorana_zero_modes"], "product tetron target_majorana_zero_modes", minimum=1
        ),
    )

    overlay_raw = root["simulation_overlay"]
    overlay: SimulationOverlay | None
    if overlay_raw is None:
        overlay = None
    else:
        overlay_value = _exact_dict(overlay_raw, _OVERLAY_KEYS, "product simulation overlay")
        overlay = SimulationOverlay(
            seed=_integer(overlay_value["seed"], "product simulation seed"),
            coverage=_number(overlay_value["coverage"], "product simulation coverage"),
            thickness_nm=_number(overlay_value["thickness_nm"], "product simulation thickness"),
            defect_fraction=_number(overlay_value["defect_fraction"], "product simulation defect fraction"),
            label=_string(overlay_value["label"], "product simulation label"),
        )

    views_raw = _exact_dict(root["views"], _VIEW_KEYS, "product view digests")
    views = {
        key: _digest_hex(views_raw[key], f"product {key} SVG SHA-256")
        for key in sorted(_VIEW_KEYS)
    }
    recipe_digest_hex = _digest_hex(root["recipe_sha256"], "product recipe SHA-256")
    root_digest_hex = _digest_hex(root["packet_root_hash"], "product packet root hash")

    scene = ProductScene(
        protocol=SCENE_PROTOCOL,
        recipe_id=_string(root["recipe_id"], "product recipe_id"),
        reference_target=_string(root["reference_target"], "product reference_target"),
        reference_status=_string(root["reference_status"], "product reference_status"),
        scientific_caveat=_string(root["scientific_caveat"], "product scientific_caveat"),
        physical_fabrication_mapping=False,
        stage=stage,
        layers=tuple(_parse_layer(item, index) for index, item in enumerate(layers_raw)),
        tetron=tetron,
        gate_layers=tuple(_parse_gate(item, index) for index, item in enumerate(gates_raw)),
        quantum_dots=tuple(_parse_dot(item, index) for index, item in enumerate(dots_raw)),
        unspecified_fields=tuple(unspecified_raw),
        overlay=overlay,
    )
    document = ProductDocument(
        scene=scene,
        recipe_sha256=bytes.fromhex(recipe_digest_hex),
        root_hash=bytes.fromhex(root_digest_hex),
        view_sha256=MappingProxyType(views),
    )
    if canonical_product_json(document) != raw:
        raise core.RecipeError("product JSON is not canonical sorted compact JSON")
    return document
