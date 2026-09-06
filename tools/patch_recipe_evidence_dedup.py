from pathlib import Path

path = Path("tools/refresh_recipe_evidence.py")
text = path.read_text(encoding="utf-8")
old = '''    in_universe: list[dict[str, object]] = []
    outside_material_catalog = 0
    for raw in source_records:
        normalized = evidence.validate_evidence_record(raw)
        reduced = str(normalized["target_reduced_formula"])
        material = material_by_formula.get(reduced)
        if material is None:
            outside_material_catalog += 1
            continue
        material_id = material.get("material_id")
        if isinstance(material_id, str) and material_id.strip():
            normalized["material_id"] = material_id.strip()
            normalized = evidence.validate_evidence_record(normalized)
        in_universe.append(normalized)

    selected_records = evidence.select_best_candidates(in_universe, existing_targets)
'''
new = '''    in_universe_by_id: dict[str, dict[str, object]] = {}
    in_universe_candidate_count = 0
    outside_material_catalog = 0
    for raw in source_records:
        normalized = evidence.validate_evidence_record(raw)
        reduced = str(normalized["target_reduced_formula"])
        material = material_by_formula.get(reduced)
        if material is None:
            outside_material_catalog += 1
            continue
        in_universe_candidate_count += 1
        material_id = material.get("material_id")
        if isinstance(material_id, str) and material_id.strip():
            normalized["material_id"] = material_id.strip()
            normalized = evidence.validate_evidence_record(normalized)
        record_id = str(normalized["evidence_id"])
        previous = in_universe_by_id.get(record_id)
        if previous is None or evidence.canonical_json_bytes(normalized) < evidence.canonical_json_bytes(previous):
            in_universe_by_id[record_id] = normalized

    in_universe = list(in_universe_by_id.values())
    duplicate_evidence_collapses = in_universe_candidate_count - len(in_universe)
    selected_records = evidence.select_best_candidates(in_universe, existing_targets)
'''
if text.count(old) != 1:
    raise SystemExit("expected one in-universe evidence collection block")
text = text.replace(old, new, 1)
old_counts = '''        "atomiclimits_candidates": len(source_records),
        "source_candidates_in_material_catalog": len(in_universe),
        "source_candidates_outside_material_catalog": outside_material_catalog,
'''
new_counts = '''        "atomiclimits_candidates": len(source_records),
        "source_candidates_in_material_catalog": in_universe_candidate_count,
        "unique_source_candidates_in_material_catalog": len(in_universe),
        "duplicate_evidence_collapses": duplicate_evidence_collapses,
        "source_candidates_outside_material_catalog": outside_material_catalog,
'''
if text.count(old_counts) != 1:
    raise SystemExit("expected one acquisition count block")
path.write_text(text.replace(old_counts, new_counts, 1), encoding="utf-8")
