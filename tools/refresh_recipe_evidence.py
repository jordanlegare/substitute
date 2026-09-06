"""Refresh non-operational ALD/MLD chemistry evidence from public sources.

This is the only recipe-evidence component that is allowed to access the
network.  Canonical evidence stores target identity, exact reactant source
labels, process family, and publication provenance only; literature operating
conditions and full text are deliberately discarded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable, Mapping, TextIO
from urllib.parse import quote
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import ald_materials as materials
import ald_recipe_evidence as evidence


AWASES_REPOSITORY = "jd-coderepos/awases-ald"
AWASES_PATH = "step 1/data/2-filtered-data.csv"
ATOMICLIMITS_DATABASE_DOI = "10.6100/alddatabase"
CROSSREF_BASE = "https://api.crossref.org/works/"
OPENALEX_BASE = "https://api.openalex.org/works/"

_REACTANT_COLUMNS = (
    ("process_reactanta", "reactant-a"),
    ("process_reactantb", "reactant-b"),
    ("process_reactantc", "reactant-c"),
    ("process_reactantd", "reactant-d"),
)
_NON_CYCLIC_PHRASES = (
    "chemical vapor deposition",
    "chemical vapour deposition",
    "physical vapor deposition",
    "physical vapour deposition",
    "sputtering",
    "evaporation",
    "solution growth",
    "sol-gel",
)


def _fold_text(*values: object) -> str:
    return " ".join(
        str(value).casefold().replace("_", " ").replace("-", " ")
        for value in values
        if value not in (None, "")
    )


def classify_process_family(title: str, abstract: str, full_text: str) -> str | None:
    """Classify only explicit cyclic ALD/MLD process language.

    The source text is used transiently and is never returned by this function
    or persisted by :func:`parse_awases_rows`.
    """

    text = _fold_text(title, abstract, full_text)
    compact = " ".join(text.split())

    has_atomic_layer = "atomic layer deposition" in compact
    has_ald_token = any(
        token in compact.split()
        for token in ("ald", "peald")
    )
    has_molecular_layer = "molecular layer deposition" in compact
    has_mld_token = "mld" in compact.split()

    hybrid_markers = (
        "ald/mld",
        "mld/ald",
        "ald mld",
        "mld ald",
        "hybrid atomic layer",
        "hybrid molecular layer",
        "hybrid cyclic deposition",
    )
    raw_folded = " ".join(
        str(value).casefold() for value in (title, abstract, full_text) if value
    )
    if (has_atomic_layer or has_ald_token) and (has_molecular_layer or has_mld_token):
        return "hybrid"
    if any(marker in raw_folded for marker in hybrid_markers):
        return "hybrid"
    if has_molecular_layer or has_mld_token:
        return "mld"

    plasma_markers = (
        "plasma enhanced atomic layer deposition",
        "plasma assisted atomic layer deposition",
        "plasma atomic layer deposition",
        "peald",
    )
    if any(marker in compact for marker in plasma_markers):
        return "plasma-ald"

    if has_atomic_layer or has_ald_token:
        return "thermal-ald"

    if any(phrase in compact for phrase in _NON_CYCLIC_PHRASES):
        return None
    return None


def _flag(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def _atomiclimits_live_family(process: Mapping[str, object]) -> str:
    """Classify a reviewed AtomicLimits process without persisting notes.

    AtomicLimits is itself an ALD process index. Explicit plasma/MLD/hybrid
    markers override the thermal default; notes are transient classification
    input only and are never copied into evidence records.
    """

    reactant_text = _fold_text(
        process.get("process_reactantA"),
        process.get("process_reactantB"),
        process.get("process_reactantC"),
        process.get("process_reactantD"),
        process.get("process_note"),
    )
    compact = " ".join(reactant_text.split())
    if any(
        marker in compact
        for marker in (
            "ald/mld",
            "mld/ald",
            "ald mld",
            "mld ald",
            "hybrid molecular layer",
        )
    ):
        return "hybrid"
    if "molecular layer deposition" in compact or " mld " in f" {compact} ":
        return "mld"
    if any(marker in compact for marker in ("plasma", "peald", "radical")):
        return "plasma-ald"
    return "thermal-ald"


def parse_atomiclimits_api_payload(
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    """Normalize the public live AtomicLimits process API into evidence records.

    The endpoint returns process chemistry and linked references separately.
    This join keeps only fixed target formulas, exact reactant source labels,
    stable DOI references, review flags, and non-operational provenance.
    """

    if payload.get("success") is not True:
        raise ValueError("AtomicLimits API payload is not successful")
    raw_processes = payload.get("processes")
    raw_references = payload.get("references")
    if not isinstance(raw_processes, list) or not isinstance(raw_references, list):
        raise ValueError(
            "AtomicLimits API payload must contain process and reference arrays"
        )

    references_by_process: dict[str, list[dict[str, object]]] = {}
    for raw_reference in raw_references:
        if not isinstance(raw_reference, Mapping):
            continue
        process_id = str(raw_reference.get("process_id", "")).strip()
        reference_id = str(raw_reference.get("reference_id", "")).strip()
        doi_raw = str(raw_reference.get("reference_doi", "")).strip()
        if not process_id or not doi_raw:
            continue
        try:
            doi = evidence.normalize_doi(doi_raw)
        except ValueError:
            continue
        reference: dict[str, object] = {
            "type": "doi",
            "identifier": doi,
            "direct": True,
            "reviewed": _flag(raw_reference.get("reference_reviewed")),
        }
        if reference_id:
            reference["reference_id"] = reference_id
        references_by_process.setdefault(process_id, []).append(reference)

    records: list[dict[str, object]] = []
    for raw_process in raw_processes:
        if not isinstance(raw_process, Mapping):
            continue
        process_id = str(raw_process.get("process_id", "")).strip()
        target_formula = str(raw_process.get("process_material", "")).strip()
        if not process_id or not target_formula:
            continue
        try:
            target_reduced, target_elements = materials.reduce_formula(target_formula)
        except ValueError:
            continue
        if len(target_elements) < 2:
            continue

        reactants: list[dict[str, str]] = []
        for suffix, role in (
            ("A", "reactant-a"),
            ("B", "reactant-b"),
            ("C", "reactant-c"),
            ("D", "reactant-d"),
        ):
            label = str(raw_process.get(f"process_reactant{suffix}", "")).strip()
            if label:
                reactants.append({"label": label, "role": role})
        if not reactants:
            continue

        source_references = references_by_process.get(process_id, [])
        publications_by_doi: dict[str, dict[str, object]] = {}
        reference_ids: set[str] = set()
        any_reference_reviewed = False
        for source_reference in source_references:
            doi = str(source_reference["identifier"])
            publications_by_doi[doi] = {
                "type": "doi",
                "identifier": doi,
                "direct": True,
            }
            any_reference_reviewed = (
                any_reference_reviewed
                or source_reference.get("reviewed") is True
            )
            reference_id = source_reference.get("reference_id")
            if isinstance(reference_id, str) and reference_id:
                reference_ids.add(reference_id)
        if not publications_by_doi:
            continue

        process_reviewed = _flag(raw_process.get("process_reviewed"))
        raw_record: dict[str, object] = {
            "target_material": target_formula,
            "target_formula": target_formula,
            "process_family": _atomiclimits_live_family(raw_process),
            "reactants": reactants,
            "publications": [
                publications_by_doi[key] for key in sorted(publications_by_doi)
            ],
            "discovery_sources": ["atomiclimits"],
            "evidence_grade": (
                "R3" if process_reviewed and any_reference_reviewed else "R2"
            ),
            "selection_status": "candidate",
            "provenance": {
                "primary_process_index": "atomiclimits",
                "atomiclimits_database_doi": ATOMICLIMITS_DATABASE_DOI,
                "transport": "atomiclimits-live-api",
                "process_id": process_id,
                "process_reviewed": process_reviewed,
                "reference_ids": sorted(reference_ids),
                "reviewed_reference_present": any_reference_reviewed,
            },
        }
        normalized = evidence.validate_evidence_record(raw_record)
        if normalized["target_reduced_formula"] != target_reduced:
            raise ValueError("target formula normalization mismatch")
        records.append(normalized)

    records.sort(
        key=lambda item: (
            str(item["target_reduced_formula"]),
            str(item["evidence_id"]),
        )
    )
    return records


def _safe_source_provenance(row: Mapping[str, object]) -> dict[str, object]:
    """Return allow-listed provenance metadata only."""

    result: dict[str, object] = {
        "primary_process_index": "atomiclimits",
        "atomiclimits_database_doi": ATOMICLIMITS_DATABASE_DOI,
        "transport": "awases-ald-structured-export",
    }
    process_id = str(row.get("process_id", "")).strip()
    reference_id = str(row.get("reference_id", "")).strip()
    if process_id:
        result["process_id"] = process_id
    if reference_id:
        result["reference_id"] = reference_id
    result["process_reviewed"] = _flag(row.get("process_reviewed"))
    result["reference_reviewed"] = _flag(row.get("reference_reviewed"))
    return result


def parse_awases_rows(stream: TextIO) -> list[dict[str, object]]:
    """Normalize structured AtomicLimits-derived rows into evidence records.

    ``title``, ``abstract``, ``full_text``, ``process_note`` and all other
    non-allow-listed source columns are transient inputs only and never copied
    into returned records.
    """

    reader = csv.DictReader(stream)
    required = {
        "process_material",
        "process_reactanta",
        "reference_doi",
        "title",
        "abstract",
        "full_text",
    }
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        missing = sorted(required.difference(set(reader.fieldnames or [])))
        raise ValueError(f"AWASES source is missing required columns: {', '.join(missing)}")

    records: list[dict[str, object]] = []
    for row in reader:
        target_formula = str(row.get("process_material", "")).strip()
        if not target_formula:
            continue
        try:
            target_reduced, target_elements = materials.reduce_formula(target_formula)
        except ValueError:
            continue
        if len(target_elements) < 2:
            continue

        family = classify_process_family(
            str(row.get("title", "")),
            str(row.get("abstract", "")),
            str(row.get("full_text", "")),
        )
        if family is None:
            continue

        doi_raw = str(row.get("reference_doi", "")).strip()
        if not doi_raw:
            continue
        try:
            doi = evidence.normalize_doi(doi_raw)
        except ValueError:
            continue

        reactants: list[dict[str, str]] = []
        for column, role in _REACTANT_COLUMNS:
            label = str(row.get(column, "")).strip()
            if label:
                reactants.append({"label": label, "role": role})
        if not reactants:
            continue

        reviewed = _flag(row.get("process_reviewed")) and _flag(row.get("reference_reviewed"))
        raw_record: dict[str, object] = {
            "target_material": target_formula,
            "target_formula": target_formula,
            "process_family": family,
            "reactants": reactants,
            "publications": [
                {
                    "type": "doi",
                    "identifier": doi,
                    "direct": True,
                }
            ],
            "discovery_sources": ["atomiclimits"],
            "evidence_grade": "R3" if reviewed else "R2",
            "selection_status": "candidate",
            "provenance": _safe_source_provenance(row),
        }
        normalized = evidence.validate_evidence_record(raw_record)
        # Be explicit that the fixed formula used by validation is the source
        # selection key; this also catches accidental future parser drift.
        if normalized["target_reduced_formula"] != target_reduced:
            raise ValueError("target formula normalization mismatch")
        records.append(normalized)

    records.sort(
        key=lambda item: (
            str(item["target_reduced_formula"]),
            str(item["evidence_id"]),
        )
    )
    return records


def _first_text(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _crossref_year(message: Mapping[str, object]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        value = message.get(key)
        if not isinstance(value, Mapping):
            continue
        parts = value.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
            and type(parts[0][0]) is int
        ):
            return int(parts[0][0])
    return None


def normalize_crossref_work(payload: Mapping[str, object]) -> dict[str, object]:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Crossref payload is missing message object")
    doi = evidence.normalize_doi(str(message.get("DOI", "")))
    result: dict[str, object] = {"type": "doi", "identifier": doi}
    title = _first_text(message.get("title"))
    journal = _first_text(message.get("container-title"))
    year = _crossref_year(message)
    if title is not None:
        result["title"] = title
    if journal is not None:
        result["journal"] = journal
    if year is not None:
        result["year"] = year
    return result


def normalize_openalex_work(payload: Mapping[str, object]) -> dict[str, object]:
    doi_raw = payload.get("doi")
    if not isinstance(doi_raw, str) or not doi_raw.strip():
        raise ValueError("OpenAlex work is missing DOI")
    result: dict[str, object] = {
        "type": "doi",
        "identifier": evidence.normalize_doi(doi_raw),
    }
    title = _first_text(payload.get("title"))
    if title is not None:
        result["title"] = title
    location = payload.get("primary_location")
    if isinstance(location, Mapping):
        source = location.get("source")
        if isinstance(source, Mapping):
            journal = _first_text(source.get("display_name"))
            if journal is not None:
                result["journal"] = journal
    year = payload.get("publication_year")
    if type(year) is int:
        result["year"] = year
    openalex_id = payload.get("id")
    if isinstance(openalex_id, str) and openalex_id.strip():
        result["openalex_id"] = openalex_id.rstrip("/").rsplit("/", 1)[-1]
    return result


def cached_fetch_json(
    url: str,
    cache_dir: Path,
    fetcher: Callable[[str], bytes],
) -> object:
    """Fetch JSON once and replay byte-stable cached canonical JSON later."""

    if not isinstance(url, str) or not url:
        raise ValueError("URL must be non-empty")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json"
    cache_path = cache_dir / cache_name
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    payload = json.loads(fetcher(url).decode("utf-8-sig"))
    cache_path.write_bytes(evidence.canonical_json_bytes(payload))
    return payload


def fetch_url_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "substitute-recipe-evidence/1 (+https://github.com/jordanlegare/substitute)",
            "Accept": "application/json,text/csv;q=0.9,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def crossref_url(doi: str) -> str:
    return CROSSREF_BASE + quote(evidence.normalize_doi(doi), safe="")


def openalex_url(doi: str) -> str:
    return OPENALEX_BASE + quote("https://doi.org/" + evidence.normalize_doi(doi), safe="")


def resolve_publication(
    doi: str,
    cache_dir: Path,
    fetcher: Callable[[str], bytes] = fetch_url_bytes,
) -> dict[str, object]:
    """Resolve DOI metadata through Crossref, falling back to OpenAlex."""

    try:
        payload = cached_fetch_json(crossref_url(doi), cache_dir / "crossref", fetcher)
        if not isinstance(payload, Mapping):
            raise ValueError("Crossref response is not an object")
        return normalize_crossref_work(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        payload = cached_fetch_json(openalex_url(doi), cache_dir / "openalex", fetcher)
        if not isinstance(payload, Mapping):
            raise ValueError("OpenAlex response is not an object")
        return normalize_openalex_work(payload)



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
    historical_recipe_entries = [
        entry
        for entry in recipe_entries
        if entry.get("recipe_origin") != "evidence-expansion"
    ]
    existing_targets: set[str] = set()
    for entry in historical_recipe_entries:
        reduced = _fixed_reduced_formula(entry.get("target_formula"))
        if reduced is not None and reduced in material_by_formula:
            existing_targets.add(reduced)

    in_universe_by_id: dict[str, dict[str, object]] = {}
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
    final_recipe_count = len(historical_recipe_entries) + len(selected_targets)
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
        "source_candidates_in_material_catalog": in_universe_candidate_count,
        "unique_source_candidates_in_material_catalog": len(in_universe),
        "duplicate_evidence_collapses": duplicate_evidence_collapses,
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

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--awases-ref",
        required=True,
        help="pinned AWASES Git commit/tag used for the structured source export",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/recipe-evidence"))
    parser.add_argument(
        "--source-csv",
        type=Path,
        help="optional already-downloaded AWASES CSV; production artifact writing is handled by later audit/build stages",
    )
    args = parser.parse_args(argv)

    if args.source_csv is None:
        print(
            "refresh adapter ready: provide --source-csv for local normalization; "
            "bulk frozen-artifact acquisition is performed by the audited refresh workflow",
            file=sys.stderr,
        )
        return 0

    with args.source_csv.open(encoding="ISO-8859-1", newline="") as stream:
        records = parse_awases_rows(stream)
    print(json.dumps({"candidate_count": len(records), "awases_ref": args.awases_ref}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
