from pathlib import Path

from ald_media_controller import ExitCode, main


def test_checked_in_al2o3_recipe_runs_twice_identically(tmp_path):
    recipe = Path("recipes/generic_al2o3.json")
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert recipe.is_file()
    assert main(["validate", str(recipe)]) == ExitCode.OK
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(first)]) == ExitCode.OK
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(second)]) == ExitCode.OK

    assert {path.name for path in first.iterdir()} == {
        "audit.jsonl",
        "cycles.csv",
        "surface-final.json",
    }
    for name in ("audit.jsonl", "cycles.csv", "surface-final.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_checked_in_majorana2_public_reference_recipe_runs_deterministically(tmp_path):
    recipe = Path("recipes/majorana2_public_specs_reference_sim.json")
    first = tmp_path / "majorana2-first"
    second = tmp_path / "majorana2-second"

    assert recipe.is_file()
    assert main(["validate", str(recipe)]) == ExitCode.OK
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(first)]) == ExitCode.OK
    assert main(["simulate", str(recipe), "--seed", "42", "--output", str(second)]) == ExitCode.OK

    assert {path.name for path in first.iterdir()} == {
        "audit.jsonl",
        "cycles.csv",
        "surface-final.json",
    }
    for name in ("audit.jsonl", "cycles.csv", "surface-final.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
