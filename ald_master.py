"""Master launcher for Substitute's 2-6 precursor simulation catalog.

The launcher is orchestration-only. It discovers recipes in the compound
catalog and delegates execution to the existing ``ald-media-controller`` CLI.
It does not reinterpret chemistry, create physical process windows, or control
hardware.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable, Iterable, Sequence


PRECURSOR_COUNTS = (2, 3, 4, 5, 6)
ACTIONS = ("validate", "simulate", "hls", "product")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DEFAULT_CATALOG = Path("recipes/compounds/catalog.json")
DEFAULT_CONTROLLER = "ald-media-controller"


CLI_REFERENCE = """\
Substitute master precursor launcher
====================================

Purpose
-------
Browse and launch catalog recipes containing 2 through 6 declared precursors.
The launcher delegates execution to the existing ald-media-controller.
All repository recipes and resulting workflows remain simulation-only.

Invocation
----------
  ald-master                         interactive browser/launcher
  ald-master reference               complete switch and command reference
  ald-master list [FILTERS]          list matching catalog recipes
  ald-master run [OPTIONS]           run one recipe or all matching recipes
  ald-master -h, --help              standard argparse help

Global switches (place before the subcommand)
---------------------------------------------
  --catalog PATH                     catalog JSON (default: recipes/compounds/catalog.json)
  --controller EXECUTABLE            controller command (default: ald-media-controller)

Catalog filters
---------------
  --precursors {2,3,4,5,6}           precursor count; repeat to select several counts
  --category NAME                    exact catalog category
  --status NAME                      exact chemistry_status
  --search TEXT                      recipe/target/formula/category/status/precursor text

list switches
-------------
  --precursors {2,3,4,5,6}           repeatable precursor-count filter
  --category NAME                    category filter
  --status NAME                      chemistry-status filter
  --search TEXT                      case-insensitive text filter
  --recipe-id ID                     exact recipe id; repeatable
  -h, --help                         list-command help

run selection switches
----------------------
  --recipe PATH                      run a direct recipe path
  --recipe-id ID                     run one recipe selected from the catalog
  --all                              run every recipe matching supplied filters
  --precursors {2,3,4,5,6}           repeatable filter; validates a direct recipe count
  --category NAME                    category filter
  --status NAME                      chemistry-status filter
  --search TEXT                      case-insensitive catalog filter

run execution switches
----------------------
  --action {validate,simulate,hls,product}
                                     master workflow to execute
  --seed INTEGER                     deterministic simulation/render seed (default: 42)
  --output PATH                      output path/root; required except validate
  --overwrite                        pass overwrite to producing/simulation commands
  --signing-key PATH                 Ed25519 private key for compile/compile-product
  --require-signature                require signature during verify/simulation
  --trusted-public-key PATH          trusted Ed25519 public key for verify/simulation
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                                     controller log level (default: INFO)
  --dry-run                          print exact commands without executing them
  -h, --help                         run-command help

Underlying ald-media-controller mapping
---------------------------------------
The controller itself also supports -h/--help globally and per subcommand,
and --log-level may be supplied globally or on each controller subcommand.
The master launcher emits --log-level globally.

validate:
  ald-media-controller [--log-level LEVEL] validate RECIPE

simulate:
  ald-media-controller [--log-level LEVEL] simulate RECIPE
      --seed INTEGER --output DIR [--overwrite]

hls (three commands):
  ald-media-controller [--log-level LEVEL] compile RECIPE
      --output ROOT/bundle [--overwrite] [--signing-key PATH]
  ald-media-controller [--log-level LEVEL] verify ROOT/bundle/stream.m3u8
      [--require-signature] [--trusted-public-key PATH]
  ald-media-controller [--log-level LEVEL] simulate-media ROOT/bundle/stream.m3u8
      --seed INTEGER --output ROOT/simulation [--overwrite]
      [--require-signature] [--trusted-public-key PATH]

product (three commands):
  ald-media-controller [--log-level LEVEL] compile-product RECIPE
      [--seed INTEGER] --output ROOT/bundle [--overwrite] [--signing-key PATH]
  ald-media-controller [--log-level LEVEL] verify-product ROOT/bundle/bundle.json
      [--require-signature] [--trusted-public-key PATH]
  ald-media-controller [--log-level LEVEL] simulate-product ROOT/bundle/bundle.json
      --seed INTEGER --output ROOT/simulation [--overwrite]
      [--require-signature] [--trusted-public-key PATH]

Interactive controls
--------------------
  Up / Down arrows                   move the highlighted option
  Enter                              select the highlighted option
  Number + Enter                     select by displayed number; multi-digit supported
  Backspace                          edit a typed number
  q or Esc                           cancel/back out of the current menu

Interactive catalog flow
------------------------
  precursor count -> category -> chemistry status -> text search -> recipe
  -> workflow -> relevant switches -> command preview -> run/dry-run/cancel

Non-interactive terminals automatically fall back to numbered text prompts.
"""


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> list[dict[str, Any]]:
    catalog_path = Path(path)
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"unable to read catalog {catalog_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"catalog is not valid JSON: {error}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("catalog must contain an entries array")

    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(payload["entries"]):
        if not isinstance(entry, dict):
            raise ValueError(f"catalog entry {index} is not an object")
        count = entry.get("precursor_count")
        if count not in PRECURSOR_COUNTS:
            raise ValueError(
                f"catalog entry {entry.get('recipe_id', index)!r} has unsupported "
                f"precursor_count {count!r}"
            )
        if not isinstance(entry.get("recipe_id"), str) or not isinstance(
            entry.get("path"), str
        ):
            raise ValueError(f"catalog entry {index} is missing recipe_id/path")
        entries.append(entry)
    return entries


def _search_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "recipe_id",
        "path",
        "category",
        "chemistry_family",
        "chemistry_status",
        "target_material",
        "target_formula",
        "product_family",
        "exposure_signature",
    ):
        value = entry.get(key)
        if value is not None:
            parts.append(str(value))
    for precursor in entry.get("precursors", []):
        if isinstance(precursor, dict):
            parts.extend(str(value) for value in precursor.values() if value is not None)
    return " ".join(parts).casefold()


def filter_catalog(
    entries: Iterable[dict[str, Any]],
    *,
    precursor_counts: Iterable[int] | None = None,
    category: str | None = None,
    chemistry_status: str | None = None,
    search: str | None = None,
    recipe_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    counts = set(PRECURSOR_COUNTS if precursor_counts is None else precursor_counts)
    invalid = counts.difference(PRECURSOR_COUNTS)
    if invalid:
        bad = ", ".join(str(value) for value in sorted(invalid))
        raise ValueError(f"precursor count must be 2 through 6; got {bad}")

    wanted_ids = set(recipe_ids) if recipe_ids else None
    needle = search.casefold().strip() if search else None
    result: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("precursor_count") not in counts:
            continue
        if category is not None and entry.get("category") != category:
            continue
        if chemistry_status is not None and entry.get("chemistry_status") != chemistry_status:
            continue
        if wanted_ids is not None and entry.get("recipe_id") not in wanted_ids:
            continue
        if needle and needle not in _search_text(entry):
            continue
        result.append(entry)
    return result


def _base_command(controller: str, log_level: str, command: str) -> list[str]:
    if not controller:
        raise ValueError("controller executable must not be empty")
    if log_level not in LOG_LEVELS:
        raise ValueError(f"unsupported log level: {log_level}")
    return [controller, "--log-level", log_level, command]


def _append_overwrite(command: list[str], overwrite: bool) -> None:
    if overwrite:
        command.append("--overwrite")


def _append_signature_verification(
    command: list[str],
    require_signature: bool,
    trusted_public_key: Path | None,
) -> None:
    if require_signature:
        command.append("--require-signature")
    if trusted_public_key is not None:
        command.extend(["--trusted-public-key", os.fspath(trusted_public_key)])


def build_workflow(
    action: str,
    recipe_path: Path,
    *,
    seed: int = 42,
    output: Path | None = None,
    overwrite: bool = False,
    signing_key: Path | None = None,
    require_signature: bool = False,
    trusted_public_key: Path | None = None,
    log_level: str = "INFO",
    controller: str = DEFAULT_CONTROLLER,
) -> list[list[str]]:
    if action not in ACTIONS:
        raise ValueError(f"unsupported action: {action}")
    if action != "validate" and output is None:
        raise ValueError(f"output is required for {action}")

    recipe = os.fspath(recipe_path)
    if action == "validate":
        return [_base_command(controller, log_level, "validate") + [recipe]]

    assert output is not None
    if action == "simulate":
        command = _base_command(controller, log_level, "simulate") + [
            recipe,
            "--seed",
            str(seed),
            "--output",
            os.fspath(output),
        ]
        _append_overwrite(command, overwrite)
        return [command]

    bundle = output / "bundle"
    simulation = output / "simulation"

    if action == "hls":
        manifest = bundle / "stream.m3u8"
        compile_command = _base_command(controller, log_level, "compile") + [
            recipe,
            "--output",
            os.fspath(bundle),
        ]
        _append_overwrite(compile_command, overwrite)
        if signing_key is not None:
            compile_command.extend(["--signing-key", os.fspath(signing_key)])

        verify_command = _base_command(controller, log_level, "verify") + [
            os.fspath(manifest)
        ]
        _append_signature_verification(
            verify_command, require_signature, trusted_public_key
        )

        simulate_command = _base_command(controller, log_level, "simulate-media") + [
            os.fspath(manifest),
            "--seed",
            str(seed),
            "--output",
            os.fspath(simulation),
        ]
        _append_overwrite(simulate_command, overwrite)
        _append_signature_verification(
            simulate_command, require_signature, trusted_public_key
        )
        return [compile_command, verify_command, simulate_command]

    bundle_index = bundle / "bundle.json"
    compile_command = _base_command(controller, log_level, "compile-product") + [
        recipe,
        "--seed",
        str(seed),
        "--output",
        os.fspath(bundle),
    ]
    _append_overwrite(compile_command, overwrite)
    if signing_key is not None:
        compile_command.extend(["--signing-key", os.fspath(signing_key)])

    verify_command = _base_command(controller, log_level, "verify-product") + [
        os.fspath(bundle_index)
    ]
    _append_signature_verification(
        verify_command, require_signature, trusted_public_key
    )

    simulate_command = _base_command(controller, log_level, "simulate-product") + [
        os.fspath(bundle_index),
        "--seed",
        str(seed),
        "--output",
        os.fspath(simulation),
    ]
    _append_overwrite(simulate_command, overwrite)
    _append_signature_verification(
        simulate_command, require_signature, trusted_public_key
    )
    return [compile_command, verify_command, simulate_command]


@dataclass(frozen=True)
class MenuState:
    index: int = 0
    number_buffer: str = ""
    selection: int | None = None
    cancelled: bool = False

    def handle(self, key: str, option_count: int) -> "MenuState":
        if option_count <= 0:
            raise ValueError("menu requires at least one option")
        if key == "UP":
            return MenuState(index=(self.index - 1) % option_count)
        if key == "DOWN":
            return MenuState(index=(self.index + 1) % option_count)
        if key in {"q", "Q", "ESC"}:
            return replace(self, cancelled=True, selection=None)
        if key == "BACKSPACE":
            value = self.number_buffer[:-1]
            index = self.index
            if value and 1 <= int(value) <= option_count:
                index = int(value) - 1
            return MenuState(index=index, number_buffer=value)
        if len(key) == 1 and key.isdigit():
            value = self.number_buffer + key
            index = self.index
            if 1 <= int(value) <= option_count:
                index = int(value) - 1
            return MenuState(index=index, number_buffer=value)
        if key == "ENTER":
            if self.number_buffer:
                number = int(self.number_buffer)
                if 1 <= number <= option_count:
                    return replace(self, selection=number - 1)
                return MenuState(index=self.index)
            return replace(self, selection=self.index)
        return self


def _read_key_windows() -> str:
    import msvcrt

    char = msvcrt.getwch()
    if char in {"\x00", "\xe0"}:
        return {"H": "UP", "P": "DOWN"}.get(msvcrt.getwch(), "OTHER")
    if char in {"\r", "\n"}:
        return "ENTER"
    if char == "\x1b":
        return "ESC"
    if char in {"\x08", "\x7f"}:
        return "BACKSPACE"
    return char


def _read_key_posix() -> str:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
        if char in {"\r", "\n"}:
            return "ENTER"
        if char in {"\x7f", "\x08"}:
            return "BACKSPACE"
        if char != "\x1b":
            return char

        ready, _, _ = select.select([sys.stdin], [], [], 0.03)
        if not ready:
            return "ESC"
        if sys.stdin.read(1) != "[":
            return "ESC"
        ready, _, _ = select.select([sys.stdin], [], [], 0.03)
        if not ready:
            return "ESC"
        return {"A": "UP", "B": "DOWN"}.get(sys.stdin.read(1), "OTHER")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def read_key() -> str:
    return _read_key_windows() if os.name == "nt" else _read_key_posix()


def _render_menu(title: str, options: Sequence[str], state: MenuState) -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    print(title)
    print("Up/Down = move | Enter = select | number + Enter = select | q/Esc = cancel")
    print(f"Number: {state.number_buffer}" if state.number_buffer else "")
    for number, option in enumerate(options, start=1):
        marker = ">" if number - 1 == state.index else " "
        print(f"{marker} {number:>3}. {option}")
    sys.stdout.flush()


def select_menu(
    title: str,
    options: Sequence[str],
    *,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    key_reader: Callable[[], str] = read_key,
) -> int | None:
    if not options:
        raise ValueError("menu requires at least one option")
    if interactive is None:
        interactive = bool(sys.stdin.isatty() and sys.stdout.isatty())

    if not interactive:
        print(title)
        for number, option in enumerate(options, start=1):
            print(f"  {number}. {option}")
        while True:
            value = input_fn(f"Select 1-{len(options)} (q to cancel): ").strip()
            if value.casefold() in {"q", "quit", "esc", "escape"}:
                return None
            try:
                selected = int(value)
            except ValueError:
                continue
            if 1 <= selected <= len(options):
                return selected - 1

    state = MenuState()
    while True:
        _render_menu(title, options, state)
        state = state.handle(key_reader(), len(options))
        if state.cancelled:
            return None
        if state.selection is not None:
            return state.selection


def run_commands(
    commands: Sequence[Sequence[str]],
    *,
    dry_run: bool = False,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    for command in commands:
        argv = [str(value) for value in command]
        print(f"$ {shlex.join(argv)}")
        if dry_run:
            continue
        try:
            result = runner(argv, check=False)
        except FileNotFoundError:
            print(f"ald-master: command not found: {argv[0]}", file=sys.stderr)
            return 127
        returncode = int(getattr(result, "returncode", 0))
        if returncode != 0:
            return returncode
    return 0


def render_cli_reference() -> str:
    return CLI_REFERENCE


def _add_catalog_filters(
    parser: argparse.ArgumentParser, *, recipe_ids: bool = False
) -> None:
    parser.add_argument(
        "--precursors",
        type=int,
        choices=PRECURSOR_COUNTS,
        action="append",
        help="precursor count; repeat for multiple counts",
    )
    parser.add_argument("--category", help="exact catalog category")
    parser.add_argument(
        "--status", dest="chemistry_status", help="exact chemistry_status"
    )
    parser.add_argument("--search", help="case-insensitive catalog text search")
    if recipe_ids:
        parser.add_argument(
            "--recipe-id", action="append", help="exact catalog recipe id"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ald-master",
        description="Interactive and flag-driven launcher for Substitute 2-6 precursor recipes.",
        epilog="Use 'ald-master reference' for the complete controller switch map.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--controller", default=DEFAULT_CONTROLLER)
    commands = parser.add_subparsers(dest="command")

    commands.add_parser(
        "reference", help="show complete master and controller switch reference"
    )

    list_parser = commands.add_parser(
        "list", help="list matching 2-6 precursor catalog recipes"
    )
    _add_catalog_filters(list_parser, recipe_ids=True)

    run_parser = commands.add_parser(
        "run", help="execute one recipe or all matching catalog recipes"
    )
    run_parser.add_argument("--action", choices=ACTIONS, required=True)
    selector = run_parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--recipe", type=Path, help="direct recipe path")
    selector.add_argument("--recipe-id", help="exact catalog recipe id")
    selector.add_argument(
        "--all", dest="run_all", action="store_true", help="run all matching recipes"
    )
    _add_catalog_filters(run_parser)
    run_parser.add_argument("--seed", type=int, default=42)
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--overwrite", action="store_true")
    run_parser.add_argument("--signing-key", type=Path)
    run_parser.add_argument("--require-signature", action="store_true")
    run_parser.add_argument("--trusted-public-key", type=Path)
    run_parser.add_argument("--log-level", choices=LOG_LEVELS, default="INFO")
    run_parser.add_argument("--dry-run", action="store_true")
    return parser


def _entry_label(entry: dict[str, Any]) -> str:
    count = entry.get("precursor_count", "?")
    recipe_id = entry.get("recipe_id", "<unknown>")
    target = (
        entry.get("target_material")
        or entry.get("target_formula")
        or "unspecified target"
    )
    category = entry.get("category", "uncategorized")
    return f"[{count}p] {recipe_id} - {target} ({category})"


def _print_entries(entries: Sequence[dict[str, Any]]) -> None:
    if not entries:
        print("No matching catalog recipes.")
        return
    for number, entry in enumerate(entries, start=1):
        print(f"{number:>3}. {_entry_label(entry)}")
        print(f"     {entry['path']}")
        precursors = entry.get("precursors", [])
        if precursors:
            signature = " -> ".join(
                f"{item.get('id', '?')}:{item.get('name', '?')}"
                for item in precursors
                if isinstance(item, dict)
            )
            if signature:
                print(f"     {signature}")


def _read_direct_recipe_count(path: Path) -> tuple[int, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"unable to read recipe {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"recipe is not valid JSON: {error}") from error

    precursors = payload.get("precursors") if isinstance(payload, dict) else None
    if not isinstance(precursors, dict):
        raise ValueError("recipe must contain a precursors object")
    count = len(precursors)
    if count not in PRECURSOR_COUNTS:
        raise ValueError(
            f"master launcher supports recipes with 2 through 6 precursors; got {count}"
        )
    recipe_id = (
        payload.get("recipe_id")
        if isinstance(payload.get("recipe_id"), str)
        else path.stem
    )
    return count, recipe_id


def _safe_output_component(recipe_id: str) -> str:
    """Return a recipe id that is safe to append to a batch output root."""
    if (
        not recipe_id
        or recipe_id in {".", ".."}
        or "/" in recipe_id
        or "\\" in recipe_id
        or "\x00" in recipe_id
    ):
        raise ValueError(
            f"recipe_id {recipe_id!r} is not safe for output directory naming"
        )
    return recipe_id


def _filter_from_args(
    entries: Sequence[dict[str, Any]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    recipe_id_value = getattr(args, "recipe_id", None)
    recipe_ids = recipe_id_value if isinstance(recipe_id_value, list) else None
    return filter_catalog(
        entries,
        precursor_counts=args.precursors,
        category=args.category,
        chemistry_status=args.chemistry_status,
        search=args.search,
        recipe_ids=recipe_ids,
    )


def _run_flag_mode(args: argparse.Namespace) -> int:
    if args.action != "validate" and args.output is None:
        raise ValueError("--output is required unless --action validate is used")

    if args.recipe is not None:
        count, recipe_id = _read_direct_recipe_count(args.recipe)
        if args.precursors is not None and count not in set(args.precursors):
            raise ValueError(
                f"direct recipe declares {count} precursors and does not match --precursors"
            )
        recipes = [(recipe_id, args.recipe)]
    else:
        entries = load_catalog(args.catalog)
        filtered = filter_catalog(
            entries,
            precursor_counts=args.precursors,
            category=args.category,
            chemistry_status=args.chemistry_status,
            search=args.search,
        )
        if args.recipe_id is not None:
            filtered = [
                entry for entry in filtered if entry["recipe_id"] == args.recipe_id
            ]
            if not filtered:
                raise ValueError(
                    f"catalog recipe not found or filtered out: {args.recipe_id}"
                )
        elif not args.run_all:
            raise ValueError("select --recipe, --recipe-id, or --all")
        if not filtered:
            raise ValueError("no catalog recipes match the requested filters")
        recipes = [
            (entry["recipe_id"], Path(entry["path"])) for entry in filtered
        ]

    for recipe_id, path in recipes:
        output = args.output
        if args.run_all and output is not None:
            output = output / _safe_output_component(recipe_id)
        print(f"\n=== {recipe_id} ===")
        workflow = build_workflow(
            args.action,
            path,
            seed=args.seed,
            output=output,
            overwrite=args.overwrite,
            signing_key=args.signing_key,
            require_signature=args.require_signature,
            trusted_public_key=args.trusted_public_key,
            log_level=args.log_level,
            controller=args.controller,
        )
        code = run_commands(workflow, dry_run=args.dry_run)
        if code != 0:
            return code
    return 0


def _prompt_text(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return default if not value and default is not None else value


def _prompt_int(prompt: str, default: int) -> int:
    while True:
        value = _prompt_text(prompt, str(default))
        try:
            return int(value)
        except ValueError:
            print("Enter an integer.")


def _menu_yes_no(title: str, *, default_yes: bool = False) -> bool:
    options = ["Yes", "No"] if default_yes else ["No", "Yes"]
    selected = select_menu(title, options)
    return selected is not None and options[selected] == "Yes"


def _interactive_main(args: argparse.Namespace) -> int:
    entries = load_catalog(args.catalog)

    count_options = ["All precursor counts (2-6)"] + [
        f"{count} precursors" for count in PRECURSOR_COUNTS
    ]
    selected = select_menu("Select precursor count", count_options)
    if selected is None:
        return 0
    counts = None if selected == 0 else {PRECURSOR_COUNTS[selected - 1]}
    filtered = filter_catalog(entries, precursor_counts=counts)

    categories = sorted(
        {str(entry.get("category")) for entry in filtered if entry.get("category")}
    )
    category_options = ["All categories"] + categories
    selected = select_menu("Select category", category_options)
    if selected is None:
        return 0
    if selected:
        filtered = filter_catalog(filtered, category=category_options[selected])

    statuses = sorted(
        {
            str(entry.get("chemistry_status"))
            for entry in filtered
            if entry.get("chemistry_status")
        }
    )
    status_options = ["All chemistry statuses"] + statuses
    selected = select_menu("Select chemistry status", status_options)
    if selected is None:
        return 0
    if selected:
        filtered = filter_catalog(
            filtered, chemistry_status=status_options[selected]
        )

    search_value = _prompt_text(
        "Search recipe/target/formula/precursor (blank for all)"
    )
    if search_value:
        filtered = filter_catalog(filtered, search=search_value)

    if not filtered:
        print("No recipes match those filters.")
        return 1

    selected = select_menu(
        "Select recipe", [_entry_label(entry) for entry in filtered]
    )
    if selected is None:
        return 0
    entry = filtered[selected]

    action_labels = [
        "Validate recipe",
        "Direct deterministic simulation",
        "HLS: compile -> verify -> simulate-media",
        "Product MP4: compile-product -> verify-product -> simulate-product",
    ]
    selected = select_menu("Select workflow", action_labels)
    if selected is None:
        return 0
    action = ACTIONS[selected]

    seed = 42
    output: Path | None = None
    overwrite = False
    signing_key: Path | None = None
    require_signature = False
    trusted_public_key: Path | None = None

    if action != "validate":
        seed = _prompt_int("Seed", 42)
        output = Path(
            _prompt_text(
                "Output", f"build/master/{entry['recipe_id']}/{action}"
            )
        )
        overwrite = _menu_yes_no("Overwrite existing output if present?")

    if action in {"hls", "product"}:
        signing_value = _prompt_text("Signing key PEM (blank for none)")
        signing_key = Path(signing_value) if signing_value else None
        require_signature = _menu_yes_no(
            "Require signature during verification?"
        )
        trusted_value = _prompt_text(
            "Trusted public key PEM (blank for none)"
        )
        trusted_public_key = Path(trusted_value) if trusted_value else None

    selected = select_menu("Log level", list(LOG_LEVELS))
    if selected is None:
        return 0
    log_level = LOG_LEVELS[selected]

    workflow = build_workflow(
        action,
        Path(entry["path"]),
        seed=seed,
        output=output,
        overwrite=overwrite,
        signing_key=signing_key,
        require_signature=require_signature,
        trusted_public_key=trusted_public_key,
        log_level=log_level,
        controller=args.controller,
    )

    print("\nPlanned commands:")
    for command in workflow:
        print(f"  $ {shlex.join(command)}")
    selected = select_menu(
        "Execute workflow?", ["Run now", "Dry run only", "Cancel"]
    )
    if selected is None or selected == 2:
        return 0
    return run_commands(workflow, dry_run=selected == 1)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "reference":
            print(render_cli_reference())
            return 0
        if args.command == "list":
            entries = load_catalog(args.catalog)
            matches = _filter_from_args(entries, args)
            _print_entries(matches)
            return 0 if matches else 1
        if args.command == "run":
            return _run_flag_mode(args)
        return _interactive_main(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except ValueError as error:
        print(f"ald-master: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
