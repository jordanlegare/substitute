import json
from pathlib import Path

import pytest

from ald_media_controller import ExitCode, main


PRODUCT_RECIPE = Path("recipes/majorana2_public_specs_reference_sim.json")


def test_compile_product_refuses_existing_output(tmp_path):
    output = tmp_path / "exists"
    output.mkdir()

    result = main(["compile-product", str(PRODUCT_RECIPE), "--output", str(output)])

    assert result == int(ExitCode.OUTPUT)


@pytest.mark.requires_ffmpeg
def test_product_cli_compile_verify_and_simulation_are_equivalent(tmp_path, capsys):
    bundle = tmp_path / "bundle"
    direct = tmp_path / "direct"
    product = tmp_path / "product"

    assert main(
        [
            "compile-product",
            str(PRODUCT_RECIPE),
            "--seed",
            "42",
            "--output",
            str(bundle),
        ]
    ) == int(ExitCode.OK)
    capsys.readouterr()

    for name in (
        "product.mp4",
        "recipe.canonical.json",
        "product.json",
        "product-top.svg",
        "product-stack.svg",
        "product-final.svg",
        "bundle.json",
    ):
        assert (bundle / name).is_file()
    document = json.loads((bundle / "product.json").read_text(encoding="utf-8"))
    assert document["physical_fabrication_mapping"] is False

    assert main(["verify-product", str(bundle / "bundle.json")]) == int(ExitCode.OK)
    verification = json.loads(capsys.readouterr().out)
    assert verification["protocol"] == "ALD-MEDIA/1"
    assert verification["media_type"] == "product-mp4"
    assert verification["packet_count"] == 7
    assert verification["signature_status"] == "UNSIGNED"
    assert len(verification["root_hash"]) == 64

    assert main(
        [
            "simulate",
            str(PRODUCT_RECIPE),
            "--seed",
            "42",
            "--output",
            str(direct),
        ]
    ) == int(ExitCode.OK)
    capsys.readouterr()
    assert main(
        [
            "simulate-product",
            str(bundle / "bundle.json"),
            "--seed",
            "42",
            "--output",
            str(product),
        ]
    ) == int(ExitCode.OK)
    capsys.readouterr()

    for name in ("surface-final.json", "cycles.csv", "audit.jsonl"):
        assert (direct / name).read_bytes() == (product / name).read_bytes()
