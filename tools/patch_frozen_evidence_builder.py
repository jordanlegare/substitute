from pathlib import Path

path = Path("tools/refresh_recipe_evidence.py")
text = path.read_text(encoding="utf-8")
marker = "\ndef main(argv: list[str] | None = None) -> int:\n"
if text.count(marker) != 1:
    raise SystemExit("expected one main() marker")
addition = r'''

def _catalog_entries(catalog: Mapping[str, object], field: str) -> list[Mapping[str, object]]:
    raw = catalog.get("entries")
    if not isinstance(raw, list):
        raise ValueError(f"{field}.entries must be an array")
    result: list[Mapping[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"{field}.entries[{index}] must be an object")
        result.append(item)
    return result


def _fixed_reduced_formula(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        reduced, elements = materials.reduce_formula(value)
    except ValueError:
        return None
    return reduced if len(elements) >= 2 else None


def build_frozen_evidence(
    source_records: list[Mapping[str, object]],
    material_catalog: Mapping[str, object],
    recipe_catalog: Mapping[str, object],
    *,
    source_metadata: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Build canonical frozen evidence, source manifest, and coverage audit.

    Source records outside the fixed 8,000-material identity universe are
    counted in the acquisition audit but deliberately excluded from the
    canonical recipe-evidence ledger. Historical symbolic recipe targets are
    likewise preserved in the recipe catalog but excluded from fixed-formula
    collision accounting.
    """

    material_entries = _catalog_entries(material_catalog, "material_catalog")
    material_by_formula: dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(material_entries):
        reduced = _fixed_reduced_formula(
            entry.get("reduced_formula", entry.get("formula"))
        )
        if reduced is None:
            raise ValueError(
                f"material_catalog.entries[{index}] is missing a fixed non-elemental formula"
            )
        if reduced in material_by_formula:
            raise ValueError(f"duplicate material reduced formula: {reduced}")
        material_by_formula[reduced] = entry

    recipe_entries = _catalog_entries(recipe_catalog, "recipe_catalog")
    existing_targets: set[str] = set()
    for entry in recipe_entries:
        reduced = _fixed_reduced_formula(entry.get("target_formula"))
        if reduced is not None and reduced in material_by_formula:
            existing_targets.add(reduced)

    in_universe: list[dict[str, object]] = []
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
    selected_records.sort(
        key=lambda item: (
            str(item["target_reduced_formula"]),
            str(item["selection_status"]),
            str(item["evidence_id"]),
        )
    )
    evidence_doc: dict[str, object] = {
        "schema": evidence.EVIDENCE_SCHEMA,
        "records": selected_records,
    }

    evidence_digest = hashlib.sha256(evidence.canonical_json_bytes(evidence_doc)).hexdigest()
    metadata = {
        str(key): value
        for key, value in dict(source_metadata or {}).items()
        if value is not None
    }
    atomiclimits_source: dict[str, object] = {
        "database_doi": ATOMICLIMITS_DATABASE_DOI,
        "transport": "awases-ald-structured-export",
        "source_candidate_count": len(source_records),
    }
    atomiclimits_source.update(metadata)
    manifest: dict[str, object] = {
        "schema": "ald-recipe-evidence-manifest/1",
        "sources": {"atomiclimits": atomiclimits_source},
        "digests": {"process_evidence_sha256": evidence_digest},
    }

    status_counts: dict[str, int] = {}
    rejection_counts: dict[str, int] = {}
    process_additions: dict[str, int] = {}
    selected_targets: set[str] = set()
    r2_selected = 0
    r3_selected = 0
    r1_rejected = 0
    direct_publications: set[tuple[str, str]] = set()
    for record in selected_records:
        status = str(record["selection_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        reason = record.get("rejection_reason")
        if isinstance(reason, str) and reason:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        publications = record.get("publications", [])
        if isinstance(publications, list):
            for publication in publications:
                if isinstance(publication, Mapping) and publication.get("direct") is True:
                    direct_publications.add(
                        (str(publication.get("type", "")), str(publication.get("identifier", "")))
                    )
        if status == "selected":
            selected_targets.add(str(record["target_reduced_formula"]))
            family = str(record["process_family"])
            process_additions[family] = process_additions.get(family, 0) + 1
            if record["evidence_grade"] == "R3":
                r3_selected += 1
            elif record["evidence_grade"] == "R2":
                r2_selected += 1
        elif record["evidence_grade"] == "R1":
            r1_rejected += 1

    material_count = len(material_by_formula)
    existing_material_count = len(existing_targets)
    final_recipe_count = len(recipe_entries) + len(selected_targets)
    remaining_identity_only = max(
        0, material_count - len(existing_targets.union(selected_targets))
    )
    counts: dict[str, object] = {
        "material_identities_examined": material_count,
        "existing_recipe_backed_materials": existing_material_count,
        "remaining_identity_only_materials_before_refresh": max(
            0, material_count - existing_material_count
        ),
        "atomiclimits_candidates": len(source_records),
        "source_candidates_in_material_catalog": len(in_universe),
        "source_candidates_outside_material_catalog": outside_material_catalog,
        "direct_publication_records_resolved": len(direct_publications),
        "r3_selected": r3_selected,
        "r2_selected": r2_selected,
        "r1_rejected": r1_rejected,
        "new_distinct_materials_selected": len(selected_targets),
        "additions_by_process_family": dict(sorted(process_additions.items())),
        "final_executable_recipe_count": final_recipe_count,
        "remaining_identity_only_materials": remaining_identity_only,
        "evidence_status_counts": dict(sorted(status_counts.items())),
    }
    audit: dict[str, object] = {
        "schema": "ald-recipe-evidence-audit/1",
        "counts": counts,
        "rejections": dict(sorted(rejection_counts.items())),
    }
    return evidence_doc, manifest, audit
'''
path.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")
