"""Deterministic raster/BFSK/data-track staging for product-MP4 mode.

The product raster is display-only. It renders public reference geometry and
surrogate simulation status, never QR symbols, canonical packet bytes, or
fabrication instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import ald_hardened_core as core
import ald_media_codecs as media
import ald_product_data as product_data
import ald_product_scene as product_scene


_STAGE_BY_OPCODE = {
    "CONFIGURE": "reference-stack",
    "SET_TEMPERATURE": "reference-stack",
    "EVACUATE": "tetron",
    "STABILIZE": "gates",
    "ALD_CYCLE": "simulation-status",
    "MEASURE": "quantum-dots",
    "SHUTDOWN": "final",
}
_SIMULATION_STAGES = frozenset({"simulation-status", "final"})


class ProductRenderError(core.ALDError):
    """Raised when deterministic product-track staging cannot be completed."""

    exit_code = core.ExitCode.MEDIA


@dataclass(frozen=True)
class ProductTrackSources:
    frame_paths: tuple[Path, ...]
    audio_path: Path
    data_path: Path
    duration_seconds: float


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - compatibility with older Pillow
        return ImageFont.load_default()


def _draw_header(draw: ImageDraw.ImageDraw, scene: product_scene.ProductScene, item: core.HashedPacket) -> None:
    title_font = _font(42)
    body_font = _font(25)
    draw.text((64, 48), "Majorana 2 public-reference product view", fill="black", font=title_font)
    draw.text(
        (64, 110),
        f"Stage: {scene.stage}    Packet {item.packet.sequence:03d}    Status opcode: {item.packet.opcode}",
        fill="black",
        font=body_font,
    )
    draw.text(
        (64, 1020),
        "PUBLIC-REFERENCE VISUALIZATION • physical_fabrication_mapping=false • simulation only",
        fill="black",
        font=_font(20),
    )


def _draw_stack_context(draw: ImageDraw.ImageDraw, scene: product_scene.ProductScene) -> None:
    x0, y0, width, height = 80, 190, 350, 650
    draw.rounded_rectangle((x0, y0, x0 + width, y0 + height), radius=18, outline="black", width=3)
    draw.text((x0 + 20, y0 + 20), "Public material stack", fill="black", font=_font(28))
    cursor = y0 + 72
    for layer in scene.layers:
        material = layer.material if layer.material is not None else "UNSPECIFIED"
        thickness = (
            f"{layer.thickness_nm:g} nm" if layer.thickness_nm is not None else "UNSPECIFIED"
        )
        label = f"{layer.role}\n{material} • {thickness}"
        draw.multiline_text((x0 + 20, cursor), label, fill="black", font=_font(18), spacing=3)
        cursor += 76
        if cursor > y0 + height - 55:
            break


def _draw_tetron(draw: ImageDraw.ImageDraw, scene: product_scene.ProductScene) -> None:
    # Schematic geometry only: proportions communicate the public H-shaped
    # tetron topology without mapping dimensions to fabrication coordinates.
    left, right = 560, 1450
    upper_y, lower_y = 410, 660
    wire_half_height = 28
    backbone_x = 1005
    backbone_half_width = 26

    draw.rounded_rectangle(
        (left, upper_y - wire_half_height, right, upper_y + wire_half_height),
        radius=24,
        outline="black",
        width=5,
    )
    draw.rounded_rectangle(
        (left, lower_y - wire_half_height, right, lower_y + wire_half_height),
        radius=24,
        outline="black",
        width=5,
    )
    draw.rectangle(
        (
            backbone_x - backbone_half_width,
            upper_y - wire_half_height,
            backbone_x + backbone_half_width,
            lower_y + wire_half_height,
        ),
        outline="black",
        width=5,
    )
    draw.text(
        (690, 300),
        f"{scene.tetron.shape} • 2 horizontal nanowires • Pb reference island",
        fill="black",
        font=_font(26),
    )


def _draw_gates(draw: ImageDraw.ImageDraw, scene: product_scene.ProductScene) -> None:
    gate_x = (740, 990, 1240)
    for index, gate in enumerate(scene.gate_layers):
        x = gate_x[index] if index < len(gate_x) else 740 + index * 250
        draw.rounded_rectangle((x, 345, x + 72, 725), radius=18, outline="black", width=3)
        draw.text((x - 4, 742), f"G{gate.index}", fill="black", font=_font(20))
    draw.text((720, 790), "3 schematic functional gate bands", fill="black", font=_font(20))


def _draw_quantum_dots(draw: ImageDraw.ImageDraw, scene: product_scene.ProductScene) -> None:
    positions = ((620, 410), (850, 410), (1160, 410), (1390, 410), (1005, 660))
    for dot, (x, y) in zip(scene.quantum_dots, positions, strict=False):
        radius = 22
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="black", width=4)
        draw.text((x - 18, y + 30), dot.label, fill="black", font=_font(18))


def _draw_status_panel(
    draw: ImageDraw.ImageDraw,
    scene: product_scene.ProductScene,
) -> None:
    x0, y0, x1, y1 = 1515, 190, 1850, 840
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline="black", width=3)
    draw.text((x0 + 18, y0 + 20), "Reference status", fill="black", font=_font(25))
    draw.multiline_text(
        (x0 + 18, y0 + 65),
        "H tetron\n3 gate layers\n5 quantum dots\n\nKnown stack:\nGaSb\nInAs 6 nm\nInAs0.8Sb0.2 2 nm\nPb 10 nm\n\nUnknown barriers:\nUNSPECIFIED",
        fill="black",
        font=_font(18),
        spacing=5,
    )
    if scene.overlay is not None:
        overlay = scene.overlay
        draw.multiline_text(
            (x0 + 18, y0 + 455),
            (
                "SURROGATE SIMULATION\n"
                f"seed: {overlay.seed}\n"
                f"coverage: {overlay.coverage:.6f}\n"
                f"thickness: {overlay.thickness_nm:.6f} nm\n"
                f"defect: {overlay.defect_fraction:.6f}\n"
                "generic A/B surrogate simulation status"
            ),
            fill="black",
            font=_font(16),
            spacing=4,
        )


def render_product_frame(
    scene: product_scene.ProductScene,
    item: core.HashedPacket,
    profile: media.MediaProfile,
    destination: Path,
) -> Path:
    """Render one deterministic display-only RGB product frame."""
    if type(scene) is not product_scene.ProductScene:
        raise ProductRenderError("product frame requires an exact ProductScene")
    if type(profile) is not media.MediaProfile:
        raise ProductRenderError("product frame profile must be an exact MediaProfile")
    media.validate_hashed_packet(item)
    if profile.width != 1920 or profile.height != 1080:
        raise ProductRenderError("product frame profile must be 1920x1080")
    if scene.physical_fabrication_mapping is not False:
        raise ProductRenderError("product frame requires physical_fabrication_mapping=false")

    image = Image.new("RGB", (profile.width, profile.height), "white")
    draw = ImageDraw.Draw(image)
    _draw_header(draw, scene, item)
    _draw_stack_context(draw, scene)
    _draw_tetron(draw, scene)
    _draw_gates(draw, scene)
    _draw_quantum_dots(draw, scene)
    _draw_status_panel(draw, scene)

    destination = Path(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=False, compress_level=9)
    except OSError as error:
        raise ProductRenderError(f"unable to write product frame: {error}") from error
    return destination


def _write_full_checksum_wav(
    compiled: core.CompiledRecipe,
    profile: media.MediaProfile,
    destination: Path,
) -> Path:
    intervals: list[np.ndarray] = []
    for item in compiled.packets:
        media.validate_hashed_packet(item)
        intervals.append(media.encode_checksum_audio(item.packet.sequence, item.digest, profile))
    if not intervals:
        raise ProductRenderError("product audio requires at least one packet")
    samples = np.concatenate(intervals)
    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    try:
        with wave.open(str(destination), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(profile.sample_rate)
            target.setcomptype("NONE", "not compressed")
            target.writeframes(pcm.tobytes(order="C"))
    except (OSError, wave.Error) as error:
        raise ProductRenderError(f"unable to write product checksum WAV: {error}") from error
    return destination


def stage_product_tracks(
    compiled: core.CompiledRecipe,
    simulation: core.SimulationResult,
    root: Path,
    profile: media.MediaProfile,
) -> ProductTrackSources:
    """Stage deterministic PNG, BFSK WAV, and guarded binary data sources."""
    if type(compiled) is not core.CompiledRecipe or type(compiled.packets) is not tuple:
        raise ProductRenderError("product staging requires an exact CompiledRecipe")
    if type(simulation) is not core.SimulationResult:
        raise ProductRenderError("product staging requires an exact SimulationResult")
    if type(profile) is not media.MediaProfile:
        raise ProductRenderError("product staging requires an exact MediaProfile")
    if simulation.fault is not None:
        raise ProductRenderError("faulted simulation cannot be staged as product media")
    if simulation.recipe_id != compiled.recipe.recipe_id:
        raise ProductRenderError("simulation recipe id does not match compiled recipe")
    if simulation.root_hash != compiled.root_hash:
        raise ProductRenderError("simulation root hash does not match compiled recipe")
    if profile.width != 1920 or profile.height != 1080:
        raise ProductRenderError("product media profile must be 1920x1080")
    if profile.sample_rate != 48_000 or profile.interval_seconds != 3.0:
        raise ProductRenderError("product media profile must use 48 kHz and 3.0-second intervals")
    if not compiled.packets:
        raise ProductRenderError("product staging requires at least one packet")

    target = Path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        try:
            target.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError as error:
            raise core.OutputError(f"product-track staging directory already exists: {target}") from error
        except OSError as error:
            raise core.OutputError(f"unable to create product-track staging directory: {error}") from error
        created = True

        frame_paths: list[Path] = []
        for expected_sequence, item in enumerate(compiled.packets):
            media.validate_hashed_packet(item)
            if item.packet.sequence != expected_sequence:
                raise ProductRenderError("compiled packet sequence is not contiguous and zero-based")
            try:
                stage = _STAGE_BY_OPCODE[item.packet.opcode]
            except KeyError as error:
                raise ProductRenderError(f"unsupported product-stage opcode: {item.packet.opcode}") from error
            scene = product_scene.build_product_scene(
                compiled.recipe,
                stage=stage,
                simulation=simulation if stage in _SIMULATION_STAGES else None,
            )
            frame_path = target / f"frame-{expected_sequence:06d}.png"
            render_product_frame(scene, item, profile, frame_path)
            frame_paths.append(frame_path)

        audio_path = _write_full_checksum_wav(compiled, profile, target / "product-audio.wav")
        interval_ms = int(round(profile.interval_seconds * 1000.0))
        data_path = product_data.write_product_slot_stream(
            compiled,
            target / "product-data.bin",
            interval_ms=interval_ms,
            include_guard=True,
        )
        return ProductTrackSources(
            frame_paths=tuple(frame_paths),
            audio_path=audio_path,
            data_path=data_path,
            duration_seconds=len(compiled.packets) * profile.interval_seconds,
        )
    except BaseException as error:
        if created:
            try:
                shutil.rmtree(target)
            except OSError as cleanup_error:
                try:
                    error.add_note(f"unable to remove failed product-track staging directory: {cleanup_error}")
                except AttributeError:
                    pass
        raise
