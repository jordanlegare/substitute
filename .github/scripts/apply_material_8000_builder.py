from pathlib import Path

path = Path("tools/build_material_catalog.py")
text = path.read_text(encoding="utf-8")

old = '''def _merged_record(
    reduced_formula: str,
    elements: tuple[str, ...],
    source_records: Sequence[Mapping[str, Any]],
    pubchem: Mapping[str, Any] | None,
) -> dict[str, Any]:
'''
new = '''def _merged_record(
    reduced_formula: str,
    elements: tuple[str, ...],
    source_records: Sequence[Mapping[str, Any]],
    pubchem: Mapping[str, Any] | None,
    pubchem_audit_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    if pubchem is not None:
        for source_key, output_key in (
            ("cid", "pubchem_cid"),
            ("inchi", "inchi"),
            ("inchikey", "inchikey"),
        ):
            value = pubchem.get(source_key)
            if value not in (None, ""):
                identifiers[output_key] = str(value)
'''
new = '''    pubchem_audit: dict[str, Any] | None = None
    if pubchem is not None:
        cids_raw = pubchem.get("cids", [])
        cids = {
            str(value).strip()
            for value in cids_raw
            if str(value).strip()
        } if isinstance(cids_raw, Sequence) and not isinstance(cids_raw, (str, bytes)) else set()
        cid = pubchem.get("cid")
        if cid not in (None, ""):
            cids.add(str(cid).strip())
        ordered_cids = sorted(cids, key=lambda value: (int(value) if value.isdigit() else 10**30, value))
        if ordered_cids:
            identifiers["pubchem_cid"] = ordered_cids[0]
        for source_key, output_key in (("inchi", "inchi"), ("inchikey", "inchikey")):
            value = pubchem.get(source_key)
            if value not in (None, ""):
                identifiers[output_key] = str(value)
        metadata = dict(pubchem_audit_metadata or {})
        if ordered_cids and metadata.get("mirror") and metadata.get("mirror_release_date"):
            pubchem_audit = {
                "status": "matched",
                "mirror": str(metadata["mirror"]),
                "release_date": str(metadata["mirror_release_date"]),
                "cids": ordered_cids,
            }
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    return {
        "material_id": materials.material_id(reduced_formula),
        "name": name,
        "formula": reduced_formula,
        "reduced_formula": reduced_formula,
        "elements": list(elements),
        "counted": True,
        "material_classes": sorted(classes),
        "aliases": aliases,
        "identifiers": identifiers,
        "phases": phases,
        "provenance": provenance,
        "process_evidence": {
            "status": "identity-only",
            "recipe_ids": [],
            "recipe_paths": [],
        },
    }
'''
new = '''    result = {
        "material_id": materials.material_id(reduced_formula),
        "name": name,
        "formula": reduced_formula,
        "reduced_formula": reduced_formula,
        "elements": list(elements),
        "counted": True,
        "material_classes": sorted(classes),
        "aliases": aliases,
        "identifiers": identifiers,
        "phases": phases,
        "provenance": provenance,
        "process_evidence": {
            "status": "identity-only",
            "recipe_ids": [],
            "recipe_paths": [],
        },
    }
    if pubchem_audit is not None:
        result["pubchem_audit"] = pubchem_audit
    return result
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    *,
    target_count: int = 1000,
    manifest_template: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
'''
new = '''    *,
    target_count: int = 1000,
    manifest_template: Mapping[str, Any] | None = None,
    require_pubchem_match: bool = False,
    pubchem_audit_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    for reduced in sorted(groups):
        _, elements = materials.reduce_formula(reduced)
        record = _merged_record(reduced, elements, groups[reduced], pubchem.get(reduced))
        links = recipe_index.get(reduced, [])
'''
new = '''    for reduced in sorted(groups):
        _, elements = materials.reduce_formula(reduced)
        pubchem_record = pubchem.get(reduced)
        if require_pubchem_match and pubchem_record is None:
            continue
        record = _merged_record(
            reduced,
            elements,
            groups[reduced],
            pubchem_record,
            pubchem_audit_metadata,
        )
        links = recipe_index.get(reduced, [])
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    manifest.update(template)
    classes = Counter(
'''
new = '''    manifest.update(template)
    if pubchem_audit_metadata:
        source_metadata = dict(manifest.get("source_metadata", {}))
        source_metadata["pubchem"] = {
            key: value
            for key, value in dict(pubchem_audit_metadata).items()
            if key not in {"records"}
        }
        manifest["source_metadata"] = source_metadata
    classes = Counter(
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "raw_candidate_count": raw_candidate_count,
'''
new = '''    pubchem_candidate_match_count = sum(
        1 for entry in candidates if entry.get("pubchem_audit", {}).get("status") == "matched"
    )
    pubchem_matched_count = sum(
        1 for entry in selected if entry.get("pubchem_audit", {}).get("status") == "matched"
    )
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "target_count": target_count,
        "selected_count": len(selected),
        "pubchem_matched_count": pubchem_matched_count,
        "pubchem_candidate_match_count": pubchem_candidate_match_count,
        "raw_candidate_count": raw_candidate_count,
'''
assert old in text
text = text.replace(old, new, 1)

old = '''def _read_recipe_entries(path: Path) -> list[dict[str, Any]]:
'''
new = '''def _read_pubchem_snapshot(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        return [], {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        if not all(isinstance(record, dict) for record in payload):
            raise ValueError(f"{path}: every PubChem record must be an object")
        return [dict(record) for record in payload], {}
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{path}: expected an array or records array")
    records = payload["records"]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path}: every PubChem record must be an object")
    metadata = {key: value for key, value in payload.items() if key != "records"}
    return [dict(record) for record in records], metadata


def _read_recipe_entries(path: Path) -> list[dict[str, Any]]:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    source_records = _read_json_array(COD_SOURCE_PATH)
    pubchem_records = _read_json_array(PUBCHEM_SOURCE_PATH) if PUBCHEM_SOURCE_PATH.exists() else []
    recipe_entries = _read_recipe_entries(RECIPE_CATALOG_PATH)
'''
new = '''    source_records = _read_json_array(COD_SOURCE_PATH)
    pubchem_records, pubchem_metadata = _read_pubchem_snapshot(PUBCHEM_SOURCE_PATH)
    recipe_entries = _read_recipe_entries(RECIPE_CATALOG_PATH)
'''
assert old in text
text = text.replace(old, new, 1)

old = '''        target_count=args.target_count,
        manifest_template=template,
    )
'''
new = '''        target_count=args.target_count,
        manifest_template=template,
        require_pubchem_match=pubchem_metadata.get("audit_mode") == "bulk-mirror",
        pubchem_audit_metadata=pubchem_metadata,
    )
'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
