"""Product-scene facade adding strict multi-precursor surrogate scenes.

Legacy Majorana and generic surrogate behavior is delegated unchanged to
``_ald_product_scene_legacy``. Multi-precursor recipes receive an extended
surrogate document containing the target material and ordered real chemical
identities, but never executable dose/purge/controller values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, TypeAlias

import ald_hardened_core as core
import _ald_product_scene_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_MULTI_SCHEMA = "multi-precursor/1"
_MULTI_PRODUCT_KEYS = frozenset(
    set(_legacy._SURROGATE_PRODUCT_KEYS)
    | {"recipe_schema", "target_material", "precursor_sequence"}
)
_PRECURSOR_KEYS = frozenset({"id", "name", "formula"})


@dataclass(frozen=True)
class NamedPrecursorStage:
    id: str
    name: str
    formula: str


@dataclass(frozen=True)
class MultiPrecursorProductScene:
    protocol: str
    recipe_id: str
    recipe_schema: str
    target_material: str
    product_family: str
    commercial_context: str
    film_role: str
    modeled_scope: str
    simulation_notice: str
    physical_fabrication_mapping: bool
    stage: str
    regions: tuple[_legacy.SurrogateProductRegion, ...]
    precursor_sequence: tuple[NamedPrecursorStage, ...]
    overlay: _legacy.SimulationOverlay | None


ProductSceneLike: TypeAlias = _legacy.ProductScene | _legacy.SurrogateProductScene | MultiPrecursorProductScene


def is_surrogate_scene(scene: object) -> bool:
    return type(scene) in (_legacy.SurrogateProductScene, MultiPrecursorProductScene)


def _plain(value: Any, label: str) -> str:
    return _legacy._plain_string(value, label)


def _multi_scene(recipe: core.Recipe, *, stage: str, simulation=None) -> MultiPrecursorProductScene:
    if stage not in _legacy.PRODUCT_STAGES:
        raise core.RecipeError("unsupported product visualization stage")
    metadata = recipe.metadata
    if metadata.get("recipe_schema") != _MULTI_SCHEMA:
        raise core.RecipeError("multi-precursor product scene requires multi-precursor/1")
    if metadata.get("physical_fabrication_mapping") is not False:
        raise core.RecipeError("multi-precursor product visualization requires physical_fabrication_mapping=false")

    target = _plain(metadata.get("target_material"), "metadata.target_material")
    product_family = _plain(metadata.get("product_family"), "metadata.product_family")
    commercial_context = _plain(metadata.get("commercial_context", product_family), "metadata.commercial_context")
    film_role = _plain(metadata.get("film_role", f"{target} simulated film"), "metadata.film_role")
    modeled_scope = _plain(
        metadata.get("modeled_scope", "Sequential multi-precursor surface-state simulation"),
        "metadata.modeled_scope",
    )
    notice = _plain(metadata.get("simulation_notice"), "metadata.simulation_notice")

    surface = recipe.surface
    region_count = surface.get("regions")
    if type(region_count) is not int or region_count <= 0:
        raise core.RecipeError("surface.regions must be a positive integer")
    transport_raw = surface.get("transport_factors")
    if not isinstance(transport_raw, Sequence) or isinstance(transport_raw, (str, bytes)):
        raise core.RecipeError("surface.transport_factors must be an array")
    transport = tuple(
        _legacy._number(value, f"surface.transport_factors[{index}]")
        for index, value in enumerate(transport_raw)
    )
    if len(transport) != region_count:
        raise core.RecipeError("surface.transport_factors must contain one value per surface region")

    semantics = metadata.get("region_semantics")
    if semantics is None:
        labels = tuple(f"simulation region {index + 1}" for index in range(region_count))
    else:
        if not isinstance(semantics, Sequence) or isinstance(semantics, (str, bytes)):
            raise core.RecipeError("metadata.region_semantics must be an array")
        labels = tuple(_plain(value, f"metadata.region_semantics[{index}]") for index, value in enumerate(semantics))
        if len(labels) != region_count:
            raise core.RecipeError("metadata.region_semantics must contain one label per surface region")

    deposition = next(
        (instruction for instruction in recipe.instructions if instruction["opcode"] == "DEPOSITION_CYCLE"),
        None,
    )
    if deposition is None:
        raise core.RecipeError("multi-precursor product scene requires DEPOSITION_CYCLE")
    sequence: list[NamedPrecursorStage] = []
    for exposure in deposition["arguments"]["exposures"]:
        precursor_id = exposure["precursor"]
        identity = recipe.precursors[precursor_id]
        sequence.append(
            NamedPrecursorStage(
                id=precursor_id,
                name=_plain(identity["name"], f"precursors.{precursor_id}.name"),
                formula=_plain(identity["formula"], f"precursors.{precursor_id}.formula"),
            )
        )

    overlay = _legacy._majorana._build_overlay(simulation) if stage in {"simulation-status", "final"} else None
    return MultiPrecursorProductScene(
        protocol=_legacy.SCENE_PROTOCOL,
        recipe_id=recipe.recipe_id,
        recipe_schema=_MULTI_SCHEMA,
        target_material=target,
        product_family=product_family,
        commercial_context=commercial_context,
        film_role=film_role,
        modeled_scope=modeled_scope,
        simulation_notice=notice,
        physical_fabrication_mapping=False,
        stage=stage,
        regions=tuple(
            _legacy.SurrogateProductRegion(index=index + 1, label=labels[index], transport_factor=transport[index])
            for index in range(region_count)
        ),
        precursor_sequence=tuple(sequence),
        overlay=overlay,
    )


def build_product_scene(recipe: core.Recipe, *, stage: str, simulation=None) -> ProductSceneLike:
    if type(recipe) is not core.Recipe:
        raise core.RecipeError("product scene requires a validated recipe")
    if recipe.metadata.get("recipe_schema") == _MULTI_SCHEMA:
        return _multi_scene(recipe, stage=stage, simulation=simulation)
    return _legacy.build_product_scene(recipe, stage=stage, simulation=simulation)


def build_product_document(scene: ProductSceneLike, *, recipe_sha256: bytes, root_hash: bytes, view_sha256: Mapping[str, str]):
    if type(scene) is not MultiPrecursorProductScene:
        return _legacy.build_product_document(
            scene, recipe_sha256=recipe_sha256, root_hash=root_hash, view_sha256=view_sha256
        )
    recipe_digest = _legacy._digest_bytes(recipe_sha256, "product recipe SHA-256")
    packet_root = _legacy._digest_bytes(root_hash, "product packet root hash")
    if not isinstance(view_sha256, Mapping) or set(view_sha256) != _legacy._VIEW_KEYS:
        raise core.RecipeError("product view digests must contain top, stack, and final")
    views = MappingProxyType(
        {
            key: _legacy._digest_hex(view_sha256[key], f"product {key} SVG SHA-256")
            for key in sorted(_legacy._VIEW_KEYS)
        }
    )
    return _legacy.ProductDocument(scene=scene, recipe_sha256=recipe_digest, root_hash=packet_root, view_sha256=views)


def _multi_payload(document) -> dict[str, Any]:
    scene = document.scene
    return {
        "commercial_context": scene.commercial_context,
        "film_role": scene.film_role,
        "modeled_scope": scene.modeled_scope,
        "packet_root_hash": document.root_hash.hex(),
        "physical_fabrication_mapping": False,
        "precursor_sequence": [
            {"formula": item.formula, "id": item.id, "name": item.name}
            for item in scene.precursor_sequence
        ],
        "product_family": scene.product_family,
        "protocol": _legacy.SCENE_PROTOCOL,
        "recipe_id": scene.recipe_id,
        "recipe_schema": scene.recipe_schema,
        "recipe_sha256": document.recipe_sha256.hex(),
        "regions": [
            {"index": region.index, "label": region.label, "transport_factor": region.transport_factor}
            for region in scene.regions
        ],
        "scene_kind": _legacy.SURROGATE_SCENE_KIND,
        "simulation_notice": scene.simulation_notice,
        "simulation_overlay": _legacy._overlay_payload(scene.overlay),
        "stage": scene.stage,
        "target_material": scene.target_material,
        "views": dict(sorted(document.view_sha256.items())),
    }


def canonical_product_json(document) -> bytes:
    if type(document) is not _legacy.ProductDocument:
        raise core.RecipeError("product JSON requires a ProductDocument")
    if type(document.scene) is not MultiPrecursorProductScene:
        return _legacy.canonical_product_json(document)
    try:
        return (
            json.dumps(_multi_payload(document), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise core.RecipeError(f"unable to canonicalize product JSON: {error}") from error


def _parse_multi(value: dict[str, Any], raw: bytes):
    if set(value) != _MULTI_PRODUCT_KEYS:
        raise core.RecipeError("multi-precursor product JSON has unexpected or missing fields")
    if value["scene_kind"] != _legacy.SURROGATE_SCENE_KIND or value["recipe_schema"] != _MULTI_SCHEMA:
        raise core.RecipeError("multi-precursor product JSON identity is invalid")
    if value["physical_fabrication_mapping"] is not False:
        raise core.RecipeError("product JSON physical_fabrication_mapping must be false")
    stage = _plain(value["stage"], "product stage")
    if stage not in _legacy.PRODUCT_STAGES:
        raise core.RecipeError("product JSON stage is unsupported")

    regions = []
    regions_raw = value["regions"]
    if type(regions_raw) is not list or not regions_raw:
        raise core.RecipeError("multi-precursor product regions must be a non-empty array")
    for index, item in enumerate(regions_raw):
        if type(item) is not dict or set(item) != _legacy._SURROGATE_REGION_KEYS or item["index"] != index + 1:
            raise core.RecipeError("multi-precursor product regions are invalid")
        regions.append(
            _legacy.SurrogateProductRegion(
                index=index + 1,
                label=_plain(item["label"], "product region label"),
                transport_factor=_legacy._number(item["transport_factor"], "product region transport_factor"),
            )
        )

    sequence = []
    sequence_raw = value["precursor_sequence"]
    if type(sequence_raw) is not list or not 2 <= len(sequence_raw) <= 12:
        raise core.RecipeError("product precursor_sequence must contain 2 to 12 stages")
    for item in sequence_raw:
        if type(item) is not dict or set(item) != _PRECURSOR_KEYS:
            raise core.RecipeError("product precursor_sequence entry is invalid")
        sequence.append(
            NamedPrecursorStage(
                id=_plain(item["id"], "product precursor id"),
                name=_plain(item["name"], "product precursor name"),
                formula=_plain(item["formula"], "product precursor formula"),
            )
        )

    views_raw = value["views"]
    if type(views_raw) is not dict or set(views_raw) != _legacy._VIEW_KEYS:
        raise core.RecipeError("product JSON views must contain final, stack, and top")
    views = MappingProxyType(
        {key: _legacy._digest_hex(views_raw[key], f"product {key} SVG SHA-256") for key in sorted(_legacy._VIEW_KEYS)}
    )
    scene = MultiPrecursorProductScene(
        protocol=_legacy.SCENE_PROTOCOL,
        recipe_id=_plain(value["recipe_id"], "product recipe_id"),
        recipe_schema=_MULTI_SCHEMA,
        target_material=_plain(value["target_material"], "product target_material"),
        product_family=_plain(value["product_family"], "product product_family"),
        commercial_context=_plain(value["commercial_context"], "product commercial_context"),
        film_role=_plain(value["film_role"], "product film_role"),
        modeled_scope=_plain(value["modeled_scope"], "product modeled_scope"),
        simulation_notice=_plain(value["simulation_notice"], "product simulation_notice"),
        physical_fabrication_mapping=False,
        stage=stage,
        regions=tuple(regions),
        precursor_sequence=tuple(sequence),
        overlay=_legacy._parse_overlay(value["simulation_overlay"]),
    )
    document = _legacy.ProductDocument(
        scene=scene,
        recipe_sha256=bytes.fromhex(_legacy._digest_hex(value["recipe_sha256"], "product recipe")),
        root_hash=bytes.fromhex(_legacy._digest_hex(value["packet_root_hash"], "product packet root")),
        view_sha256=views,
    )
    if canonical_product_json(document) != raw:
        raise core.RecipeError("multi-precursor product JSON is not canonical sorted compact JSON")
    return document


def parse_product_json(raw: bytes):
    if type(raw) is not bytes or not raw:
        raise core.RecipeError("product JSON must be non-empty exact bytes")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_legacy._reject_duplicate_pairs,
            parse_constant=_legacy._reject_nonfinite_constant,
        )
    except core.RecipeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise core.RecipeError("product JSON is not valid JSON") from error
    if type(value) is dict and value.get("recipe_schema") == _MULTI_SCHEMA:
        return _parse_multi(value, raw)
    return _legacy.parse_product_json(raw)


# Re-export overridden entry points after the legacy wildcard population.
globals().update(
    {
        "NamedPrecursorStage": NamedPrecursorStage,
        "MultiPrecursorProductScene": MultiPrecursorProductScene,
        "ProductSceneLike": ProductSceneLike,
        "is_surrogate_scene": is_surrogate_scene,
        "build_product_scene": build_product_scene,
        "build_product_document": build_product_document,
        "canonical_product_json": canonical_product_json,
        "parse_product_json": parse_product_json,
    }
)
