"""Extended ald-master CLI with offline compatibility research commands.

This package facade preserves the existing recipe-launcher implementation while
adding evidence-graph queries, candidate ranking, and a deliberately shorter
interactive path. Compatibility output is research evidence for offline
simulation only; it is not a chemical-mixing or equipment-safety decision.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import ald_compatibility as compatibility


_CORE_PATH = Path(__file__).resolve().parent.parent / "ald_master.py"
_SPEC = importlib.util.spec_from_file_location("_ald_master_core", _CORE_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise ImportError(f"unable to load ald-master core from {_CORE_PATH}")
_core = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _core
_SPEC.loader.exec_module(_core)

for _name, _value in vars(_core).items():
    if not _name.startswith("__"):
        globals()[_name] = _value


DEFAULT_COMPAT_MODEL = Path("compatibility/model-v1.json")
DEFAULT_COMPAT_EVIDENCE = Path("compatibility/evidence-overrides.json")
DEFAULT_COMPAT_SNAPSHOT = Path("build/compatibility/snapshot.json")
EVIDENCE_LEVELS = (
    "E0_UNKNOWN",
    "E1_HEURISTIC",
    "E2_ANALOGUE",
    "E3_CORROBORATED",
    "E4_DIRECT",
)

_COMPAT_REFERENCE = r"""

Compatibility evidence engine
-----------------------------
Global inputs (place before the command):
  --compat-model PATH       Versioned scoring model (default compatibility/model-v1.json)
  --compat-evidence PATH    Curated offline evidence (default compatibility/evidence-overrides.json)

Commands:
  ald-master compatibility-build [--output PATH]
  ald-master compatible precursor A [B] [--top N] [--json]
  ald-master compatible material A [B] [--top N] [--json]
  ald-master candidates [--min-size 2] [--max-size 6] [--top N]
      [--beam-width N] [--search TEXT] [--novel-only]
      [--minimum-score 0..100] [--minimum-evidence LEVEL] [--json]
  ald-master explain precursor A B [--json]
  ald-master explain material A B [--json]
  ald-master explain candidate A B [C ... F] [--json]
  ald-master compatibility-report [--json]

Evidence levels:
  E0_UNKNOWN < E1_HEURISTIC < E2_ANALOGUE < E3_CORROBORATED < E4_DIRECT
  Explicit strong negative curated evidence is E_CONFLICT and is never treated
  as merely missing evidence.

Interactive top menu:
  Recipe workflow | Precursor compatibility | Material compatibility |
  Rank precursor candidates | Compatibility report

Normal recipe interaction is shortened to:
  Search -> recipe -> workflow -> Run / Dry run / Advanced / Cancel
Advanced exposes seed/output/overwrite/signature/log-level controls.

Compatibility is evidence support for offline simulation research only. It is
not a chemical-mixing, reactor/equipment-safety, or fabrication-readiness
assessment.
"""


def render_cli_reference() -> str:
    return _core.render_cli_reference().rstrip() + _COMPAT_REFERENCE


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("ald-master parser has no command subparser")


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = _core.build_parser()
    parser.add_argument(
        "--compat-model",
        type=Path,
        default=DEFAULT_COMPAT_MODEL,
        help="versioned compatibility scoring model",
    )
    parser.add_argument(
        "--compat-evidence",
        type=Path,
        default=DEFAULT_COMPAT_EVIDENCE,
        help="curated offline compatibility evidence overrides",
    )
    commands = _subparser_action(parser)

    build = commands.add_parser(
        "compatibility-build",
        help="build the deterministic exhaustive compatibility snapshot",
    )
    build.add_argument("--output", type=Path, default=DEFAULT_COMPAT_SNAPSHOT)

    compatible = commands.add_parser(
        "compatible",
        help="query precursor or directed material compatibility evidence",
    )
    compatible_graph = compatible.add_subparsers(dest="graph", required=True)
    for graph in ("precursor", "material"):
        query = compatible_graph.add_parser(graph)
        query.add_argument("entities", nargs="+", metavar="ENTITY")
        query.add_argument("--top", type=int, default=20)
        _add_json_flag(query)

    candidates = commands.add_parser(
        "candidates", help="rank bounded 2-6 precursor candidates"
    )
    candidates.add_argument("--min-size", type=int, default=2)
    candidates.add_argument("--max-size", type=int, default=6)
    candidates.add_argument("--top", type=int, default=20)
    candidates.add_argument("--beam-width", type=int, default=None)
    candidates.add_argument("--search")
    candidates.add_argument("--novel-only", action="store_true")
    candidates.add_argument("--minimum-score", type=float, default=0.0)
    candidates.add_argument(
        "--minimum-evidence", choices=EVIDENCE_LEVELS, default="E0_UNKNOWN"
    )
    _add_json_flag(candidates)

    explain = commands.add_parser("explain", help="explain compatibility evidence")
    explain_graph = explain.add_subparsers(dest="graph", required=True)
    for graph in ("precursor", "material"):
        pair = explain_graph.add_parser(graph)
        pair.add_argument("entities", nargs=2, metavar="ENTITY")
        _add_json_flag(pair)
    candidate = explain_graph.add_parser("candidate")
    candidate.add_argument("entities", nargs="+", metavar="PRECURSOR")
    _add_json_flag(candidate)

    report = commands.add_parser(
        "compatibility-report", help="summarize compatibility graph coverage"
    )
    _add_json_flag(report)
    return parser


def _sync_core_bindings() -> None:
    """Keep existing core functions compatible with facade-level monkeypatching."""
    for name in (
        "load_catalog",
        "filter_catalog",
        "build_workflow",
        "run_commands",
        "_load_direct_recipe_precursor_count",
        "_safe_output_component",
    ):
        if name in globals():
            setattr(_core, name, globals()[name])


def _run_flag_mode(args: argparse.Namespace) -> int:
    _sync_core_bindings()
    return _core._run_flag_mode(args)


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


def _build_compatibility_snapshot_from_args(args: argparse.Namespace) -> dict[str, Any]:
    entries = load_catalog(args.catalog)
    model_path = Path(getattr(args, "compat_model", DEFAULT_COMPAT_MODEL))
    evidence_path = Path(getattr(args, "compat_evidence", DEFAULT_COMPAT_EVIDENCE))
    model = compatibility.load_model(model_path)
    evidence = compatibility.load_evidence_overrides(evidence_path)
    return compatibility.build_compatibility_snapshot(entries, model, evidence)


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _entity_text(entity: dict[str, Any]) -> str:
    formula = str(entity.get("formula", "")).strip()
    name = str(entity.get("name", "")).strip()
    if formula and name and formula.casefold() != name.casefold():
        return f"{formula} ({name})"
    return formula or name or str(entity.get("id", "?"))


def _print_evidence_edge(edge: dict[str, Any]) -> None:
    left = _entity_text(edge.get("a", {}))
    right = _entity_text(edge.get("b", {}))
    connector = " -> " if str(edge.get("id", "")).startswith("mi-") else " + "
    print(f"{left}{connector}{right}")
    print(
        f"  score={float(edge.get('score', 0.0)):.2f}  "
        f"coverage={100.0 * float(edge.get('coverage', 0.0)):.1f}%  "
        f"evidence={edge.get('evidence_level')}  verdict={edge.get('verdict')}"
    )
    for feature in edge.get("features", []):
        if not feature.get("available"):
            continue
        print(
            f"  - {feature.get('family')}: value={float(feature.get('value', 0.0)):.2f} "
            f"reliability={float(feature.get('reliability', 0.0)):.2f}"
        )
        note = str(feature.get("note", "")).strip()
        if note:
            print(f"    {note}")
        for source in feature.get("sources", []):
            if isinstance(source, dict):
                print(
                    f"    source: {source.get('type', '?')}:{source.get('identifier', '?')}"
                )


def _print_edge_list(edges: list[dict[str, Any]]) -> None:
    if not edges:
        print("No compatibility edges found.")
        return
    for index, edge in enumerate(edges, start=1):
        left = _entity_text(edge.get("a", {}))
        right = _entity_text(edge.get("b", {}))
        connector = " -> " if str(edge.get("id", "")).startswith("mi-") else " + "
        print(
            f"{index:>2}. {left}{connector}{right}  "
            f"score={float(edge.get('score', 0.0)):.1f}  "
            f"coverage={100.0 * float(edge.get('coverage', 0.0)):.0f}%  "
            f"{edge.get('evidence_level')}"
        )


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " + ".join(_entity_text(item) for item in candidate.get("precursors", []))


def _print_candidate(candidate: dict[str, Any], *, prefix: str = "") -> None:
    weakest = candidate.get("weakest_pair")
    weakest_text = "none"
    if isinstance(weakest, dict):
        weakest_text = (
            f"{_entity_text(weakest.get('a', {}))} + "
            f"{_entity_text(weakest.get('b', {}))}"
        )
    print(
        f"{prefix}{_candidate_text(candidate)}  score={float(candidate.get('score', 0.0)):.1f}  "
        f"coverage={float(candidate.get('coverage', 0.0)):.1f}%  "
        f"{candidate.get('evidence_level')}  "
        f"{'novel' if candidate.get('novel') else 'catalog-known'}"
    )
    print(f"    weakest: {weakest_text}")


def _print_candidates(candidates: list[dict[str, Any]]) -> None:
    if not candidates:
        print("No candidates match the requested evidence constraints.")
        return
    for index, candidate in enumerate(candidates, start=1):
        _print_candidate(candidate, prefix=f"{index:>2}. ")


def _report_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": snapshot.get("schema"),
        "safety_notice": snapshot.get("safety_notice"),
        "summary": snapshot.get("summary", {}),
        "model_digest": snapshot.get("model_digest"),
        "catalog_digest": snapshot.get("catalog_digest"),
        "evidence_digest": snapshot.get("evidence_digest"),
    }


def _print_report(snapshot: dict[str, Any]) -> None:
    summary = snapshot.get("summary", {})
    print("Compatibility evidence report")
    print(f"  unique precursors: {summary.get('unique_precursors', 0)}")
    print(f"  exhaustive precursor pairs: {summary.get('precursor_pairs', 0)}")
    print(f"  unique materials: {summary.get('unique_materials', 0)}")
    print(
        "  directed material interfaces: "
        f"{summary.get('directed_material_interfaces', 0)}"
    )
    print(f"  precursor verdicts: {summary.get('precursor_verdicts', {})}")
    print(
        "  precursor evidence levels: "
        f"{summary.get('precursor_evidence_levels', {})}"
    )
    print(f"  material verdicts: {summary.get('material_verdicts', {})}")
    print(
        "  material evidence levels: "
        f"{summary.get('material_evidence_levels', {})}"
    )
    print(f"  model digest: {snapshot.get('model_digest')}")
    print(f"  catalog digest: {snapshot.get('catalog_digest')}")
    print(f"  evidence digest: {snapshot.get('evidence_digest')}")
    print(f"  safety boundary: {snapshot.get('safety_notice', compatibility.SAFETY_NOTICE)}")


def _dispatch_compatible(args: argparse.Namespace) -> int:
    if not 1 <= len(args.entities) <= 2:
        raise ValueError("compatible queries accept one or two entities")
    snapshot = _build_compatibility_snapshot_from_args(args)
    query = compatibility.query_precursor if args.graph == "precursor" else compatibility.query_material
    result = query(
        snapshot,
        args.entities[0],
        args.entities[1] if len(args.entities) == 2 else None,
        top=args.top,
    )
    if args.json:
        _json_print(result)
    elif isinstance(result, list):
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        _print_edge_list(result)
    else:
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        _print_evidence_edge(result)
    return 0 if result else 1


def _dispatch_candidates(args: argparse.Namespace) -> int:
    snapshot = _build_compatibility_snapshot_from_args(args)
    result = compatibility.rank_candidates(
        snapshot,
        min_size=args.min_size,
        max_size=args.max_size,
        top=args.top,
        beam_width=args.beam_width,
        search=args.search,
        novel_only=args.novel_only,
        minimum_score=args.minimum_score,
        minimum_evidence=args.minimum_evidence,
    )
    if args.json:
        _json_print(result)
    else:
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        _print_candidates(result)
    return 0 if result else 1


def _dispatch_explain(args: argparse.Namespace) -> int:
    snapshot = _build_compatibility_snapshot_from_args(args)
    if args.graph == "candidate":
        result = compatibility.explain_candidate(snapshot, args.entities)
    elif args.graph == "precursor":
        result = compatibility.query_precursor(snapshot, *args.entities)
    else:
        result = compatibility.query_material(snapshot, *args.entities)
    if args.json:
        _json_print(result)
    else:
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        if args.graph == "candidate":
            _print_candidate(result)
            print(f"    components: {result.get('components', {})}")
            print(f"    matching recipes: {result.get('matching_recipe_ids', [])}")
            print(f"    subset recipes: {result.get('subset_recipe_ids', [])}")
        else:
            _print_evidence_edge(result)
    return 0


def _dispatch_build(args: argparse.Namespace) -> int:
    snapshot = _build_compatibility_snapshot_from_args(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(compatibility.canonical_json_bytes(snapshot))
    print(f"Wrote deterministic compatibility snapshot: {output}")
    print(
        f"  {snapshot['summary']['unique_precursors']} precursors / "
        f"{snapshot['summary']['precursor_pairs']} pairs / "
        f"{snapshot['summary']['unique_materials']} materials / "
        f"{snapshot['summary']['directed_material_interfaces']} directed interfaces"
    )
    return 0


def _dispatch_report(args: argparse.Namespace) -> int:
    snapshot = _build_compatibility_snapshot_from_args(args)
    if args.json:
        _json_print(_report_payload(snapshot))
    else:
        _print_report(snapshot)
    return 0


def _advanced_recipe_options(entry: dict[str, Any], action: str) -> dict[str, Any]:
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
        require_signature = _menu_yes_no("Require signature during verification?")
        trusted_value = _prompt_text("Trusted public key PEM (blank for none)")
        trusted_public_key = Path(trusted_value) if trusted_value else None
    selected = select_menu("Log level", list(LOG_LEVELS))
    if selected is None:
        return {"cancelled": True}
    return {
        "cancelled": False,
        "seed": seed,
        "output": output,
        "overwrite": overwrite,
        "signing_key": signing_key,
        "require_signature": require_signature,
        "trusted_public_key": trusted_public_key,
        "log_level": LOG_LEVELS[selected],
    }


def _interactive_recipe_mode(args: argparse.Namespace) -> int:
    entries = load_catalog(args.catalog)
    search_value = _prompt_text("Search recipe/target/formula/precursor (blank for all)")
    filtered = filter_catalog(entries, search=search_value or None)
    if not filtered:
        print("No recipes match that search.")
        return 1
    selected = select_menu("Select recipe", [_entry_label(entry) for entry in filtered])
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

    execution = select_menu(
        "Execute workflow?", ["Run now", "Dry run only", "Advanced", "Cancel"]
    )
    if execution is None or execution == 3:
        return 0

    options: dict[str, Any] = {
        "seed": 42,
        "output": (
            None
            if action == "validate"
            else Path(f"build/master/{_safe_output_component(str(entry['recipe_id']))}/{action}")
        ),
        "overwrite": False,
        "signing_key": None,
        "require_signature": False,
        "trusted_public_key": None,
        "log_level": "INFO",
    }
    dry_run = execution == 1
    if execution == 2:
        options = _advanced_recipe_options(entry, action)
        if options.get("cancelled"):
            return 0
        final = select_menu("Execute advanced workflow?", ["Run now", "Dry run only", "Cancel"])
        if final is None or final == 2:
            return 0
        dry_run = final == 1

    workflow = build_workflow(
        action,
        Path(entry["path"]),
        seed=int(options["seed"]),
        output=options["output"],
        overwrite=bool(options["overwrite"]),
        signing_key=options["signing_key"],
        require_signature=bool(options["require_signature"]),
        trusted_public_key=options["trusted_public_key"],
        log_level=str(options["log_level"]),
        controller=args.controller,
    )
    return run_commands(workflow, dry_run=dry_run)


def _split_interactive_entities(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _interactive_compatibility_query(args: argparse.Namespace, graph: str) -> int:
    label = "Precursor" if graph == "precursor" else "Material"
    value = _prompt_text(f"{label}(s), comma-separated for a pair")
    entities = _split_interactive_entities(value)
    if not 1 <= len(entities) <= 2:
        print("Enter one entity or a comma-separated pair.")
        return 2
    snapshot = _build_compatibility_snapshot_from_args(args)
    query = compatibility.query_precursor if graph == "precursor" else compatibility.query_material
    result = query(snapshot, entities[0], entities[1] if len(entities) == 2 else None, top=20)
    print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
    if isinstance(result, list):
        _print_edge_list(result)
    else:
        _print_evidence_edge(result)
    return 0 if result else 1


def _interactive_candidates(args: argparse.Namespace) -> int:
    search = _prompt_text("Candidate search (blank for all)")
    snapshot = _build_compatibility_snapshot_from_args(args)
    result = compatibility.rank_candidates(snapshot, search=search or None)
    print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
    _print_candidates(result)
    return 0 if result else 1


def _interactive_main(args: argparse.Namespace) -> int:
    selected = select_menu(
        "ald-master",
        [
            "Recipe workflow",
            "Precursor compatibility",
            "Material compatibility",
            "Rank precursor candidates",
            "Compatibility report",
        ],
    )
    if selected is None:
        return 0
    if selected == 0:
        return _interactive_recipe_mode(args)
    if selected == 1:
        return _interactive_compatibility_query(args, "precursor")
    if selected == 2:
        return _interactive_compatibility_query(args, "material")
    if selected == 3:
        return _interactive_candidates(args)
    snapshot = _build_compatibility_snapshot_from_args(args)
    _print_report(snapshot)
    return 0


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
        if args.command == "compatibility-build":
            return _dispatch_build(args)
        if args.command == "compatible":
            return _dispatch_compatible(args)
        if args.command == "candidates":
            return _dispatch_candidates(args)
        if args.command == "explain":
            return _dispatch_explain(args)
        if args.command == "compatibility-report":
            return _dispatch_report(args)
        return _interactive_main(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except ValueError as error:
        print(f"ald-master: error: {error}", file=sys.stderr)
        return 2


__all__ = sorted(
    name for name in globals() if not name.startswith("_") or name in {
        "_interactive_main",
        "_run_flag_mode",
        "_build_compatibility_snapshot_from_args",
        "_prompt_text",
    }
)
