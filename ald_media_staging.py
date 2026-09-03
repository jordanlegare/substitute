"""Filesystem staging for verified ALD packet media artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

import ald_core as core
import ald_media_codecs as media


@dataclass(frozen=True)
class PacketMediaArtifact:
    sequence: int
    frame_path: Path
    audio_path: Path
    digest: bytes


def stage_packet_media(
    compiled: core.CompiledRecipe,
    directory: Path,
    profile: media.MediaProfile,
) -> tuple[PacketMediaArtifact, ...]:
    """Write and immediately re-verify one PNG/WAV pair per compiled packet.

    The destination is a staging directory, not a publication target: it must
    not already exist. Any failure after creation removes the staging tree and
    no partial artifact tuple is returned.
    """
    if type(compiled) is not core.CompiledRecipe:
        raise media.FrameDecodeError("media staging requires an exact CompiledRecipe")
    if type(compiled.packets) is not tuple:
        raise media.FrameDecodeError("compiled packet stream must be an exact tuple")
    if type(profile) is not media.MediaProfile:
        raise media.FrameDecodeError("profile must be an exact MediaProfile")

    target = Path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        try:
            target.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError as error:
            raise core.OutputError(f"packet-media staging directory already exists: {target}") from error
        except OSError as error:
            raise core.OutputError(f"unable to create packet-media staging directory: {error}") from error
        created = True

        artifacts: list[PacketMediaArtifact] = []
        for item in compiled.packets:
            if type(item) is not core.HashedPacket:
                raise media.FrameDecodeError("compiled packet stream contains a non-HashedPacket item")
            sequence = item.packet.sequence
            stem = f"packet-{sequence:06d}"
            frame_path = target / f"{stem}.png"
            audio_path = target / f"{stem}.wav"

            media.render_instruction_frame(item, profile, frame_path)
            media.write_checksum_wav(sequence, item.digest, profile, audio_path)

            frame = media.decode_instruction_frame(frame_path, profile)
            if (
                frame.sequence != sequence
                or frame.digest != item.digest
                or frame.canonical_bytes != item.canonical_bytes
            ):
                raise media.FrameDecodeError(
                    f"staged frame verification failed for packet {sequence}"
                )

            audio = media.decode_checksum_audio(media.read_checksum_wav(audio_path, profile), profile)
            if audio.sequence != sequence or audio.digest != item.digest:
                raise media.AudioDecodeError(
                    f"staged audio verification failed for packet {sequence}"
                )

            artifacts.append(
                PacketMediaArtifact(
                    sequence=sequence,
                    frame_path=frame_path,
                    audio_path=audio_path,
                    digest=item.digest,
                )
            )
        return tuple(artifacts)
    except BaseException as error:
        if created:
            try:
                shutil.rmtree(target)
            except OSError as cleanup_error:
                try:
                    error.add_note(f"unable to remove failed packet-media staging directory: {cleanup_error}")
                except AttributeError:
                    pass
        raise
