"""Audit frozen material candidates against the full PubChemRDF formula mirror.

The audit streams every compound-to-molecular-formula shard and retains only CID
matches for formulas already present in the frozen COD candidate snapshot. It is
identity/provenance work only; it does not acquire process conditions or infer
compatibility evidence.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import ald_materials as materials
from tools import refresh_material_sources as refresh


DEFAULT_BASE_URL = "https://ftp.ncbi.nlm.nih.gov/pubchem/RDF/compound/general"
DEFAULT_RELEASE_DATE = "2026-07-25"
DEFAULT_SHARD_COUNT = 9
DEFAULT_COMPRESSED_BYTES = 803_480_392
AUDIT_SCHEMA = "ald-material-pubchem-rdf-audit/1"


def _load_candidate_formulas(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected an array or records array")
    formulas: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        formula = record.get("formula")
        if not isinstance(formula, str):
            continue
        try:
            reduced, elements = materials.reduce_formula(formula)
        except ValueError:
            continue
        if len(elements) >= 2:
            formulas.add(reduced)
    return sorted(formulas)


def _scan_shard(
    url: str,
    variants: dict[str, str],
    *,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": refresh.USER_AGENT, "Accept": "application/gzip"})
            with urlopen(request, timeout=timeout) as response:
                with gzip.GzipFile(fileobj=response, mode="rb") as stream:
                    return refresh.audit_pubchem_rdf_binary_lines(stream, variants)
        except (HTTPError, URLError, TimeoutError, OSError, EOFError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(2.0**attempt, 8.0))
    assert error is not None
    raise RuntimeError(f"unable to scan PubChemRDF shard {url}: {error}") from error


def audit_full_mirror(
    target_formulas: list[str],
    *,
    base_url: str = DEFAULT_BASE_URL,
    shard_count: int = DEFAULT_SHARD_COUNT,
    max_scale: int = 16,
    timeout: float = 180.0,
    retries: int = 3,
) -> dict[str, Any]:
    if type(shard_count) is not int or shard_count <= 0:
        raise ValueError("shard_count must be a positive integer")
    variants = refresh.build_pubchem_formula_variant_index(target_formulas, max_scale=max_scale)
    matched_sets: dict[str, set[str]] = {}
    formula_records_scanned = 0
    shard_rows: list[dict[str, Any]] = []
    for shard in range(1, shard_count + 1):
        name = f"pc_compound2molecular_formula_{shard:06d}.ttl.gz"
        url = f"{base_url.rstrip('/')}/{name}"
        result = _scan_shard(url, variants, timeout=timeout, retries=retries)
        scanned = int(result["formula_records_scanned"])
        formula_records_scanned += scanned
        shard_rows.append({"name": name, "formula_records_scanned": scanned})
        for formula, cids in result["matched"].items():
            matched_sets.setdefault(formula, set()).update(str(cid) for cid in cids)

    records: list[dict[str, Any]] = []
    for formula in sorted(matched_sets):
        cids = sorted(matched_sets[formula], key=lambda value: int(value))
        records.append({"reduced_formula": formula, "cid": cids[0], "cids": cids})
    return {
        "formula_records_scanned": formula_records_scanned,
        "matched_candidate_formula_count": len(records),
        "records": records,
        "shards": shard_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cod-source", type=Path, default=Path("materials/sources/cod-materials.json"))
    parser.add_argument("--output", type=Path, default=Path("materials/sources/pubchem-identities.json"))
    parser.add_argument("--requested-material-count", type=int, default=8000)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--release-date", default=DEFAULT_RELEASE_DATE)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--compressed-bytes", type=int, default=DEFAULT_COMPRESSED_BYTES)
    parser.add_argument("--max-scale", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args(argv)

    if args.requested_material_count <= 0:
        parser.error("--requested-material-count must be positive")
    candidates = _load_candidate_formulas(args.cod_source)
    result = audit_full_mirror(
        candidates,
        base_url=args.base_url,
        shard_count=args.shard_count,
        max_scale=args.max_scale,
        timeout=args.timeout,
        retries=args.retries,
    )
    payload = {
        "schema": AUDIT_SCHEMA,
        "audit_mode": "bulk-mirror",
        "mirror": "PubChemRDF",
        "mirror_release_date": args.release_date,
        "requested_material_count": args.requested_material_count,
        "audited_candidate_formula_count": len(candidates),
        "formula_records_scanned": result["formula_records_scanned"],
        "matched_candidate_formula_count": result["matched_candidate_formula_count"],
        "shard_count": args.shard_count,
        "compressed_bytes": args.compressed_bytes,
        "mirror_base_url": args.base_url,
        "max_formula_unit_scale": args.max_scale,
        "shards": result["shards"],
        "records": result["records"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(materials.canonical_json_bytes(payload))
    if result["matched_candidate_formula_count"] < args.requested_material_count:
        raise RuntimeError(
            f"PubChemRDF matched only {result['matched_candidate_formula_count']} candidate formulas; "
            f"need {args.requested_material_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
