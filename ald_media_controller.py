"""Public ALD media-controller namespace.

The module composes the hardened deterministic core with local media-codec
interfaces while preserving the existing CLI and monkeypatch-compatible
module object.
"""

from __future__ import annotations

import sys

import ald_hardened_core as _core
import ald_media_codecs as _media


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
):
    setattr(_core, _name, getattr(_media, _name))


if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
