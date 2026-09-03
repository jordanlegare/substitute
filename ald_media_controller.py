"""Public ALD media-controller namespace.

The module composes the hardened deterministic core with local media-codec,
staging, HLS packaging, and bundle-verification interfaces while preserving
the existing CLI and monkeypatch-compatible module object.
"""

from __future__ import annotations

import sys

import ald_hardened_core as _core
import ald_media_codecs as _media
import ald_media_staging as _staging
import ald_hls_integration as _hls
import ald_hls_packaging as _packaging
import ald_hls_bundle as _bundle


for _name in (
    "FrameDecodeError",
    "AudioDecodeError",
    "MediaProfile",
    "DEFAULT_MEDIA_PROFILE",
    "DecodedFrameRecord",
    "AudioRecord",
    "QR_MAGIC",
    "AUDIO_PREAMBLE",
    "AUDIO_VERSION",
    "AUDIO_RECORD_BYTES",
    "encode_qr_payload",
    "decode_qr_payload",
    "render_instruction_frame",
    "decode_instruction_frame",
    "build_audio_record",
    "parse_audio_record",
    "manchester_encode",
    "manchester_decode",
    "encode_checksum_audio",
    "write_checksum_wav",
    "read_checksum_wav",
    "decode_checksum_audio",
):
    setattr(_core, _name, getattr(_media, _name))

for _name in ("PacketMediaArtifact", "stage_packet_media"):
    setattr(_core, _name, getattr(_staging, _name))

for _name in (
    "MediaBuildError",
    "MediaCapabilities",
    "probe_media_capabilities",
    "run_media_tool",
):
    setattr(_core, _name, getattr(_hls, _name))

for _name in ("probe_media_json", "mux_packet_mp4", "package_hls"):
    setattr(_core, _name, getattr(_packaging, _name))

for _name in (
    "MediaVerificationError",
    "PlaylistSegment",
    "LocalPlaylist",
    "BundlePacket",
    "BundleIndex",
    "parse_local_playlist",
    "write_bundle_index",
):
    setattr(_core, _name, getattr(_bundle, _name))


if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
