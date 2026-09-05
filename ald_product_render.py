"""Raster-track dispatcher for Majorana and generic surrogate product scenes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import ald_hardened_core as core
import ald_media_codecs as media
import ald_product_scene as product_scene
import ald_product_render_majorana as _majorana
from ald_product_render_majorana import *  # noqa: F401,F403


_majorana_render_product_frame = _majorana.render_product_frame
_STAGE_LABELS = {
    "reference-stack": "product context",
    "tetron": "concept geometry",
    "gates": "region map",
    "simulation-status": "deposition simulation",
    "quantum-dots": "measurement summary",
    "final": "final surrogate view",
}


def _font(size: int):
    return _majorana._font(size)


def _draw_surrogate_header(
    draw: ImageDraw.ImageDraw,
    scene: product_scene.SurrogateProductScene,
    item: core.HashedPacket,
) -> None:
    display_stage = _STAGE_LABELS.get(scene.stage, scene.stage)
    draw.text((64, 48), scene.product_family, fill="black", font=_font(42))
    draw.text(
        (64, 110),
        f"Stage: {display_stage}    Packet {item.packet.sequence:03d}    Status opcode: {item.packet.opcode}",
        fill="black",
        font=_font(25),
    )
    draw.text(
        (64, 1020),
        "SIMULATION-ONLY PRODUCT VIEW • physical_fabrication_mapping=false • pixels are display-only",
        fill="black",
        font=_font(20),
    )


def _draw_surrogate_context(
    draw: ImageDraw.ImageDraw,
    scene: product_scene.SurrogateProductScene,
) -> None:
    x0, y0, x1, y1 = 70, 185, 590, 850
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline="black", width=3)
    draw.text((x0 + 22, y0 + 22), "Product surrogate", fill="black", font=_font(28))
    draw.multiline_text(
        (x0 + 22, y0 + 78),
        (
            f"Film role:\n{scene.film_role}\n\n"
            f"Commercial context:\n{scene.commercial_context}\n\n"
            f"Modeled scope:\n{scene.modeled_scope}\n\n"
            "Generic A/B chemistry only\n"
            "No physical fabrication mapping"
        ),
        fill="black",
        font=_font(18),
        spacing=6,
    )


def _draw_surrogate_regions(
    draw: ImageDraw.ImageDraw,
    scene: product_scene.SurrogateProductScene,
) -> None:
    x0, y0, x1, y1 = 650, 185, 1435, 850
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline="black", width=3)
    draw.text((x0 + 22, y0 + 22), "Conceptual simulation regions", fill="black", font=_font(27))
    count = len(scene.regions)
    available = y1 - y0 - 105
    row_height = max(58, min(100, available // max(count, 1)))
    cursor = y0 + 78
    for region in scene.regions:
        bottom = min(cursor + row_height - 10, y1 - 18)
        draw.rounded_rectangle((x0 + 25, cursor, x1 - 25, bottom), radius=12, outline="black", width=2)
        draw.text(
            (x0 + 45, cursor + 12),
            f"R{region.index}: {region.label}",
            fill="black",
            font=_font(18),
        )
        draw.text(
            (x0 + 45, cursor + 38),
            f"simulation transport factor {region.transport_factor:g}",
            fill="black",
            font=_font(15),
        )
        cursor += row_height
        if cursor >= y1 - 30:
            break


def _draw_surrogate_status(
    draw: ImageDraw.ImageDraw,
    scene: product_scene.SurrogateProductScene,
) -> None:
    x0, y0, x1, y1 = 1495, 185, 1855, 850
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline="black", width=3)
    draw.text((x0 + 18, y0 + 22), "Simulation status", fill="black", font=_font(25))
    draw.multiline_text(
        (x0 + 18, y0 + 70),
        (
            "Descriptive product metadata\n"
            "No physical dimensions\n"
            "No real precursor chemistry\n"
            "No equipment settings\n\n"
            f"Regions: {len(scene.regions)}\n"
            f"Stage: {_STAGE_LABELS.get(scene.stage, scene.stage)}"
        ),
        fill="black",
        font=_font(17),
        spacing=5,
    )
    if scene.overlay is not None:
        overlay = scene.overlay
        draw.multiline_text(
            (x0 + 18, y0 + 350),
            (
                "GENERIC A/B SURROGATE\n"
                f"seed: {overlay.seed}\n"
                f"coverage: {overlay.coverage:.6f}\n"
                f"thickness: {overlay.thickness_nm:.6f} nm\n"
                f"defect: {overlay.defect_fraction:.6f}"
            ),
            fill="black",
            font=_font(16),
            spacing=5,
        )


def _render_surrogate_frame(
    scene: product_scene.SurrogateProductScene,
    item: core.HashedPacket,
    profile: media.MediaProfile,
    destination: Path,
) -> Path:
    if type(profile) is not media.MediaProfile:
        raise ProductRenderError("product frame profile must be an exact MediaProfile")
    media.validate_hashed_packet(item)
    if profile.width != 1920 or profile.height != 1080:
        raise ProductRenderError("product frame profile must be 1920x1080")
    if scene.physical_fabrication_mapping is not False:
        raise ProductRenderError("product frame requires physical_fabrication_mapping=false")

    image = Image.new("RGB", (profile.width, profile.height), "white")
    draw = ImageDraw.Draw(image)
    _draw_surrogate_header(draw, scene, item)
    _draw_surrogate_context(draw, scene)
    _draw_surrogate_regions(draw, scene)
    _draw_surrogate_status(draw, scene)

    destination = Path(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=False, compress_level=9)
    except OSError as error:
        raise ProductRenderError(f"unable to write product frame: {error}") from error
    return destination


def render_product_frame(
    scene: product_scene.ProductSceneLike,
    item: core.HashedPacket,
    profile: media.MediaProfile,
    destination: Path,
) -> Path:
    if type(scene) is product_scene.ProductScene:
        return _majorana_render_product_frame(scene, item, profile, destination)
    if type(scene) is product_scene.SurrogateProductScene:
        return _render_surrogate_frame(scene, item, profile, destination)
    raise ProductRenderError("product frame requires a supported product scene")


# Preserve the original staging/audio/data implementation. Its global scene
# module resolves the public dispatcher, and this renderer hook lets each
# packet choose the appropriate raster variant without changing trust data.
_majorana.render_product_frame = render_product_frame
stage_product_tracks = _majorana.stage_product_tracks
