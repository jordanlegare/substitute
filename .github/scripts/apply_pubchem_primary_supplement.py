from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


refresh = Path("tools/refresh_material_sources.py")
replace_once(
    refresh,
    '_PUBCHEM_RDF_BINARY_SEPARATOR = b"\\tvocab:molecular_formula\\t"\n',
    '_PUBCHEM_RDF_BINARY_SEPARATOR = b"\\tvocab:molecular_formula\\t"\n'
    '_PUBCHEM_PRIMARY_MATERIAL_FORMERS = frozenset(\n'
    '    "Li Be B Na Mg Al Si K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo "\n'
    '    "Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf "\n'
    '    "Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th Pa U Np Pu".split()\n'
    ')\n',
)
replace_once(
    refresh,
    'def audit_pubchem_rdf_binary_lines(\n'
    '    lines: Iterable[bytes], formula_variants: Mapping[str, str]\n'
    ') -> dict[str, Any]:\n'
    '    """Scan PubChemRDF formula triples without parsing every formula chemically."""\n'
    '    matched_sets: dict[str, set[str]] = {}\n'
    '    formula_records_scanned = 0\n'
    '    for line in lines:\n'
    '        if not line.startswith(b"compound:CID"):\n'
    '            continue\n'
    '        try:\n'
    '            subject, value = line.rstrip().split(_PUBCHEM_RDF_BINARY_SEPARATOR, 1)\n'
    '        except ValueError:\n'
    '            continue\n'
    '        if not subject.startswith(b"compound:CID"):\n'
    '            continue\n'
    '        formula_records_scanned += 1\n'
    '        first_quote = value.find(b\'"\')\n'
    '        last_quote = value.rfind(b\'"\')\n'
    '        if first_quote < 0 or last_quote <= first_quote:\n'
    '            continue\n'
    '        try:\n'
    '            cid = subject[len(b"compound:CID") :].decode("ascii")\n'
    '            formula = value[first_quote + 1 : last_quote].decode("ascii")\n'
    '        except UnicodeDecodeError:\n'
    '            continue\n'
    '        reduced = formula_variants.get(formula)\n'
    '        if reduced is not None:\n'
    '            matched_sets.setdefault(reduced, set()).add(cid)\n'
    '    return {\n'
    '        "formula_records_scanned": formula_records_scanned,\n'
    '        "matched": {\n'
    '            formula: sorted(cids, key=lambda value: int(value))\n'
    '            for formula, cids in sorted(matched_sets.items())\n'
    '        },\n'
    '    }\n',
    'def normalize_pubchem_primary_formula(formula: str) -> str | None:\n'
    '    """Return a conservative fixed-inorganic reduced formula for catalog supplementation."""\n'
    '    try:\n'
    '        reduced, elements = materials.reduce_formula(formula)\n'
    '        counts = materials.parse_formula(reduced)\n'
    '    except ValueError:\n'
    '        return None\n'
    '    present = set(elements)\n'
    '    if not 2 <= len(present) <= 4:\n'
    '        return None\n'
    '    if present.intersection({"C", "H"}):\n'
    '        return None\n'
    '    if not present.intersection(_PUBCHEM_PRIMARY_MATERIAL_FORMERS):\n'
    '        return None\n'
    '    if sum(counts.values()) > 12:\n'
    '        return None\n'
    '    return reduced\n\n\n'
    'def audit_pubchem_rdf_binary_lines(\n'
    '    lines: Iterable[bytes],\n'
    '    formula_variants: Mapping[str, str],\n'
    '    *,\n'
    '    supplemental_limit: int = 0,\n'
    ') -> dict[str, Any]:\n'
    '    """Scan PubChemRDF triples and optionally retain bounded inorganic supplements."""\n'
    '    if type(supplemental_limit) is not int or supplemental_limit < 0:\n'
    '        raise ValueError("supplemental_limit must be a non-negative integer")\n'
    '    matched_sets: dict[str, set[str]] = {}\n'
    '    supplemental_sets: dict[str, set[str]] = {}\n'
    '    target_reduced = set(formula_variants.values())\n'
    '    formula_records_scanned = 0\n'
    '    for line in lines:\n'
    '        if not line.startswith(b"compound:CID"):\n'
    '            continue\n'
    '        try:\n'
    '            subject, value = line.rstrip().split(_PUBCHEM_RDF_BINARY_SEPARATOR, 1)\n'
    '        except ValueError:\n'
    '            continue\n'
    '        if not subject.startswith(b"compound:CID"):\n'
    '            continue\n'
    '        formula_records_scanned += 1\n'
    '        first_quote = value.find(b\'"\')\n'
    '        last_quote = value.rfind(b\'"\')\n'
    '        if first_quote < 0 or last_quote <= first_quote:\n'
    '            continue\n'
    '        try:\n'
    '            cid = subject[len(b"compound:CID") :].decode("ascii")\n'
    '            formula = value[first_quote + 1 : last_quote].decode("ascii")\n'
    '        except UnicodeDecodeError:\n'
    '            continue\n'
    '        reduced = formula_variants.get(formula)\n'
    '        if reduced is not None:\n'
    '            matched_sets.setdefault(reduced, set()).add(cid)\n'
    '            continue\n'
    '        if supplemental_limit and len(supplemental_sets) < supplemental_limit:\n'
    '            supplemental = normalize_pubchem_primary_formula(formula)\n'
    '            if supplemental is not None and supplemental not in target_reduced:\n'
    '                supplemental_sets.setdefault(supplemental, set()).add(cid)\n'
    '    return {\n'
    '        "formula_records_scanned": formula_records_scanned,\n'
    '        "matched": {\n'
    '            formula: sorted(cids, key=lambda value: int(value))\n'
    '            for formula, cids in sorted(matched_sets.items())\n'
    '        },\n'
    '        "supplemental": {\n'
    '            formula: sorted(cids, key=lambda value: int(value))\n'
    '            for formula, cids in sorted(supplemental_sets.items())\n'
    '        },\n'
    '    }\n',
)


auditor = Path("tools/audit_pubchem_rdf.py")
replace_once(
    auditor,
    'The audit streams every compound-to-molecular-formula shard and retains only CID\n'
    'matches for formulas already present in the frozen COD candidate snapshot. It is\n'
    'identity/provenance work only; it does not acquire process conditions or infer\n'
    'compatibility evidence.\n',
    'The audit streams every compound-to-molecular-formula shard, retains exact CID\n'
    'matches for frozen COD candidates, and can collect a bounded set of conservative\n'
    'fixed-inorganic PubChem-primary identities to fill a catalog-count shortfall. It is\n'
    'identity/provenance work only; it does not acquire process conditions or infer\n'
    'compatibility evidence.\n',
)
replace_once(
    auditor,
    'def _scan_shard(\n'
    '    url: str,\n'
    '    variants: dict[str, str],\n'
    '    *,\n'
    '    timeout: float,\n'
    '    retries: int,\n'
    ') -> dict[str, Any]:',
    'def _scan_shard(\n'
    '    url: str,\n'
    '    variants: dict[str, str],\n'
    '    *,\n'
    '    supplemental_limit: int,\n'
    '    timeout: float,\n'
    '    retries: int,\n'
    ') -> dict[str, Any]:',
)
replace_once(
    auditor,
    '                    return refresh.audit_pubchem_rdf_binary_lines(stream, variants)\n',
    '                    return refresh.audit_pubchem_rdf_binary_lines(\n'
    '                        stream, variants, supplemental_limit=supplemental_limit\n'
    '                    )\n',
)
replace_once(
    auditor,
    '    max_scale: int = 16,\n'
    '    timeout: float = 180.0,\n'
    '    retries: int = 3,\n'
    ') -> dict[str, Any]:',
    '    max_scale: int = 16,\n'
    '    supplemental_limit: int = 0,\n'
    '    timeout: float = 180.0,\n'
    '    retries: int = 3,\n'
    ') -> dict[str, Any]:',
)
replace_once(
    auditor,
    '    if type(shard_count) is not int or shard_count <= 0:\n'
    '        raise ValueError("shard_count must be a positive integer")\n'
    '    variants = refresh.build_pubchem_formula_variant_index(target_formulas, max_scale=max_scale)\n'
    '    matched_sets: dict[str, set[str]] = {}\n'
    '    formula_records_scanned = 0\n'
    '    shard_rows: list[dict[str, Any]] = []\n',
    '    if type(shard_count) is not int or shard_count <= 0:\n'
    '        raise ValueError("shard_count must be a positive integer")\n'
    '    if type(supplemental_limit) is not int or supplemental_limit < 0:\n'
    '        raise ValueError("supplemental_limit must be a non-negative integer")\n'
    '    variants = refresh.build_pubchem_formula_variant_index(target_formulas, max_scale=max_scale)\n'
    '    target_reduced = set(variants.values())\n'
    '    matched_sets: dict[str, set[str]] = {}\n'
    '    supplemental_sets: dict[str, set[str]] = {}\n'
    '    formula_records_scanned = 0\n'
    '    shard_rows: list[dict[str, Any]] = []\n',
)
replace_once(
    auditor,
    '        result = _scan_shard(url, variants, timeout=timeout, retries=retries)\n'
    '        scanned = int(result["formula_records_scanned"])\n'
    '        formula_records_scanned += scanned\n'
    '        shard_rows.append({"name": name, "formula_records_scanned": scanned})\n'
    '        for formula, cids in result["matched"].items():\n'
    '            matched_sets.setdefault(formula, set()).update(str(cid) for cid in cids)\n\n'
    '    records: list[dict[str, Any]] = []\n'
    '    for formula in sorted(matched_sets):\n'
    '        cids = sorted(matched_sets[formula], key=lambda value: int(value))\n'
    '        records.append({"reduced_formula": formula, "cid": cids[0], "cids": cids})\n'
    '    return {\n'
    '        "formula_records_scanned": formula_records_scanned,\n'
    '        "matched_candidate_formula_count": len(records),\n'
    '        "records": records,\n'
    '        "shards": shard_rows,\n'
    '    }\n',
    '        remaining = max(0, supplemental_limit - len(supplemental_sets))\n'
    '        result = _scan_shard(\n'
    '            url, variants, supplemental_limit=remaining, timeout=timeout, retries=retries\n'
    '        )\n'
    '        scanned = int(result["formula_records_scanned"])\n'
    '        formula_records_scanned += scanned\n'
    '        shard_rows.append({"name": name, "formula_records_scanned": scanned})\n'
    '        for formula, cids in result["matched"].items():\n'
    '            matched_sets.setdefault(formula, set()).update(str(cid) for cid in cids)\n'
    '        for formula, cids in result.get("supplemental", {}).items():\n'
    '            if formula in target_reduced or formula in matched_sets:\n'
    '                continue\n'
    '            supplemental_sets.setdefault(formula, set()).update(str(cid) for cid in cids)\n\n'
    '    records: list[dict[str, Any]] = []\n'
    '    for formula in sorted(matched_sets):\n'
    '        cids = sorted(matched_sets[formula], key=lambda value: int(value))\n'
    '        records.append({\n'
    '            "reduced_formula": formula,\n'
    '            "cid": cids[0],\n'
    '            "cids": cids,\n'
    '            "identity_origin": "cod+pubchem",\n'
    '        })\n'
    '    for formula in sorted(supplemental_sets):\n'
    '        cids = sorted(supplemental_sets[formula], key=lambda value: int(value))\n'
    '        records.append({\n'
    '            "reduced_formula": formula,\n'
    '            "cid": cids[0],\n'
    '            "cids": cids,\n'
    '            "identity_origin": "pubchem-primary",\n'
    '        })\n'
    '    records.sort(key=lambda row: (str(row["reduced_formula"]), str(row["identity_origin"])))\n'
    '    return {\n'
    '        "formula_records_scanned": formula_records_scanned,\n'
    '        "matched_candidate_formula_count": len(matched_sets),\n'
    '        "supplemental_formula_count": len(supplemental_sets),\n'
    '        "eligible_formula_count": len(matched_sets) + len(supplemental_sets),\n'
    '        "records": records,\n'
    '        "shards": shard_rows,\n'
    '    }\n',
)
replace_once(
    auditor,
    '    parser.add_argument("--max-scale", type=int, default=16)\n',
    '    parser.add_argument("--max-scale", type=int, default=16)\n'
    '    parser.add_argument("--supplemental-limit", type=int, default=4000)\n',
)
replace_once(
    auditor,
    '        max_scale=args.max_scale,\n'
    '        timeout=args.timeout,\n',
    '        max_scale=args.max_scale,\n'
    '        supplemental_limit=args.supplemental_limit,\n'
    '        timeout=args.timeout,\n',
)
replace_once(
    auditor,
    '        "mirror": "PubChemRDF",\n'
    '        "mirror_release_date": args.release_date,\n',
    '        "mirror": "PubChemRDF",\n'
    '        "mirror_release_date": args.release_date,\n'
    '        "selection_mode": "cod-plus-pubchem-primary",\n',
)
replace_once(
    auditor,
    '        "matched_candidate_formula_count": result["matched_candidate_formula_count"],\n'
    '        "shard_count": args.shard_count,\n',
    '        "matched_candidate_formula_count": result["matched_candidate_formula_count"],\n'
    '        "supplemental_formula_count": result["supplemental_formula_count"],\n'
    '        "eligible_formula_count": result["eligible_formula_count"],\n'
    '        "supplemental_limit": args.supplemental_limit,\n'
    '        "supplemental_policy": "fixed formula; 2-4 elements; no C/H; material former required; <=12 reduced atoms",\n'
    '        "shard_count": args.shard_count,\n',
)
replace_once(
    auditor,
    '    if result["matched_candidate_formula_count"] < args.requested_material_count:\n'
    '        raise RuntimeError(\n'
    '            f"PubChemRDF matched only {result[\'matched_candidate_formula_count\']} candidate formulas; "\n'
    '            f"need {args.requested_material_count}"\n'
    '        )\n',
    '    if result["eligible_formula_count"] < args.requested_material_count:\n'
    '        raise RuntimeError(\n'
    '            f"PubChemRDF produced only {result[\'eligible_formula_count\']} eligible formulas "\n'
    '            f"({result[\'matched_candidate_formula_count\']} COD matches + "\n'
    '            f"{result[\'supplemental_formula_count\']} PubChem-primary); "\n'
    '            f"need {args.requested_material_count}"\n'
    '        )\n',
)


builder = Path("tools/build_material_catalog.py")
replace_once(
    builder,
    '    process = record.get("process_evidence", {})\n'
    '    recipe_backed = int(\n'
    '        isinstance(process, Mapping) and process.get("status") == "executable-recipe"\n'
    '    )\n',
    '    process = record.get("process_evidence", {})\n'
    '    recipe_backed = int(\n'
    '        isinstance(process, Mapping) and process.get("status") == "executable-recipe"\n'
    '    )\n'
    '    cod_backed = int(\n'
    '        isinstance(provenance, Sequence)\n'
    '        and any(\n'
    '            isinstance(item, Mapping) and str(item.get("source", "")).casefold() == "cod"\n'
    '            for item in provenance\n'
    '        )\n'
    '    )\n',
)
replace_once(
    builder,
    '        -recipe_backed,\n'
    '        class_priority,\n',
    '        -recipe_backed,\n'
    '        -cod_backed,\n'
    '        class_priority,\n',
)
replace_once(
    builder,
    '    require_pubchem_match: bool = False,\n'
    '    pubchem_audit_metadata: Mapping[str, Any] | None = None,\n',
    '    require_pubchem_match: bool = False,\n'
    '    include_pubchem_primary: bool = False,\n'
    '    pubchem_audit_metadata: Mapping[str, Any] | None = None,\n',
)
replace_once(
    builder,
    '    pubchem = _pubchem_index(pubchem_records)\n'
    '    recipe_index = _recipe_index(recipe_entries)\n',
    '    pubchem = _pubchem_index(pubchem_records)\n'
    '    if include_pubchem_primary:\n'
    '        for reduced in sorted(pubchem):\n'
    '            if reduced in groups:\n'
    '                continue\n'
    '            pubchem_record = pubchem[reduced]\n'
    '            if str(pubchem_record.get("identity_origin", "")) != "pubchem-primary":\n'
    '                continue\n'
    '            cid = str(pubchem_record.get("cid", "")).strip()\n'
    '            if not cid:\n'
    '                continue\n'
    '            groups[reduced] = [{\n'
    '                "source": "pubchem",\n'
    '                "source_id": cid,\n'
    '                "formula": reduced,\n'
    '                "name": str(\n'
    '                    pubchem_record.get("title")\n'
    '                    or pubchem_record.get("iupac_name")\n'
    '                    or reduced\n'
    '                ),\n'
    '            }]\n'
    '    recipe_index = _recipe_index(recipe_entries)\n',
)
replace_once(
    builder,
    '    pubchem_matched_count = sum(\n'
    '        1 for entry in selected if entry.get("pubchem_audit", {}).get("status") == "matched"\n'
    '    )\n',
    '    pubchem_matched_count = sum(\n'
    '        1 for entry in selected if entry.get("pubchem_audit", {}).get("status") == "matched"\n'
    '    )\n'
    '    cod_backed_selected_count = sum(\n'
    '        1\n'
    '        for entry in selected\n'
    '        if any(\n'
    '            isinstance(item, Mapping) and str(item.get("source", "")).casefold() == "cod"\n'
    '            for item in entry.get("provenance", [])\n'
    '        )\n'
    '    )\n'
    '    pubchem_primary_selected_count = len(selected) - cod_backed_selected_count\n',
)
replace_once(
    builder,
    '        "pubchem_candidate_match_count": pubchem_candidate_match_count,\n'
    '        "raw_candidate_count": raw_candidate_count,\n',
    '        "pubchem_candidate_match_count": pubchem_candidate_match_count,\n'
    '        "cod_backed_selected_count": cod_backed_selected_count,\n'
    '        "pubchem_primary_selected_count": pubchem_primary_selected_count,\n'
    '        "raw_candidate_count": raw_candidate_count,\n',
)
replace_once(
    builder,
    '        require_pubchem_match=pubchem_metadata.get("audit_mode") == "bulk-mirror",\n'
    '        pubchem_audit_metadata=pubchem_metadata,\n',
    '        require_pubchem_match=pubchem_metadata.get("audit_mode") == "bulk-mirror",\n'
    '        include_pubchem_primary=(\n'
    '            pubchem_metadata.get("selection_mode") == "cod-plus-pubchem-primary"\n'
    '        ),\n'
    '        pubchem_audit_metadata=pubchem_metadata,\n',
)

print("applied PubChem-primary supplement production patch")
