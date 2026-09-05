"""Deterministic SVG views for public-reference product scenes."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from xml.sax.saxutils import escape

import ald_hardened_core as core
from ald_product_scene import ProductLayer, ProductScene


_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_BANNER = "PUBLIC-REFERENCE SCHEMATIC — NOT A FABRICATION RECIPE"


def _text(x: int, y: int, value: str, *, size: int = 26, weight: str = "normal") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" '
        f'font-weight="{weight}">{escape(value)}</text>'
    )


def _svg(lines: list[str]) -> bytes:
    return ("\n".join([_HEADER, *lines]) + "\n").encode("utf-8")


def _top_elements(scene: ProductScene, *, x_offset: int = 0, scale: float = 1.0) -> list[str]:
    if type(scene) is not ProductScene:
        raise core.RecipeError("top SVG requires a ProductScene")

    def sx(value: int) -> int:
        return x_offset + int(round(value * scale))

    def sw(value: int) -> int:
        return int(round(value * scale))

    lines = [
        _text(sx(80), sw(90), scene.tetron.shape, size=max(sw(30), 12), weight="bold"),
        f'<rect x="{sx(180)}" y="{sw(260)}" width="{sw(720)}" height="{sw(42)}" rx="{sw(18)}" fill="none" stroke="black" stroke-width="{max(sw(4), 1)}"/>',
        f'<rect x="{sx(180)}" y="{sw(540)}" width="{sw(720)}" height="{sw(42)}" rx="{sw(18)}" fill="none" stroke="black" stroke-width="{max(sw(4), 1)}"/>',
        f'<rect x="{sx(520)}" y="{sw(260)}" width="{sw(40)}" height="{sw(322)}" fill="none" stroke="black" stroke-width="{max(sw(4), 1)}"/>',
    ]
    gate_y = (335, 405, 475)
    for layer, y in zip(scene.gate_layers, gate_y, strict=False):
        lines.append(
            f'<rect x="{sx(260)}" y="{sw(y)}" width="{sw(560)}" height="{sw(28)}" '
            f'fill="none" stroke="black" stroke-width="{max(sw(2), 1)}" stroke-dasharray="{sw(10)},{sw(8)}"/>'
        )
        lines.append(_text(sx(840), sw(y + 22), f"G{layer.index}: {layer.function}", size=max(sw(17), 10)))

    dot_positions = ((270, 235), (430, 235), (650, 235), (810, 235), (540, 635))
    for dot, (x, y) in zip(scene.quantum_dots, dot_positions, strict=False):
        lines.extend(
            [
                f'<circle cx="{sx(x)}" cy="{sw(y)}" r="{sw(24)}" fill="white" stroke="black" stroke-width="{max(sw(3), 1)}"/>',
                _text(sx(x - 20), sw(y + 8), dot.label, size=max(sw(16), 9), weight="bold"),
            ]
        )
    lines.extend(
        [
            _text(
                sx(180),
                sw(700),
                f"nanowire length: {scene.tetron.horizontal_nanowire_length_um:g} µm",
                size=max(sw(20), 10),
            ),
            _text(
                sx(180),
                sw(732),
                f"nanowire width: {scene.tetron.horizontal_nanowire_width_nm:g} nm",
                size=max(sw(20), 10),
            ),
            _text(
                sx(180),
                sw(764),
                f"backbone: {scene.tetron.backbone_length_um:g} µm × {scene.tetron.backbone_width_nm:g} nm",
                size=max(sw(20), 10),
            ),
        ]
    )
    return lines


def _layer_label(layer: ProductLayer) -> str:
    material = layer.material if layer.material is not None else "UNSPECIFIED"
    thickness = f"{layer.thickness_nm:g} nm" if layer.thickness_nm is not None else "UNSPECIFIED"
    return f"{layer.role}: {material} — thickness {thickness}"


def _stack_elements(scene: ProductScene, *, x_offset: int = 0, scale: float = 1.0) -> list[str]:
    if type(scene) is not ProductScene:
        raise core.RecipeError("stack SVG requires a ProductScene")

    def sx(value: int) -> int:
        return x_offset + int(round(value * scale))

    def sw(value: int) -> int:
        return int(round(value * scale))

    known_heights = {
        "quantum_well_inas": 72,
        "quantum_well_inassb": 36,
        "superconductor": 100,
    }
    lines = [_text(sx(80), sw(90), "Material-layer stack", size=max(sw(30), 12), weight="bold")]
    y = 150
    for layer in scene.layers:
        height = known_heights.get(layer.role, 56)
        lines.append(
            f'<rect x="{sx(120)}" y="{sw(y)}" width="{sw(640)}" height="{sw(height)}" '
            f'fill="none" stroke="black" stroke-width="{max(sw(3), 1)}"/>'
        )
        lines.append(
            _text(
                sx(140),
                sw(y + max(height // 2 + 8, 22)),
                _layer_label(layer),
                size=max(sw(18), 9),
            )
        )
        y += height + 12
    return lines


def render_top_svg(scene: ProductScene) -> bytes:
    return _svg(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
            _text(70, 45, _BANNER, size=22, weight="bold"),
            *_top_elements(scene),
            "</svg>",
        ]
    )


def render_stack_svg(scene: ProductScene) -> bytes:
    return _svg(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
            _text(70, 45, _BANNER, size=22, weight="bold"),
            *_stack_elements(scene),
            "</svg>",
        ]
    )


def render_final_svg(scene: ProductScene) -> bytes:
    return _svg(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
            _text(55, 42, _BANNER, size=20, weight="bold"),
            _text(55, 72, "physical_fabrication_mapping=false", size=17, weight="bold"),
            *_top_elements(scene, x_offset=0, scale=0.78),
            *_stack_elements(scene, x_offset=800, scale=0.78),
            "</svg>",
        ]
    )


def write_product_svgs(scene: ProductScene, root: Path):
    if type(scene) is not ProductScene:
        raise core.RecipeError("product SVG writer requires a ProductScene")
    destination = Path(root)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        paths = {
            "top": destination / "product-top.svg",
            "stack": destination / "product-stack.svg",
            "final": destination / "product-final.svg",
        }
        paths["top"].write_bytes(render_top_svg(scene))
        paths["stack"].write_bytes(render_stack_svg(scene))
        paths["final"].write_bytes(render_final_svg(scene))
    except OSError as error:
        raise core.OutputError(f"unable to write product SVG views: {error}") from error
    return MappingProxyType(paths)
