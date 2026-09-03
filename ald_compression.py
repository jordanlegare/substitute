"""Bounded procedural-compression metrics for deterministic ALD simulations.

The measurements in this module are analytical size comparisons. They never
materialize an unrolled cycle stream or per-site event stream, and they do not
claim that HLS/fMP4 transport media is itself a compression format.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

import ald_hardened_core as core


@dataclass(frozen=True)
class CompressionReport:
    """Size comparison between compact packets and hypothetical expansions."""

    canonical_instruction_bytes: int
    expanded_instruction_jsonl_bytes: int
    estimated_site_event_jsonl_bytes: int
    expanded_instruction_ratio: float
    estimated_site_event_ratio: float
    expanded_cycle_count: int
    estimated_site_event_count: int


def _jsonl_bytes(value: object) -> int:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(encoded) + 1


def _expanded_packet_line_bytes(packet: core.HashedPacket) -> tuple[int, int]:
    """Return analytical JSONL bytes and expanded cycle count for one packet."""
    if packet.packet.opcode != "ALD_CYCLE":
        return len(packet.canonical_bytes) + 1, 0

    repeat = packet.packet.arguments.get("repeat")
    if type(repeat) is not int or repeat <= 0:
        raise core.RecipeError("ALD_CYCLE repeat must be a positive integer")
    arguments = dict(packet.packet.arguments)
    arguments["repeat"] = 1
    single = core.Packet(
        protocol=packet.packet.protocol,
        recipe_id=packet.packet.recipe_id,
        sequence=packet.packet.sequence,
        opcode=packet.packet.opcode,
        arguments=arguments,
    )
    single_line_bytes = len(core.canonical_packet_bytes(single)) + 1
    return single_line_bytes * repeat, repeat


def _estimated_site_event_line_bytes(simulation: core.SimulationResult) -> int:
    """Estimate one worst-width compact JSONL site-event record for this run."""
    max_cycle = max(1, len(simulation.cycles))
    max_site = max(0, simulation.surface.total_sites - 1)
    representative = {
        "cycle": max_cycle,
        "event": "reaction",
        "half_reaction": "B",
        # Region/site identifiers intentionally use the total-site width so
        # this remains a conservative bounded estimate without reconstructing
        # the surface configuration or enumerating any events.
        "region": max_site,
        "site": max_site,
    }
    return _jsonl_bytes(representative)


def measure_procedural_compression(
    compiled: core.CompiledRecipe,
    simulation: core.SimulationResult,
) -> CompressionReport:
    """Measure procedural compaction without expanding cycles or site events.

    ``expanded_instruction_jsonl_bytes`` models a naive instruction stream in
    which every ``ALD_CYCLE`` repetition is serialized separately with
    ``repeat=1``. Sequence values are retained because this is a byte-size
    model, not a second executable packet stream.

    ``estimated_site_event_jsonl_bytes`` models two potential half-reaction
    events per aggregate surface site per completed cycle. It is deliberately
    an arithmetic estimate and never allocates those records.
    """
    if type(compiled) is not core.CompiledRecipe:
        raise core.RecipeError("compiled must be an exact CompiledRecipe")
    if type(simulation) is not core.SimulationResult:
        raise core.SurfaceModelError("simulation must be an exact SimulationResult")
    if not compiled.packets:
        raise core.RecipeError("compiled recipe must contain at least one packet")

    canonical_instruction_bytes = sum(
        len(packet.canonical_bytes) + 1 for packet in compiled.packets
    )
    if canonical_instruction_bytes <= 0:
        raise core.RecipeError("compiled packet stream has no canonical bytes")

    expanded_instruction_jsonl_bytes = 0
    expanded_cycle_count = 0
    for packet in compiled.packets:
        expanded_bytes, cycles = _expanded_packet_line_bytes(packet)
        expanded_instruction_jsonl_bytes += expanded_bytes
        expanded_cycle_count += cycles

    completed_cycles = len(simulation.cycles)
    total_sites = simulation.surface.total_sites
    if total_sites < 0:
        raise core.SurfaceModelError("simulation surface total_sites is invalid")
    estimated_site_event_count = completed_cycles * 2 * total_sites
    estimated_site_event_jsonl_bytes = (
        estimated_site_event_count * _estimated_site_event_line_bytes(simulation)
    )

    return CompressionReport(
        canonical_instruction_bytes=canonical_instruction_bytes,
        expanded_instruction_jsonl_bytes=expanded_instruction_jsonl_bytes,
        estimated_site_event_jsonl_bytes=estimated_site_event_jsonl_bytes,
        expanded_instruction_ratio=(
            expanded_instruction_jsonl_bytes / canonical_instruction_bytes
        ),
        estimated_site_event_ratio=(
            estimated_site_event_jsonl_bytes / canonical_instruction_bytes
        ),
        expanded_cycle_count=expanded_cycle_count,
        estimated_site_event_count=estimated_site_event_count,
    )


def measure_hls_bundle_bytes(directory: Path) -> int:
    """Return the physical byte size of one flat, already-verified HLS bundle.

    This is an informational transport-size measurement, not a compression
    ratio. Symlinks and non-regular entries are rejected so the measurement
    never traverses or counts data outside the supplied bundle directory.
    """
    root = Path(directory)
    try:
        if root.is_symlink():
            raise core.OutputError("HLS bundle directory must not be a symlink")
        if not root.is_dir():
            raise core.OutputError("HLS bundle measurement requires a directory")

        total = 0
        file_count = 0
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise core.OutputError(
                        f"HLS bundle measurement rejects symlink: {entry.name}"
                    )
                if not entry.is_file(follow_symlinks=False):
                    raise core.OutputError(
                        f"HLS bundle measurement requires flat regular files: {entry.name}"
                    )
                metadata = entry.stat(follow_symlinks=False)
                total += metadata.st_size
                file_count += 1
    except core.OutputError:
        raise
    except OSError as error:
        raise core.OutputError(f"unable to measure HLS bundle bytes: {error}") from error

    if file_count == 0:
        raise core.OutputError("HLS bundle measurement found no regular files")
    return total
