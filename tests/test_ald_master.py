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
    {
        "recipe_id": "six-c",
        "path": "recipes/six-c.json",
        "precursor_count": 6,
        "category": "research",
        "chemistry_status": "conceptual-multicomponent-surrogate",
        "target_material": "Six C",
        "target_formula": "C6",
        "precursors": [],
    },
]


def test_filter_catalog_supports_precursor_counts_two_through_six():
    result = ald_master.filter_catalog(
        SAMPLE_ENTRIES,
        precursor_counts={4, 6},
        category="research",
    )

    assert [entry["recipe_id"] for entry in result] == ["four-b", "six-c"]


def test_filter_catalog_rejects_precursor_count_outside_supported_range():
    with pytest.raises(ValueError, match="2 through 6"):
        ald_master.filter_catalog(SAMPLE_ENTRIES, precursor_counts={1})


def test_filter_catalog_searches_recipe_target_formula_and_precursor_text():
    entries = [
        {
            **SAMPLE_ENTRIES[0],
            "precursors": [
                {"id": "A", "name": "hafnium tetrachloride", "formula": "HfCl4", "role": "source"}
            ],
        },
        SAMPLE_ENTRIES[1],
    ]

    by_formula = ald_master.filter_catalog(entries, search="hfcl4")
    by_target = ald_master.filter_catalog(entries, search="four b")

    assert [entry["recipe_id"] for entry in by_formula] == ["two-a"]
    assert [entry["recipe_id"] for entry in by_target] == ["four-b"]


def test_build_validate_workflow_maps_to_existing_controller_cli():
    workflow = ald_master.build_workflow(
        "validate",
        Path("recipes/compounds/example.json"),
        log_level="DEBUG",
    )

    assert workflow == [
        [
            "ald-media-controller",
            "--log-level",
            "DEBUG",
            "validate",
            "recipes/compounds/example.json",
        ]
    ]


def test_build_direct_simulation_workflow_maps_all_relevant_switches():
    workflow = ald_master.build_workflow(
        "simulate",
        Path("recipes/compounds/example.json"),
        seed=17,
        output=Path("build/direct"),
        overwrite=True,
        log_level="WARNING",
    )

    assert workflow == [
        [
            "ald-media-controller",
            "--log-level",
            "WARNING",
            "simulate",
            "recipes/compounds/example.json",
            "--seed",
            "17",
            "--output",
            "build/direct",
            "--overwrite",
        ]
    ]


def test_build_hls_workflow_compiles_verifies_and_simulates():
    workflow = ald_master.build_workflow(
        "hls",
        Path("recipes/compounds/example.json"),
        seed=7,
        output=Path("build/hls-example"),
        overwrite=True,
        signing_key=Path("keys/signing.pem"),
        require_signature=True,
        trusted_public_key=Path("keys/trusted.pem"),
        log_level="DEBUG",
    )

    assert workflow == [
        [
            "ald-media-controller",
            "--log-level",
            "DEBUG",
            "compile",
            "recipes/compounds/example.json",
            "--output",
            "build/hls-example/bundle",
            "--overwrite",
            "--signing-key",
            "keys/signing.pem",
        ],
        [
            "ald-media-controller",
            "--log-level",
            "DEBUG",
            "verify",
            "build/hls-example/bundle/stream.m3u8",
            "--require-signature",
            "--trusted-public-key",
            "keys/trusted.pem",
        ],
        [
            "ald-media-controller",
            "--log-level",
            "DEBUG",
            "simulate-media",
            "build/hls-example/bundle/stream.m3u8",
            "--seed",
            "7",
            "--output",
            "build/hls-example/simulation",
            "--overwrite",
            "--require-signature",
            "--trusted-public-key",
            "keys/trusted.pem",
        ],
    ]


def test_build_product_workflow_compiles_verifies_and_simulates():
    workflow = ald_master.build_workflow(
        "product",
        Path("recipes/compounds/example.json"),
        seed=9,
        output=Path("build/product-example"),
        overwrite=False,
        require_signature=True,
        trusted_public_key=Path("keys/trusted.pem"),
    )

    assert workflow == [
        [
            "ald-media-controller",
            "--log-level",
            "INFO",
            "compile-product",
            "recipes/compounds/example.json",
            "--seed",
            "9",
            "--output",
            "build/product-example/bundle",
        ],
        [
            "ald-media-controller",
            "--log-level",
            "INFO",
            "verify-product",
            "build/product-example/bundle/bundle.json",
            "--require-signature",
            "--trusted-public-key",
            "keys/trusted.pem",
        ],
        [
            "ald-media-controller",
            "--log-level",
            "INFO",
            "simulate-product",
            "build/product-example/bundle/bundle.json",
            "--seed",
            "9",
            "--output",
            "build/product-example/simulation",
            "--require-signature",
            "--trusted-public-key",
            "keys/trusted.pem",
        ],
    ]


def test_output_is_required_for_executable_workflows_except_validate():
    for action in ("simulate", "hls", "product"):
        with pytest.raises(ValueError, match="output"):
            ald_master.build_workflow(action, Path("recipe.json"))


def test_menu_state_supports_arrow_navigation_wraparound():
    state = ald_master.MenuState()

    state = state.handle("DOWN", 3)
    assert state.index == 1
    state = state.handle("UP", 3)
    assert state.index == 0
    state = state.handle("UP", 3)
    assert state.index == 2
    assert state.selection is None


def test_menu_state_supports_number_then_enter_selection():
    state = ald_master.MenuState()

    state = state.handle("2", 12)
    state = state.handle("ENTER", 12)

    assert state.selection == 1


def test_menu_state_supports_multi_digit_number_selection():
    state = ald_master.MenuState()

    state = state.handle("1", 12)
    state = state.handle("2", 12)
    state = state.handle("ENTER", 12)

    assert state.selection == 11


def test_menu_state_q_and_escape_cancel():
    assert ald_master.MenuState().handle("q", 3).cancelled is True
    assert ald_master.MenuState().handle("ESC", 3).cancelled is True


def test_non_tty_menu_falls_back_to_numbered_prompt():
    prompts = []

    selected = ald_master.select_menu(
        "Choose",
        ["alpha", "beta", "gamma"],
        interactive=False,
        input_fn=lambda prompt: prompts.append(prompt) or "2",
    )

    assert selected == 1
    assert prompts


def test_dry_run_prints_commands_without_executing(capsys):
    calls = []

    code = ald_master.run_commands(
        [["ald-media-controller", "validate", "recipe with space.json"]],
        dry_run=True,
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert code == 0
    assert calls == []
    assert "'recipe with space.json'" in capsys.readouterr().out


def test_cli_reference_documents_master_and_underlying_switches():
    text = ald_master.render_cli_reference()

    for switch in (
        "--precursors",
        "--category",
        "--status",
        "--search",
        "--recipe-id",
        "--recipe",
        "--all",
        "--action",
        "--seed",
        "--output",
        "--overwrite",
        "--signing-key",
        "--require-signature",
        "--trusted-public-key",
        "--log-level",
        "--dry-run",
        "--controller",
        "--catalog",
    ):
        assert switch in text

    for command in (
        "validate",
        "simulate",
        "compile",
        "verify",
        "simulate-media",
        "compile-product",
        "verify-product",
        "simulate-product",
    ):
        assert command in text


def test_parser_accepts_flag_mode_for_precursor_count_filter():
    parser = ald_master.build_parser()
    args = parser.parse_args(
        [
            "run",
            "--action",
            "simulate",
            "--precursors",
            "6",
            "--all",
            "--seed",
            "42",
            "--output",
            "build/catalog-6p",
            "--dry-run",
        ]
    )

    assert args.command == "run"
    assert args.action == "simulate"
    assert args.precursors == [6]
    assert args.run_all is True
    assert args.dry_run is True
