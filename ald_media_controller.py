"""Public ALD media-controller namespace.

The module composes the hardened deterministic core with local QR/HLS media and
product-MP4 visualization/data-track interfaces while preserving the existing
monkeypatch-compatible module object.
"""

from __future__ import annotations

import sys

import ald_hardened_core as _core
import ald_media_codecs as _media
import ald_media_staging as _staging
import ald_hls_integration as _hls
import ald_hls_packaging as _packaging
import ald_hls_bundle as _bundle
import ald_hls_signature as _signature
import ald_hls_verify as _verify
import ald_compression as _compression
import ald_media_cli as _cli
import ald_product_scene as _product_scene
import ald_product_svg as _product_svg
import ald_product_data as _product_data
import ald_product_render as _product_render
import ald_product_mp4 as _product_mp4
import ald_product_bundle as _product_bundle
import ald_product_verify as _product_verify
import ald_product_cli as _product_cli


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
    "validate_hashed_packet",
    "decode_canonical_packet_bytes",
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

for _name in (
    "SignatureError",
    "SignatureStatus",
    "BundleSignature",
    "sign_bundle_index",
    "verify_bundle_signature",
    "verify_bundle_signature_bytes",
):
    setattr(_core, _name, getattr(_signature, _name))

for _name in (
    "IntegrityError",
    "VerifiedMediaRecipe",
    "verify_media_bundle",
):
    setattr(_core, _name, getattr(_verify, _name))

for _name in (
    "CompressionReport",
    "measure_procedural_compression",
    "measure_hls_bundle_bytes",
):
    setattr(_core, _name, getattr(_compression, _name))

for _name in (
    "SCENE_PROTOCOL",
    "PRODUCT_STAGES",
    "ProductLayer",
    "ProductTetron",
    "ProductGateLayer",
    "ProductQuantumDot",
    "SimulationOverlay",
    "ProductScene",
    "ProductDocument",
    "build_product_scene",
    "build_product_document",
    "canonical_product_json",
    "parse_product_json",
):
    setattr(_core, _name, getattr(_product_scene, _name))

for _name in (
    "render_top_svg",
    "render_stack_svg",
    "render_final_svg",
    "write_product_svgs",
):
    setattr(_core, _name, getattr(_product_svg, _name))

for _name in (
    "ProductDataError",
    "ProductDataRecord",
    "DATA_MAGIC",
    "DATA_VERSION",
    "DATA_SLOT_BYTES",
    "encode_product_slot",
    "decode_product_slot",
    "build_product_slots",
    "write_product_slot_stream",
):
    setattr(_core, _name, getattr(_product_data, _name))

for _name in (
    "ProductRenderError",
    "ProductTrackSources",
    "render_product_frame",
    "stage_product_tracks",
):
    setattr(_core, _name, getattr(_product_render, _name))

for _name in (
    "ProductDataPacketProbe",
    "ProductMP4Probe",
    "probe_product_mp4",
    "extract_product_data",
    "extract_product_audio",
    "mux_product_mp4",
    "probe_product_mp4_capabilities",
):
    setattr(_core, _name, getattr(_product_mp4, _name))

for _name in (
    "PRODUCT_BUNDLE_KEYS",
    "ProductBundleError",
    "write_product_bundle_index",
):
    setattr(_core, _name, getattr(_product_bundle, _name))

_core.ProductIntegrityError = _product_verify.IntegrityError
for _name in ("VerifiedProductRecipe", "verify_product_bundle"):
    setattr(_core, _name, getattr(_product_verify, _name))

_core.build_parser = _product_cli.build_parser
_core.main = _product_cli.main


if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core
