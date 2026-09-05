"""SVG facade for legacy and multi-precursor product scenes."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from xml.sax.saxutils import escape

import ald_hardened_core as core
import ald_product_scene as product_scene
import _ald_product_svg_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_BANNER = "SIMULATION-ONLY PRODUCT SCHEMATIC — NOT A FABRICATION RECIPE"


def _text(x: int, y: int, value: str, *, size: int = 24, weight: str = "normal") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" '
        f'font-weight="{weight}">{escape(value)}</text>'
    )


def _svg(lines: list[str]) -> bytes:
    return ("\n".join([_HEADER, *lines]) + "\n").encode("utf-8")


def _multi_top(scene: product_scene.MultiPrecursorProductScene) -> bytes:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
        _text(55, 45, _BANNER, size=22, weight="bold"),
        _text(70, 100, scene.target_material, size=32, weight="bold"),
        _text(70, 140, f"Product family: {scene.product_family}", size=20),
        _text(70, 185, "Conceptual simulation regions", size=25, weight="bold"),
    ]
    for offset, region in enumerate(scene.regions):
        y = 220 + offset * 78
        lines.extend(
            [
                f'<rect x="90" y="{y}" width="1050" height="62" rx="10" fill="none" stroke="black" stroke-width="3"/>',
                _text(112, y + 27, f"R{region.index}: {region.label}", size=18, weight="bold"),
                _text(112, y + 51, f"dimensionless transport factor {region.transport_factor:g}", size=15),
            ]
        )
    lines.extend([
        _text(90, 840, "All geometry and transport values are abstract simulator metadata.", size=18),
        "</svg>",
    ])
    return _svg(lines)


def _multi_stack(scene: product_scene.MultiPrecursorProductScene) -> bytes:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
        _text(55, 45, _BANNER, size=22, weight="bold"),
        _text(70, 100, f"{scene.target_material} — named precursor simulation sequence", size=30, weight="bold"),
        _text(70, 140, "Chemical identities are real; executable process values are intentionally omitted from this view.", size=18),
    ]
    for index, item in enumerate(scene.precursor_sequence):
        column = index % 2
        row = index // 2
        x = 90 + column * 740
        y = 190 + row * 105
        lines.extend([
            f'<rect x="{x}" y="{y}" width="670" height="78" rx="12" fill="none" stroke="black" stroke-width="3"/>',
            _text(x + 20, y + 30, f"Step {index + 1}: {item.id} — {item.name}", size=18, weight="bold"),
            _text(x + 20, y + 58, f"Formula: {item.formula}", size=17),
        ])
    lines.extend([
        _text(90, 850, "Sequence order is authoritative display metadata; dose, purge, temperature, pressure, flow, and kinetics are not shown.", size=17),
        "</svg>",
    ])
    return _svg(lines)


def _multi_final(scene: product_scene.MultiPrecursorProductScene) -> bytes:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
        _text(55, 42, _BANNER, size=20, weight="bold"),
        _text(55, 74, "physical_fabrication_mapping=false", size=18, weight="bold"),
        _text(70, 125, scene.target_material, size=31, weight="bold"),
        _text(70, 165, "Named precursor simulation sequence", size=22, weight="bold"),
    ]
    for index, item in enumerate(scene.precursor_sequence):
        y = 205 + index * 44
        lines.append(_text(90, y, f"{index + 1}. {item.id}: {item.name} [{item.formula}]", size=17))
    panel_x = 950
    lines.extend([
        f'<rect x="{panel_x}" y="190" width="560" height="500" rx="18" fill="none" stroke="black" stroke-width="3"/>',
        _text(panel_x + 24, 238, "Sequential simulation status", size=23, weight="bold"),
    ])
    if scene.overlay is None:
        lines.append(_text(panel_x + 24, 290, "No simulation overlay for this stage", size=18))
    else:
        overlay = scene.overlay
        for index, line in enumerate((
            f"seed: {overlay.seed}",
            f"coverage: {overlay.coverage:.6f}",
            f"thickness: {overlay.thickness_nm:.6f} nm (synthetic model output)",
            f"defect fraction: {overlay.defect_fraction:.6f}",
        )):
            lines.append(_text(panel_x + 24, 290 + index * 44, line, size=17))
    lines.extend([
        _text(70, 830, "No physical process window, equipment settings, or precursor handling instructions are encoded in this schematic.", size=17),
        "</svg>",
    ])
    return _svg(lines)


def render_top_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.MultiPrecursorProductScene:
        return _multi_top(scene)
    return _legacy.render_top_svg(scene)


def render_stack_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.MultiPrecursorProductScene:
        return _multi_stack(scene)
    return _legacy.render_stack_svg(scene)


def render_final_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.MultiPrecursorProductScene:
        return _multi_final(scene)
    return _legacy.render_final_svg(scene)


def write_product_svgs(scene: product_scene.ProductSceneLike, root: Path):
    if type(scene) is not product_scene.MultiPrecursorProductScene:
        return _legacy.write_product_svgs(scene, root)
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


globals().update({
    "render_top_svg": render_top_svg,
    "render_stack_svg": render_stack_svg,
    "render_final_svg": render_final_svg,
    "write_product_svgs": write_product_svgs,
})
