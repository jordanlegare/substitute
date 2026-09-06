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
import ald_materials as material_catalog
import ald_chemistry as chemistry_catalog


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
DEFAULT_MATERIAL_CATALOG = material_catalog.DEFAULT_MATERIAL_CATALOG
DEFAULT_RECIPE_EVIDENCE = chemistry_catalog.DEFAULT_RECIPE_EVIDENCE
EVIDENCE_LEVELS = (
    "E0_UNKNOWN",
    "E1_HEURISTIC",
    "E2_ANALOGUE",
    "E3_CORROBORATED",
    "E4_DIRECT",
)

_COMPAT_REFERENCE = r"""

Material identity catalog
-------------------------
Global input:
  --materials-catalog PATH  Offline identity catalog (default materials/catalog.json)

Commands:
  ald-master materials search TEXT [--limit N] [--json]
  ald-master materials show MATERIAL [--json]
  ald-master materials list [--class CLASS] [--element ELEMENT] [--limit N] [--json]
  ald-master materials report [--json]

Material identity is distinct from process/compatibility evidence. A catalog-only
material may be recognized while compatibility remains E0_UNKNOWN / UNKNOWN.

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
    parser.add_argument(
        "--materials-catalog",
        type=Path,
        default=DEFAULT_MATERIAL_CATALOG,
        help="offline material identity catalog",
    )
    parser.add_argument(
        "--recipe-evidence",
        type=Path,
        default=DEFAULT_RECIPE_EVIDENCE,
        help="offline recipe chemistry evidence ledger",
    )
    commands = _subparser_action(parser)

    materials_command = commands.add_parser(
        "materials", help="browse the provenance-backed material identity catalog"
    )
    material_actions = materials_command.add_subparsers(
        dest="material_action", required=True
    )
    material_search = material_actions.add_parser("search")
    material_search.add_argument("text")
    material_search.add_argument("--limit", type=int, default=20)
    _add_json_flag(material_search)

    material_show = material_actions.add_parser("show")
    material_show.add_argument("material")
    _add_json_flag(material_show)

    material_list = material_actions.add_parser("list")
    material_list.add_argument("--class", dest="material_class")
    material_list.add_argument("--element")
    material_list.add_argument("--limit", type=int, default=50)
    _add_json_flag(material_list)

    material_report_parser = material_actions.add_parser("report")
    _add_json_flag(material_report_parser)

    chemistry_command = commands.add_parser(
        "chemistry", help="explore recipe chemistry and publication provenance"
    )
    chemistry_actions = chemistry_command.add_subparsers(
        dest="chemistry_action", required=True
    )

    chemistry_search = chemistry_actions.add_parser("search")
    chemistry_search.add_argument("text")
    chemistry_search.add_argument("--limit", type=int, default=20)
    _add_json_flag(chemistry_search)

    chemistry_show = chemistry_actions.add_parser("show")
    chemistry_show.add_argument("chemistry")
    _add_json_flag(chemistry_show)

    chemistry_list = chemistry_actions.add_parser("list")
    chemistry_list.add_argument(
        "--process-family", choices=("thermal-ald", "plasma-ald", "mld", "hybrid")
    )
    chemistry_list.add_argument("--chemistry-family")
    chemistry_list.add_argument("--element")
    chemistry_list.add_argument("--precursor")
    chemistry_list.add_argument("--evidence", choices=("R2", "R3", "historical"))
    chemistry_list.add_argument("--origin", choices=("historical", "expansion"))
    chemistry_list.add_argument("--limit", type=int, default=50)
    _add_json_flag(chemistry_list)

    chemistry_sources = chemistry_actions.add_parser("sources")
    chemistry_sources.add_argument("chemistry")
    _add_json_flag(chemistry_sources)

    chemistry_report_parser = chemistry_actions.add_parser("report")
    _add_json_flag(chemistry_report_parser)

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



def _load_material_entries(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = Path(getattr(args, "materials_catalog", DEFAULT_MATERIAL_CATALOG))
    return material_catalog.load_material_catalog(path)


def _material_label(entry: dict[str, Any]) -> str:
    formula = str(entry.get("formula", "")).strip()
    name = str(entry.get("name", "")).strip()
    return f"{formula} ({name})" if formula and name and formula.casefold() != name.casefold() else formula or name


def _print_material_entries(entries: list[dict[str, Any]]) -> None:
    if not entries:
        print("No materials match the requested query.")
        return
    for index, entry in enumerate(entries, start=1):
        classes = ", ".join(str(value) for value in entry.get("material_classes", []))
        suffix = f"  [{classes}]" if classes else ""
        print(f"{index:>3}. {_material_label(entry)}{suffix}")


def _print_material(entry: dict[str, Any]) -> None:
    print(_material_label(entry))
    print(f"  id: {entry.get('material_id')}")
    print(f"  reduced formula: {entry.get('reduced_formula')}")
    print(f"  elements: {', '.join(str(value) for value in entry.get('elements', []))}")
    print(f"  classes: {', '.join(str(value) for value in entry.get('material_classes', []))}")
    print(f"  provenance records: {len(entry.get('provenance', []))}")
    process = entry.get("process_evidence", {})
    print(f"  process evidence: {process.get('status', 'identity-only')}")
    recipe_ids = process.get("recipe_ids", []) if isinstance(process, dict) else []
    if recipe_ids:
        print(f"  executable recipes: {', '.join(str(value) for value in recipe_ids)}")
        first_recipe = str(recipe_ids[0])
        print(f"  explore chemistry: ald-master chemistry show {first_recipe}")


def _load_chemistry_entries(args: argparse.Namespace) -> list[dict[str, Any]]:
    return chemistry_catalog.load_chemistry_catalog(
        Path(args.catalog),
        Path(getattr(args, "recipe_evidence", DEFAULT_RECIPE_EVIDENCE)),
        Path(getattr(args, "materials_catalog", DEFAULT_MATERIAL_CATALOG)),
    )


def _chemistry_label(entry: dict[str, Any]) -> str:
    formula = str(entry.get("target_formula", "")).strip()
    name = str(entry.get("target_material", "")).strip()
    recipe_id = str(entry.get("recipe_id", "")).strip()
    target = f"{formula} ({name})" if formula and name and formula.casefold() != name.casefold() else formula or name
    return f"{target} — {recipe_id}"


def _print_chemistry_list(entries: list[dict[str, Any]]) -> None:
    if not entries:
        print("No recipe chemistries match the requested query.")
        return
    for index, entry in enumerate(entries, start=1):
        family = entry.get("process_family") or "unspecified"
        print(
            f"{index:>3}. {_chemistry_label(entry)}  "
            f"[{entry.get('origin')}; {entry.get('evidence_grade')}; {family}]"
        )


def _print_chemistry(entry: dict[str, Any]) -> None:
    print(_chemistry_label(entry))
    print(f"  chemistry id: {entry.get('chemistry_id')}")
    print(f"  origin: {entry.get('origin')}")
    print(f"  process family: {entry.get('process_family') or 'unspecified'}")
    print(f"  chemistry family: {entry.get('chemistry_family')}")
    print(f"  evidence: {entry.get('evidence_grade')}")
    print(f"  recipe path: {entry.get('recipe_path')}")
    print("  reactants:")
    for reactant in entry.get("reactants", []):
        if not isinstance(reactant, dict):
            continue
        label = reactant.get("label") or reactant.get("formula") or reactant.get("name")
        role = reactant.get("role", "reactant")
        name = reactant.get("name")
        formula = reactant.get("formula")
        details = []
        if name and str(name) != str(label):
            details.append(str(name))
        if formula and str(formula) != str(label):
            details.append(str(formula))
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"    - {role}: {label}{suffix}")
    sources = entry.get("sources", [])
    if sources:
        print("  sources:")
        for source in sources:
            if isinstance(source, dict):
                print(f"    - {source.get('type', '?')}:{source.get('identifier', '?')}")
    formula = str(entry.get("target_formula", "")).strip()
    if formula:
        print(f"  material: ald-master materials show {formula}")
    print(
        "  boundary: literature-recognition chemistry for simulation only; "
        "simulator execution values are synthetic and are not shown here"
    )


def _dispatch_chemistry(args: argparse.Namespace) -> int:
    entries = _load_chemistry_entries(args)
    action = args.chemistry_action
    if action == "search":
        result = chemistry_catalog.search_chemistries(entries, args.text, limit=args.limit)
        if args.json:
            _json_print(result)
        else:
            _print_chemistry_list(result)
        return 0 if result else 1
    if action == "show":
        result = chemistry_catalog.resolve_chemistries(entries, args.chemistry)
        if args.json:
            _json_print(result)
        else:
            for index, entry in enumerate(result):
                if index:
                    print()
                _print_chemistry(entry)
        return 0
    if action == "list":
        result = chemistry_catalog.filter_chemistries(
            entries,
            process_family=args.process_family,
            chemistry_family=args.chemistry_family,
            element=args.element,
            precursor=args.precursor,
            evidence=args.evidence,
            origin=args.origin,
            limit=args.limit,
        )
        if args.json:
            _json_print(result)
        else:
            _print_chemistry_list(result)
        return 0 if result else 1
    if action == "sources":
        result = chemistry_catalog.chemistry_sources(entries, args.chemistry)
        if args.json:
            _json_print(result)
        else:
            if not result:
                print("No publication sources are recorded for this chemistry.")
            for source in result:
                text = f"{source.get('type', '?')}:{source.get('identifier', '?')}"
                title = str(source.get("title", "")).strip()
                year = source.get("year")
                journal = str(source.get("journal", "")).strip()
                detail = "; ".join(
                    value for value in (title, str(year) if year else "", journal) if value
                )
                print(f"{text}{' — ' + detail if detail else ''}")
        return 0
    material_entries = _load_material_entries(args)
    material_count = len(material_entries)
    material_summary = material_catalog.material_report(material_entries)
    result = chemistry_catalog.chemistry_report(
        entries,
        material_count=material_count,
        recipe_backed_material_count=int(material_summary["recipe_linked_materials"]),
    )
    if args.json:
        _json_print(result)
    else:
        print("Recipe chemistry report")
        print(f"  executable recipes: {result['total_executable_recipes']}")
        print(f"  unique recipe-backed materials: {result['unique_recipe_backed_materials']}")
        print(f"  historical recipes: {result['historical_recipe_count']}")
        print(f"  expansion recipes: {result['expansion_recipe_count']}")
        print(f"  process families: {result['process_families']}")
        print(f"  evidence grades: {result['evidence_grades']}")
        print(f"  remaining identity-only materials: {result['remaining_identity_only_materials']}")
    return 0


def _dispatch_materials(args: argparse.Namespace) -> int:
    entries = _load_material_entries(args)
    action = args.material_action
    if action == "search":
        result = material_catalog.search_materials(entries, args.text, limit=args.limit)
        if args.json:
            _json_print(result)
        else:
            _print_material_entries(result)
        return 0 if result else 1
    if action == "show":
        result = dict(material_catalog.resolve_material(entries, args.material))
        if args.json:
            _json_print(result)
        else:
            _print_material(result)
        return 0
    if action == "list":
        result = material_catalog.filter_materials(
            entries,
            material_class=args.material_class,
            element=args.element,
            limit=args.limit,
        )
        if args.json:
            _json_print(result)
        else:
            _print_material_entries(result)
        return 0 if result else 1
    result = material_catalog.material_report(entries)
    if args.json:
        _json_print(result)
    else:
        print("Material identity catalog report")
        print(f"  total records: {result['total_material_records']}")
        print(f"  counted non-elemental formulas: {result['counted_non_elemental_reduced_formula_count']}")
        print(f"  recipe-linked materials: {result['recipe_linked_materials']}")
        print(f"  PubChem enriched: {result['pubchem_enriched_materials']}")
        print(f"  classes: {result['material_classes']}")
    return 0


def _catalog_only_compatibility(args: argparse.Namespace) -> dict[str, Any]:
    entries = _load_material_entries(args)
    resolved = [
        dict(material_catalog.resolve_material(entries, query)) for query in args.entities
    ]
    result: dict[str, Any] = {
        "identity_known": True,
        "compatibility_evidence_available": False,
        "evidence_level": "E0_UNKNOWN",
        "verdict": "UNKNOWN",
        "coverage": 0.0,
        "reason": (
            "material identity is known in the material catalog, but no recipe-backed "
            "compatibility evidence node is available"
        ),
    }
    if len(resolved) == 1:
        result["material"] = resolved[0]
    else:
        result["materials"] = resolved
    return result

def _dispatch_compatible(args: argparse.Namespace) -> int:
    if not 1 <= len(args.entities) <= 2:
        raise ValueError("compatible queries accept one or two entities")
    snapshot = _build_compatibility_snapshot_from_args(args)
    query = compatibility.query_precursor if args.graph == "precursor" else compatibility.query_material
    try:
        result = query(
            snapshot,
            args.entities[0],
            args.entities[1] if len(args.entities) == 2 else None,
            top=args.top,
        )
    except ValueError:
        if args.graph != "material":
            raise
        result = _catalog_only_compatibility(args)
    if args.json:
        _json_print(result)
    elif isinstance(result, list):
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        _print_edge_list(result)
    elif result.get("compatibility_evidence_available") is False:
        print(snapshot.get("safety_notice", compatibility.SAFETY_NOTICE))
        known = result.get("material") or result.get("materials", [])
        if isinstance(known, dict):
            print(f"{_material_label(known)}: identity known; compatibility evidence unavailable (UNKNOWN)")
        else:
            print("Known material identities; compatibility evidence unavailable (UNKNOWN)")
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
    return 0


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
        if args.command == "materials":
            return _dispatch_materials(args)
        if args.command == "chemistry":
            return _dispatch_chemistry(args)
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
