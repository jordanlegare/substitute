"""Temporary one-shot patcher for the ald-master chemistry CLI facade."""

from __future__ import annotations

from pathlib import Path


PATH = Path("ald_master/__init__.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one patch marker, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "import ald_compatibility as compatibility\nimport ald_materials as material_catalog\n",
        "import ald_compatibility as compatibility\nimport ald_materials as material_catalog\nimport ald_chemistry as chemistry_catalog\n",
    )

    text = replace_once(
        text,
        'DEFAULT_MATERIAL_CATALOG = material_catalog.DEFAULT_MATERIAL_CATALOG\n',
        'DEFAULT_MATERIAL_CATALOG = material_catalog.DEFAULT_MATERIAL_CATALOG\nDEFAULT_RECIPE_EVIDENCE = chemistry_catalog.DEFAULT_RECIPE_EVIDENCE\n',
    )

    text = replace_once(
        text,
        '''    parser.add_argument(\n        "--materials-catalog",\n        type=Path,\n        default=DEFAULT_MATERIAL_CATALOG,\n        help="offline material identity catalog",\n    )\n    commands = _subparser_action(parser)\n''',
        '''    parser.add_argument(\n        "--materials-catalog",\n        type=Path,\n        default=DEFAULT_MATERIAL_CATALOG,\n        help="offline material identity catalog",\n    )\n    parser.add_argument(\n        "--recipe-evidence",\n        type=Path,\n        default=DEFAULT_RECIPE_EVIDENCE,\n        help="offline recipe chemistry evidence ledger",\n    )\n    commands = _subparser_action(parser)\n''',
    )

    text = replace_once(
        text,
        '''    material_report_parser = material_actions.add_parser("report")\n    _add_json_flag(material_report_parser)\n\n    build = commands.add_parser(\n''',
        '''    material_report_parser = material_actions.add_parser("report")\n    _add_json_flag(material_report_parser)\n\n    chemistry_command = commands.add_parser(\n        "chemistry", help="explore recipe chemistry and publication provenance"\n    )\n    chemistry_actions = chemistry_command.add_subparsers(\n        dest="chemistry_action", required=True\n    )\n\n    chemistry_search = chemistry_actions.add_parser("search")\n    chemistry_search.add_argument("text")\n    chemistry_search.add_argument("--limit", type=int, default=20)\n    _add_json_flag(chemistry_search)\n\n    chemistry_show = chemistry_actions.add_parser("show")\n    chemistry_show.add_argument("chemistry")\n    _add_json_flag(chemistry_show)\n\n    chemistry_list = chemistry_actions.add_parser("list")\n    chemistry_list.add_argument(\n        "--process-family", choices=("thermal-ald", "plasma-ald", "mld", "hybrid")\n    )\n    chemistry_list.add_argument("--chemistry-family")\n    chemistry_list.add_argument("--element")\n    chemistry_list.add_argument("--precursor")\n    chemistry_list.add_argument("--evidence", choices=("R2", "R3", "historical"))\n    chemistry_list.add_argument("--origin", choices=("historical", "expansion"))\n    chemistry_list.add_argument("--limit", type=int, default=50)\n    _add_json_flag(chemistry_list)\n\n    chemistry_sources = chemistry_actions.add_parser("sources")\n    chemistry_sources.add_argument("chemistry")\n    _add_json_flag(chemistry_sources)\n\n    chemistry_report_parser = chemistry_actions.add_parser("report")\n    _add_json_flag(chemistry_report_parser)\n\n    build = commands.add_parser(\n''',
    )

    text = replace_once(
        text,
        '''    if recipe_ids:\n        print(f"  executable recipes: {', '.join(str(value) for value in recipe_ids)}")\n\n\ndef _dispatch_materials(args: argparse.Namespace) -> int:\n''',
        '''    if recipe_ids:\n        print(f"  executable recipes: {', '.join(str(value) for value in recipe_ids)}")\n        first_recipe = str(recipe_ids[0])\n        print(f"  explore chemistry: ald-master chemistry show {first_recipe}")\n\n\ndef _load_chemistry_entries(args: argparse.Namespace) -> list[dict[str, Any]]:\n    return chemistry_catalog.load_chemistry_catalog(\n        Path(args.catalog),\n        Path(getattr(args, "recipe_evidence", DEFAULT_RECIPE_EVIDENCE)),\n        Path(getattr(args, "materials_catalog", DEFAULT_MATERIAL_CATALOG)),\n    )\n\n\ndef _chemistry_label(entry: dict[str, Any]) -> str:\n    formula = str(entry.get("target_formula", "")).strip()\n    name = str(entry.get("target_material", "")).strip()\n    recipe_id = str(entry.get("recipe_id", "")).strip()\n    target = f"{formula} ({name})" if formula and name and formula.casefold() != name.casefold() else formula or name\n    return f"{target} — {recipe_id}"\n\n\ndef _print_chemistry_list(entries: list[dict[str, Any]]) -> None:\n    if not entries:\n        print("No recipe chemistries match the requested query.")\n        return\n    for index, entry in enumerate(entries, start=1):\n        family = entry.get("process_family") or "unspecified"\n        print(\n            f"{index:>3}. {_chemistry_label(entry)}  "\n            f"[{entry.get('origin')}; {entry.get('evidence_grade')}; {family}]"\n        )\n\n\ndef _print_chemistry(entry: dict[str, Any]) -> None:\n    print(_chemistry_label(entry))\n    print(f"  chemistry id: {entry.get('chemistry_id')}")\n    print(f"  origin: {entry.get('origin')}")\n    print(f"  process family: {entry.get('process_family') or 'unspecified'}")\n    print(f"  chemistry family: {entry.get('chemistry_family')}")\n    print(f"  evidence: {entry.get('evidence_grade')}")\n    print(f"  recipe path: {entry.get('recipe_path')}")\n    print("  reactants:")\n    for reactant in entry.get("reactants", []):\n        if not isinstance(reactant, dict):\n            continue\n        label = reactant.get("label") or reactant.get("formula") or reactant.get("name")\n        role = reactant.get("role", "reactant")\n        name = reactant.get("name")\n        formula = reactant.get("formula")\n        details = []\n        if name and str(name) != str(label):\n            details.append(str(name))\n        if formula and str(formula) != str(label):\n            details.append(str(formula))\n        suffix = f" ({', '.join(details)})" if details else ""\n        print(f"    - {role}: {label}{suffix}")\n    sources = entry.get("sources", [])\n    if sources:\n        print("  sources:")\n        for source in sources:\n            if isinstance(source, dict):\n                print(f"    - {source.get('type', '?')}:{source.get('identifier', '?')}")\n    formula = str(entry.get("target_formula", "")).strip()\n    if formula:\n        print(f"  material: ald-master materials show {formula}")\n    print(\n        "  boundary: literature-recognition chemistry; simulator execution values "\n        "are synthetic and are not shown here"\n    )\n\n\ndef _dispatch_chemistry(args: argparse.Namespace) -> int:\n    entries = _load_chemistry_entries(args)\n    action = args.chemistry_action\n    if action == "search":\n        result = chemistry_catalog.search_chemistries(entries, args.text, limit=args.limit)\n        if args.json:\n            _json_print(result)\n        else:\n            _print_chemistry_list(result)\n        return 0 if result else 1\n    if action == "show":\n        result = chemistry_catalog.resolve_chemistries(entries, args.chemistry)\n        if args.json:\n            _json_print(result)\n        else:\n            for index, entry in enumerate(result):\n                if index:\n                    print()\n                _print_chemistry(entry)\n        return 0\n    if action == "list":\n        result = chemistry_catalog.filter_chemistries(\n            entries,\n            process_family=args.process_family,\n            chemistry_family=args.chemistry_family,\n            element=args.element,\n            precursor=args.precursor,\n            evidence=args.evidence,\n            origin=args.origin,\n            limit=args.limit,\n        )\n        if args.json:\n            _json_print(result)\n        else:\n            _print_chemistry_list(result)\n        return 0 if result else 1\n    if action == "sources":\n        result = chemistry_catalog.chemistry_sources(entries, args.chemistry)\n        if args.json:\n            _json_print(result)\n        else:\n            if not result:\n                print("No publication sources are recorded for this chemistry.")\n            for source in result:\n                text = f"{source.get('type', '?')}:{source.get('identifier', '?')}"\n                title = str(source.get("title", "")).strip()\n                year = source.get("year")\n                journal = str(source.get("journal", "")).strip()\n                detail = "; ".join(\n                    value for value in (title, str(year) if year else "", journal) if value\n                )\n                print(f"{text}{' — ' + detail if detail else ''}")\n        return 0\n    material_count = len(_load_material_entries(args))\n    result = chemistry_catalog.chemistry_report(entries, material_count=material_count)\n    if args.json:\n        _json_print(result)\n    else:\n        print("Recipe chemistry report")\n        print(f"  executable recipes: {result['total_executable_recipes']}")\n        print(f"  unique recipe-backed materials: {result['unique_recipe_backed_materials']}")\n        print(f"  historical recipes: {result['historical_recipe_count']}")\n        print(f"  expansion recipes: {result['expansion_recipe_count']}")\n        print(f"  process families: {result['process_families']}")\n        print(f"  evidence grades: {result['evidence_grades']}")\n        print(f"  remaining identity-only materials: {result['remaining_identity_only_materials']}")\n    return 0\n\n\ndef _dispatch_materials(args: argparse.Namespace) -> int:\n''',
    )

    text = replace_once(
        text,
        '''        if args.command == "materials":\n            return _dispatch_materials(args)\n        if args.command == "compatibility-build":\n''',
        '''        if args.command == "materials":\n            return _dispatch_materials(args)\n        if args.command == "chemistry":\n            return _dispatch_chemistry(args)\n        if args.command == "compatibility-build":\n''',
    )

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
