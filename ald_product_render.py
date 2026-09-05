"""Raster facade adding multi-precursor product scenes without changing legacy frames."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import ald_hardened_core as core
import ald_media_codecs as media
import ald_product_scene as product_scene
import _ald_product_render_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

# The original staging implementation owns timing/BFSK/data-track behavior.
# Teach only its display-stage mapping about the new first-class opcode.
_legacy._majorana._STAGE_BY_OPCODE["DEPOSITION_CYCLE"] = "simulation-status"


def _font(size: int):
    return _legacy._majorana._font(size)


def _render_multi_frame(
    scene: product_scene.MultiPrecursorProductScene,
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
    draw.text((64, 48), scene.target_material, fill="black", font=_font(40))
    draw.text(
        (64, 108),
        f"Stage: {scene.stage}    Packet {item.packet.sequence:03d}    Opcode: {item.packet.opcode}",
        fill="black",
        font=_font(24),
    )
    draw.text(
        (64, 1020),
        "MULTI-PRECURSOR SIMULATION • physical_fabrication_mapping=false • pixels are display-only",
        fill="black",
        font=_font(20),
    )

    # Left: chemistry identities only. Never render dose, purge, pressure,
    # temperature, flow, or kinetic values from the executable packet.
    draw.rounded_rectangle((70, 180, 1040, 850), radius=18, outline="black", width=3)
    draw.text((95, 210), "Named precursor simulation sequence", fill="black", font=_font(27))
    cursor_y = 265
    for index, precursor in enumerate(scene.precursor_sequence):
        draw.text(
            (110, cursor_y),
            f"{index + 1}. {precursor.id}: {precursor.name} [{precursor.formula}]",
            fill="black",
            font=_font(18),
        )
        cursor_y += 43
        if cursor_y > 810:
            break

    # Right: abstract region/status context.
    draw.rounded_rectangle((1090, 180, 1845, 850), radius=18, outline="black", width=3)
    draw.text((1115, 210), "Sequential surface simulation", fill="black", font=_font(26))
    draw.text((1115, 255), f"Product family: {scene.product_family}", fill="black", font=_font(17))
    draw.text((1115, 290), f"Regions: {len(scene.regions)}", fill="black", font=_font(17))
    y = 335
    for region in scene.regions[:6]:
        draw.text(
            (1125, y),
            f"R{region.index}: {region.label}  factor={region.transport_factor:g}",
            fill="black",
            font=_font(16),
        )
        y += 36
    if scene.overlay is not None:
        overlay = scene.overlay
        draw.multiline_text(
            (1125, 610),
            (
                f"seed: {overlay.seed}\n"
                f"coverage: {overlay.coverage:.6f}\n"
                f"thickness: {overlay.thickness_nm:.6f} nm\n"
                f"defect fraction: {overlay.defect_fraction:.6f}"
            ),
            fill="black",
            font=_font(17),
            spacing=5,
        )

    destination = Path(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=False, compress_level=9)
    except OSError as error:
        raise ProductRenderError(f"unable to write product frame: {error}") from error
    return destination


def render_product_frame(scene, item, profile, destination):
    if type(scene) is product_scene.MultiPrecursorProductScene:
        return _render_multi_frame(scene, item, profile, destination)
    return _legacy.render_product_frame(scene, item, profile, destination)


# Route the original staging loop through this renderer while preserving its
# BFSK/data-track implementation byte-for-byte.
_legacy._majorana.render_product_frame = render_product_frame
stage_product_tracks = _legacy._majorana.stage_product_tracks

globals().update({
    "render_product_frame": render_product_frame,
    "stage_product_tracks": stage_product_tracks,
})
