"""Product-scene dispatcher preserving Majorana rendering and adding surrogate products."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from types import MappingProxyType
from typing import Any, TypeAlias

import ald_hardened_core as core
import ald_product_scene_majorana as _majorana
from ald_product_scene_majorana import *  # noqa: F401,F403


SURROGATE_SCENE_KIND = "surrogate-product"
_SURROGATE_PRODUCT_KEYS = frozenset(
    {
        "commercial_context",
        "film_role",
        "modeled_scope",
        "packet_root_hash",
        "physical_fabrication_mapping",
        "product_family",
        "protocol",
        "recipe_id",
        "recipe_sha256",
        "regions",
        "scene_kind",
        "simulation_notice",
        "simulation_overlay",
        "stage",
        "views",
    }
)
_SURROGATE_REGION_KEYS = frozenset({"index", "label", "transport_factor"})
_VIEW_KEYS = frozenset({"top", "stack", "final"})
_OVERLAY_KEYS = frozenset({"coverage", "defect_fraction", "label", "seed", "thickness_nm"})


@dataclass(frozen=True)
class SurrogateProductRegion:
    index: int
    label: str
    transport_factor: float


@dataclass(frozen=True)
class SurrogateProductScene:
    protocol: str
    recipe_id: str
    product_family: str
    commercial_context: str
    film_role: str
    modeled_scope: str
    simulation_notice: str
    physical_fabrication_mapping: bool
    stage: str
    regions: tuple[SurrogateProductRegion, ...]
    overlay: SimulationOverlay | None


ProductSceneLike: TypeAlias = ProductScene | SurrogateProductScene


def is_surrogate_scene(scene: object) -> bool:
    return type(scene) is SurrogateProductScene


def _plain_string(value: Any, label: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 0x20 for character in value):
        raise core.RecipeError(f"{label} must be a non-empty plain string")
    return value


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        raise core.RecipeError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise core.RecipeError(f"{label} must be a finite number >= {minimum:g}")
    return result


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


def _build_surrogate_scene(
    recipe: core.Recipe,
    *,
    stage: str,
    simulation: core.SimulationResult | None,
) -> SurrogateProductScene:
    if stage not in PRODUCT_STAGES:
        raise core.RecipeError("unsupported product visualization stage")
    metadata = recipe.metadata
    if not isinstance(metadata, Mapping):
        raise core.RecipeError("metadata must be an object")
    if metadata.get("physical_fabrication_mapping") is not False:
        raise core.RecipeError("surrogate product visualization requires physical_fabrication_mapping=false")

    region_semantics = metadata.get("region_semantics")
    if not isinstance(region_semantics, Sequence) or isinstance(region_semantics, (str, bytes)):
        raise core.RecipeError("metadata.region_semantics must be an array")
    labels = tuple(
        _plain_string(item, f"metadata.region_semantics[{index}]")
        for index, item in enumerate(region_semantics)
    )
    if not labels:
        raise core.RecipeError("metadata.region_semantics must not be empty")

    surface = recipe.surface
    if not isinstance(surface, Mapping):
        raise core.RecipeError("surface must be an object")
    region_count = surface.get("regions")
    if type(region_count) is not int or region_count <= 0:
        raise core.RecipeError("surface.regions must be a positive integer")
    if len(labels) != region_count:
        raise core.RecipeError("metadata.region_semantics must contain one label per surface region")
    transport_raw = surface.get("transport_factors")
    if not isinstance(transport_raw, Sequence) or isinstance(transport_raw, (str, bytes)):
        raise core.RecipeError("surface.transport_factors must be an array")
    transport = tuple(
        _number(item, f"surface.transport_factors[{index}]")
        for index, item in enumerate(transport_raw)
    )
    if len(transport) != region_count:
        raise core.RecipeError("surface.transport_factors must contain one value per surface region")

    overlay = _majorana._build_overlay(simulation) if stage in {"simulation-status", "final"} else None
    return SurrogateProductScene(
        protocol=SCENE_PROTOCOL,
        recipe_id=recipe.recipe_id,
        product_family=_plain_string(metadata.get("product_family"), "metadata.product_family"),
        commercial_context=_plain_string(metadata.get("commercial_context"), "metadata.commercial_context"),
        film_role=_plain_string(metadata.get("film_role"), "metadata.film_role"),
        modeled_scope=_plain_string(metadata.get("modeled_scope"), "metadata.modeled_scope"),
        simulation_notice=_plain_string(metadata.get("simulation_notice"), "metadata.simulation_notice"),
        physical_fabrication_mapping=False,
        stage=stage,
        regions=tuple(
            SurrogateProductRegion(index=index + 1, label=label, transport_factor=transport[index])
            for index, label in enumerate(labels)
        ),
        overlay=overlay,
    )


def build_product_scene(
    recipe: core.Recipe,
    *,
    stage: str,
    simulation: core.SimulationResult | None = None,
) -> ProductSceneLike:
    """Build a strict Majorana-reference or generic surrogate-product display scene."""
    if type(recipe) is not core.Recipe:
        raise core.RecipeError("product scene requires a validated recipe")
    metadata = recipe.metadata
    if isinstance(metadata, Mapping) and (
        "product_family" in metadata or "region_semantics" in metadata
    ):
        return _build_surrogate_scene(recipe, stage=stage, simulation=simulation)
    return _majorana.build_product_scene(recipe, stage=stage, simulation=simulation)


def build_product_document(
    scene: ProductSceneLike,
    *,
    recipe_sha256: bytes,
    root_hash: bytes,
    view_sha256: Mapping[str, str],
) -> ProductDocument:
    if type(scene) is ProductScene:
        return _majorana.build_product_document(
            scene,
            recipe_sha256=recipe_sha256,
            root_hash=root_hash,
            view_sha256=view_sha256,
        )
    if type(scene) is not SurrogateProductScene:
        raise core.RecipeError("product document requires a supported product scene")
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


def _overlay_payload(overlay: SimulationOverlay | None) -> dict[str, Any] | None:
    if overlay is None:
        return None
    return {
        "coverage": overlay.coverage,
        "defect_fraction": overlay.defect_fraction,
        "label": overlay.label,
        "seed": overlay.seed,
        "thickness_nm": overlay.thickness_nm,
    }


def _surrogate_payload(document: ProductDocument) -> dict[str, Any]:
    scene = document.scene
    if type(scene) is not SurrogateProductScene:
        raise core.RecipeError("surrogate product JSON requires a SurrogateProductScene")
    return {
        "commercial_context": scene.commercial_context,
        "film_role": scene.film_role,
        "modeled_scope": scene.modeled_scope,
        "packet_root_hash": document.root_hash.hex(),
        "physical_fabrication_mapping": False,
        "product_family": scene.product_family,
        "protocol": SCENE_PROTOCOL,
        "recipe_id": scene.recipe_id,
        "recipe_sha256": document.recipe_sha256.hex(),
        "regions": [
            {
                "index": region.index,
                "label": region.label,
                "transport_factor": region.transport_factor,
            }
            for region in scene.regions
        ],
        "scene_kind": SURROGATE_SCENE_KIND,
        "simulation_notice": scene.simulation_notice,
        "simulation_overlay": _overlay_payload(scene.overlay),
        "stage": scene.stage,
        "views": dict(sorted(document.view_sha256.items())),
    }


def canonical_product_json(document: ProductDocument) -> bytes:
    if type(document) is not ProductDocument:
        raise core.RecipeError("product JSON requires a ProductDocument")
    if type(document.scene) is ProductScene:
        return _majorana.canonical_product_json(document)
    if type(document.scene) is not SurrogateProductScene:
        raise core.RecipeError("product JSON requires a supported product scene")
    try:
        text = json.dumps(
            _surrogate_payload(document),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise core.RecipeError(f"unable to canonicalize product JSON: {error}") from error
    return text.encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise core.RecipeError("product JSON object key must be a string")
        if key in result:
            raise core.RecipeError(f"product JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise core.RecipeError(f"product JSON contains non-finite number: {value}")


def _parse_overlay(value: Any) -> SimulationOverlay | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _OVERLAY_KEYS:
        raise core.RecipeError("product simulation_overlay has unexpected or missing fields")
    seed = value["seed"]
    if type(seed) is not int:
        raise core.RecipeError("product simulation overlay seed must be an integer")
    return SimulationOverlay(
        seed=seed,
        coverage=_number(value["coverage"], "product simulation overlay coverage"),
        thickness_nm=_number(value["thickness_nm"], "product simulation overlay thickness"),
        defect_fraction=_number(value["defect_fraction"], "product simulation overlay defect fraction"),
        label=_plain_string(value["label"], "product simulation overlay label"),
    )


def _parse_surrogate_product(value: dict[str, Any], raw: bytes) -> ProductDocument:
    if set(value) != _SURROGATE_PRODUCT_KEYS:
        raise core.RecipeError("surrogate product JSON has unexpected or missing fields")
    if value["scene_kind"] != SURROGATE_SCENE_KIND:
        raise core.RecipeError("surrogate product JSON scene_kind is invalid")
    if value["protocol"] != SCENE_PROTOCOL:
        raise core.RecipeError(f"product JSON protocol must be {SCENE_PROTOCOL}")
    if value["physical_fabrication_mapping"] is not False:
        raise core.RecipeError("product JSON physical_fabrication_mapping must be false")
    stage = _plain_string(value["stage"], "product stage")
    if stage not in PRODUCT_STAGES:
        raise core.RecipeError("product JSON stage is unsupported")

    regions_raw = value["regions"]
    if type(regions_raw) is not list or not regions_raw:
        raise core.RecipeError("surrogate product JSON regions must be a non-empty array")
    regions: list[SurrogateProductRegion] = []
    for index, item in enumerate(regions_raw):
        if type(item) is not dict or set(item) != _SURROGATE_REGION_KEYS:
            raise core.RecipeError(f"surrogate product region {index} has unexpected or missing fields")
        expected_index = index + 1
        if type(item["index"]) is not int or item["index"] != expected_index:
            raise core.RecipeError("surrogate product region indexes must be contiguous and one-based")
        regions.append(
            SurrogateProductRegion(
                index=expected_index,
                label=_plain_string(item["label"], f"surrogate product region {index} label"),
                transport_factor=_number(
                    item["transport_factor"],
                    f"surrogate product region {index} transport_factor",
                ),
            )
        )

    views_raw = value["views"]
    if type(views_raw) is not dict or set(views_raw) != _VIEW_KEYS:
        raise core.RecipeError("product JSON views must contain final, stack, and top")
    views = MappingProxyType(
        {
            key: _digest_hex(views_raw[key], f"product {key} SVG SHA-256")
            for key in sorted(_VIEW_KEYS)
        }
    )
    scene = SurrogateProductScene(
        protocol=SCENE_PROTOCOL,
        recipe_id=_plain_string(value["recipe_id"], "product recipe_id"),
        product_family=_plain_string(value["product_family"], "product product_family"),
        commercial_context=_plain_string(value["commercial_context"], "product commercial_context"),
        film_role=_plain_string(value["film_role"], "product film_role"),
        modeled_scope=_plain_string(value["modeled_scope"], "product modeled_scope"),
        simulation_notice=_plain_string(value["simulation_notice"], "product simulation_notice"),
        physical_fabrication_mapping=False,
        stage=stage,
        regions=tuple(regions),
        overlay=_parse_overlay(value["simulation_overlay"]),
    )
    document = ProductDocument(
        scene=scene,
        recipe_sha256=bytes.fromhex(_digest_hex(value["recipe_sha256"], "product recipe")),
        root_hash=bytes.fromhex(_digest_hex(value["packet_root_hash"], "product packet root")),
        view_sha256=views,
    )
    if canonical_product_json(document) != raw:
        raise core.RecipeError("surrogate product JSON is not canonical sorted compact JSON")
    return document


def parse_product_json(raw: bytes) -> ProductDocument:
    if type(raw) is not bytes or not raw:
        raise core.RecipeError("product JSON must be non-empty exact bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except core.RecipeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise core.RecipeError("product JSON is not valid JSON") from error
    if type(value) is dict and value.get("scene_kind") == SURROGATE_SCENE_KIND:
        return _parse_surrogate_product(value, raw)
    return _majorana.parse_product_json(raw)
