"""SVG dispatcher for Majorana public-reference and generic surrogate-product scenes."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from xml.sax.saxutils import escape

import ald_hardened_core as core
import ald_product_scene as product_scene
import ald_product_svg_majorana as _majorana
from ald_product_svg_majorana import *  # noqa: F401,F403


_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_BANNER = "SIMULATION-ONLY PRODUCT SCHEMATIC — NOT A FABRICATION RECIPE"


def _text(x: int, y: int, value: str, *, size: int = 26, weight: str = "normal") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" '
        f'font-weight="{weight}">{escape(value)}</text>'
    )


def _svg(lines: list[str]) -> bytes:
    return ("\n".join([_HEADER, *lines]) + "\n").encode("utf-8")


def _surrogate_regions(
    scene: product_scene.SurrogateProductScene,
    *,
    x: int,
    y: int,
    width: int,
    row_height: int,
) -> list[str]:
    lines: list[str] = []
    for offset, region in enumerate(scene.regions):
        row_y = y + offset * row_height
        lines.append(
            f'<rect x="{x}" y="{row_y}" width="{width}" height="{row_height - 12}" '
            'rx="12" fill="none" stroke="black" stroke-width="3"/>'
        )
        lines.append(
            _text(x + 22, row_y + 34, f"Region {region.index}: {region.label}", size=20, weight="bold")
        )
        lines.append(
            _text(
                x + 22,
                row_y + 62,
                f"simulation transport factor: {region.transport_factor:g}",
                size=17,
            )
        )
    return lines


def _render_surrogate_top(scene: product_scene.SurrogateProductScene) -> bytes:
    return _svg(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
            _text(60, 45, _BANNER, size=22, weight="bold"),
            _text(80, 105, scene.product_family, size=34, weight="bold"),
            _text(80, 150, f"Film role: {scene.film_role}", size=22),
            _text(80, 195, "Conceptual region map", size=28, weight="bold"),
            *_surrogate_regions(scene, x=100, y=225, width=1120, row_height=88),
            _text(100, 835, "Region layout is descriptive simulation metadata; no physical dimensions are encoded.", size=19),
            "</svg>",
        ]
    )


def _render_surrogate_stack(scene: product_scene.SurrogateProductScene) -> bytes:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
        _text(60, 45, _BANNER, size=22, weight="bold"),
        _text(80, 105, f"{scene.product_family} — abstract conformality profile", size=31, weight="bold"),
        _text(80, 150, f"Modeled scope: {scene.modeled_scope}", size=19),
        _text(80, 182, f"Context: {scene.commercial_context}", size=18),
    ]
    base_y = 255
    for offset, region in enumerate(scene.regions):
        y = base_y + offset * 78
        bar_width = max(40, min(900, int(round(700 * region.transport_factor))))
        lines.extend(
            [
                _text(90, y + 26, f"R{region.index}", size=18, weight="bold"),
                f'<rect x="150" y="{y}" width="{bar_width}" height="38" fill="none" stroke="black" stroke-width="3"/>',
                _text(170 + bar_width, y + 27, region.label, size=17),
            ]
        )
    lines.extend(
        [
            _text(90, 840, "Bars visualize simulator transport factors only, not process geometry.", size=19),
            "</svg>",
        ]
    )
    return _svg(lines)


def _render_surrogate_final(scene: product_scene.SurrogateProductScene) -> bytes:
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">',
        _text(55, 42, _BANNER, size=20, weight="bold"),
        _text(55, 74, "physical_fabrication_mapping=false", size=18, weight="bold"),
        _text(70, 125, scene.product_family, size=31, weight="bold"),
        _text(70, 165, f"Generic A/B surrogate film role: {scene.film_role}", size=19),
        _text(70, 210, "Conceptual regions", size=24, weight="bold"),
        *_surrogate_regions(scene, x=80, y=235, width=820, row_height=78),
    ]
    panel_x = 970
    lines.extend(
        [
            f'<rect x="{panel_x}" y="215" width="540" height="500" rx="18" fill="none" stroke="black" stroke-width="3"/>',
            _text(panel_x + 24, 260, "Surrogate simulation status", size=24, weight="bold"),
        ]
    )
    if scene.overlay is None:
        lines.append(_text(panel_x + 24, 310, "No simulation overlay for this display stage", size=18))
    else:
        overlay = scene.overlay
        status = (
            f"seed: {overlay.seed}",
            f"coverage: {overlay.coverage:.6f}",
            f"thickness: {overlay.thickness_nm:.6f} nm (simulator output)",
            f"defect fraction: {overlay.defect_fraction:.6f}",
            "generic A/B surrogate simulation",
        )
        for index, line in enumerate(status):
            lines.append(_text(panel_x + 24, 310 + index * 42, line, size=18))
    lines.extend(
        [
            _text(70, 830, "No real material, physical dimensions, precursor chemistry, or equipment settings are inferred.", size=18),
            "</svg>",
        ]
    )
    return _svg(lines)


def render_top_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.ProductScene:
        return _majorana.render_top_svg(scene)
    if type(scene) is product_scene.SurrogateProductScene:
        return _render_surrogate_top(scene)
    raise core.RecipeError("top SVG requires a supported product scene")


def render_stack_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.ProductScene:
        return _majorana.render_stack_svg(scene)
    if type(scene) is product_scene.SurrogateProductScene:
        return _render_surrogate_stack(scene)
    raise core.RecipeError("stack SVG requires a supported product scene")


def render_final_svg(scene: product_scene.ProductSceneLike) -> bytes:
    if type(scene) is product_scene.ProductScene:
        return _majorana.render_final_svg(scene)
    if type(scene) is product_scene.SurrogateProductScene:
        return _render_surrogate_final(scene)
    raise core.RecipeError("final SVG requires a supported product scene")


def write_product_svgs(scene: product_scene.ProductSceneLike, root: Path):
    if type(scene) not in (product_scene.ProductScene, product_scene.SurrogateProductScene):
        raise core.RecipeError("product SVG writer requires a supported product scene")
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
