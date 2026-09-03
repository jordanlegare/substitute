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
    "MediaProfile",
    "DEFAULT_MEDIA_PROFILE",
    "DecodedFrameRecord",
    "QR_MAGIC",
    "encode_qr_payload",
    "decode_qr_payload",
):
    setattr(_core, _name, getattr(_media, _name))


if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
