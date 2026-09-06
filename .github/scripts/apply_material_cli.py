from pathlib import Path

path = Path("ald_master/__init__.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one patch target, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


replace_once(
    "import ald_compatibility as compatibility\n",
    "import ald_compatibility as compatibility\nimport ald_materials as material_catalog\n",
)
replace_once(
    'DEFAULT_COMPAT_SNAPSHOT = Path("build/compatibility/snapshot.json")\n',
    'DEFAULT_COMPAT_SNAPSHOT = Path("build/compatibility/snapshot.json")\nDEFAULT_MATERIAL_CATALOG = material_catalog.DEFAULT_MATERIAL_CATALOG\n',
)
replace_once(
    '''    parser.add_argument(
        "--compat-evidence",
        type=Path,
        default=DEFAULT_COMPAT_EVIDENCE,
        help="curated offline compatibility evidence overrides",
    )
    commands = _subparser_action(parser)
''',
    '''    parser.add_argument(
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
''',
)

insert_before = "\ndef _dispatch_compatible(args: argparse.Namespace) -> int:\n"
material_helpers = '''

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
'''
replace_once(insert_before, material_helpers + insert_before)

old_dispatch = '''def _dispatch_compatible(args: argparse.Namespace) -> int:
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
'''
new_dispatch = '''def _dispatch_compatible(args: argparse.Namespace) -> int:
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
'''
replace_once(old_dispatch, new_dispatch)

replace_once(
    '''        if args.command == "run":
            return _run_flag_mode(args)
        if args.command == "compatibility-build":
''',
    '''        if args.command == "run":
            return _run_flag_mode(args)
        if args.command == "materials":
            return _dispatch_materials(args)
        if args.command == "compatibility-build":
''',
)

path.write_text(text, encoding="utf-8")
