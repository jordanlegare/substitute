import dataclasses

import pytest

from ald_media_controller import (
    FrameDecodeError,
    compile_recipe,
    decode_qr_payload,
    encode_qr_payload,
    validate_recipe,
)


@pytest.fixture
def compiled_recipe():
    raw = {
        "protocol": "ALD-MEDIA/1",
        "recipe_id": "media-codec-test",
        "metadata": {"material": "generic"},
        "precursors": {
            "A": {"label": "A"},
            "B": {"label": "B"},
        },
        "initial_conditions": {
            "temperature_c": 25.0,
            "pressure_pa": 101325.0,
        },
        "limits": {
            "min_purge_ms": 1000,
            "max_temperature_c": 300.0,
            "max_pressure_pa": 200000.0,
            "max_cycles": 10,
            "max_runtime_ms": 600000,
            "max_residual_fraction": 0.01,
            "max_packet_bytes": 800,
        },
        "surface": {
            "model_version": "site-binomial/1",
            "regions": 1,
        },
        "instructions": [
            {"opcode": "CONFIGURE", "arguments": {}},
            {
                "opcode": "SET_TEMPERATURE",
                "arguments": {
                    "target_c": 150.0,
                    "ramp_c_per_min": 20.0,
                    "tolerance_c": 1.0,
                },
            },
            {
                "opcode": "EVACUATE",
                "arguments": {"target_pa": 100.0, "timeout_ms": 120000},
            },
            {"opcode": "STABILIZE", "arguments": {"duration_ms": 1000}},
            {
                "opcode": "ALD_CYCLE",
                "arguments": {
                    "precursor_a": "A",
                    "pulse_a_ms": 100,
                    "flow_a_sccm": 10.0,
                    "purge_a_ms": 5000,
                    "precursor_b": "B",
                    "pulse_b_ms": 100,
                    "flow_b_sccm": 10.0,
                    "purge_b_ms": 5000,
                    "repeat": 1,
                },
            },
            {
                "opcode": "SHUTDOWN",
                "arguments": {
                    "heater_ramp_c_per_min": 20.0,
                    "vent_target_pa": 101325.0,
                },
            },
        ],
    }
    return compile_recipe(validate_recipe(raw))


def test_qr_payload_round_trip(compiled_recipe):
    item = compiled_recipe.packets[0]

    decoded = decode_qr_payload(encode_qr_payload(item))

    assert decoded.canonical_bytes == item.canonical_bytes
    assert decoded.digest == item.digest
    assert decoded.sequence == item.packet.sequence


def test_qr_payload_rejects_oversized_packet(compiled_recipe):
    item = dataclasses.replace(compiled_recipe.packets[0], canonical_bytes=b"x" * 801)

    with pytest.raises(FrameDecodeError, match="800"):
        encode_qr_payload(item)


def test_qr_payload_rejects_trailing_bytes(compiled_recipe):
    encoded = encode_qr_payload(compiled_recipe.packets[0])

    with pytest.raises(FrameDecodeError, match="length"):
        decode_qr_payload(encoded + b"x")


def test_qr_payload_rejects_noncanonical_packet_bytes(compiled_recipe):
    item = compiled_recipe.packets[0]
    noncanonical = item.canonical_bytes.replace(b'"arguments":{}', b'"arguments": { }')
    assert noncanonical != item.canonical_bytes
    forged = dataclasses.replace(item, canonical_bytes=noncanonical)

    with pytest.raises(FrameDecodeError, match="canonical"):
        decode_qr_payload(encode_qr_payload(forged))
