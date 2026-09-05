import argparse
from pathlib import Path

import pytest

import ald_master


SAMPLE_ENTRIES = [
    {
        "recipe_id": "two-a",
        "path": "recipes/two-a.json",
        "precursor_count": 2,
        "category": "oxides",
        "chemistry_status": "literature-grounded",
        "target_material": "Two A",
        "target_formula": "A2",
        "precursors": [],
    },
    {
        "recipe_id": "four-b",
        "path": "recipes/four-b.json",
        "precursor_count": 4,
        "category": "research",
        "chemistry_status": "conceptual-multicomponent-surrogate",
        "target_material": "Four B",
        "target_formula": "B4",
        "precursors": [],
    },
]


def test_interactive_recipe_path_is_shortened_to_search_recipe_workflow_execute(monkeypatch):
    menu_answers = iter([0, 0, 0, 1])
    menu_titles = []
    prompts = []
    captured = {}

    monkeypatch.setattr(ald_master, "load_catalog", lambda path: SAMPLE_ENTRIES)

    def fake_menu(title, options, **kwargs):
        menu_titles.append(title)
        return next(menu_answers)

    monkeypatch.setattr(ald_master, "select_menu", fake_menu)

    def fake_prompt(prompt, default=None):
        prompts.append(prompt)
        if prompt.startswith("Search"):
            return "four b"
        raise AssertionError(f"normal recipe path prompted for advanced option: {prompt}")

    monkeypatch.setattr(ald_master, "_prompt_text", fake_prompt)

    def fake_run(commands, *, dry_run=False, runner=None):
        captured["commands"] = commands
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(ald_master, "run_commands", fake_run)

    code = ald_master._interactive_main(
        argparse.Namespace(catalog=Path("catalog.json"), controller="ald-media-controller")
    )

    assert code == 0
    assert captured["dry_run"] is True
    assert captured["commands"][0][-1] == "recipes/four-b.json"
    assert len(menu_titles) == 4
    assert len(prompts) == 1


def test_all_mode_rejects_recipe_id_that_can_escape_output_root(monkeypatch):
    malicious = [{**SAMPLE_ENTRIES[0], "recipe_id": "../escape"}]
    monkeypatch.setattr(ald_master, "load_catalog", lambda path: malicious)
    monkeypatch.setattr(ald_master, "run_commands", lambda *args, **kwargs: 0)

    args = argparse.Namespace(
        action="simulate",
        output=Path("build/root"),
        recipe=None,
        recipe_id=None,
        run_all=True,
        precursors=None,
        category=None,
        chemistry_status=None,
        search=None,
        seed=42,
        overwrite=False,
        signing_key=None,
        require_signature=False,
        trusted_public_key=None,
        log_level="INFO",
        controller="ald-media-controller",
        catalog=Path("catalog.json"),
        dry_run=True,
    )

    with pytest.raises(ValueError, match="recipe_id.*output"):
        ald_master._run_flag_mode(args)
