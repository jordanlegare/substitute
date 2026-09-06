"""Refresh normalized public material identity snapshots for Substitute.

This command is the only network-capable part of the material-catalog pipeline.
It writes normalized identity/provenance fields only; canonical runtime artifacts
are built separately by ``tools/build_material_catalog.py``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import ald_materials as materials


COD_SEARCH_URL = "https://www.crystallography.net/cod/result"
PUBCHEM_PUG_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
USER_AGENT = "Substitute-material-catalog/1"
_PUBCHEM_RDF_FORMULA_RE = re.compile(
    r'^compound:CID([0-9]+)\s+vocab:molecular_formula\s+"([^"]+)"\s+\.\s*$'
)
_PUBCHEM_RDF_BINARY_SEPARATOR = b"\tvocab:molecular_formula\t"
_PUBCHEM_PRIMARY_MATERIAL_FORMERS = frozenset(
    "Li Be B Na Mg Al Si K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo "
    "Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf "
    "Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th Pa U Np Pu".split()
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_cod_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    source_id = _text(_first(row, "file", "id", "cod_id"))
    formula = _text(_first(row, "formula", "chemical_formula", "formula_sum"))
    if source_id is None or formula is None:
        return None
    result: dict[str, Any] = {"source": "cod", "source_id": source_id, "formula": formula}
    name = _text(_first(row, "mineral", "name", "chemical_name", "title"))
    if name is not None:
        result["name"] = name
    space_group = _text(_first(row, "sg", "space_group", "sgHall", "spacegroup"))
    if space_group is not None:
        result["space_group"] = space_group
    doi = _text(_first(row, "doi", "DOI"))
    if doi is not None:
        result["doi"] = doi
    reference = _text(_first(row, "reference", "journal", "bibliography"))
    if reference is not None:
        result["reference"] = reference
    tags = row.get("tags") or row.get("material_classes")
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        classes = sorted({str(value).strip() for value in tags if str(value).strip()})
        if classes:
            result["material_classes"] = classes
    return result


def normalize_pubchem_payload(reduced_formula: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    table = payload.get("PropertyTable")
    if not isinstance(table, Mapping):
        return None
    properties = table.get("Properties")
    if not isinstance(properties, Sequence) or isinstance(properties, (str, bytes)):
        return None
    rows = [row for row in properties if isinstance(row, Mapping)]
    if len(rows) != 1:
        return None
    row = rows[0]
    formula = _text(row.get("MolecularFormula"))
    cid = _text(row.get("CID"))
    if formula is None or cid is None:
        return None
    try:
        normalized_formula, _ = materials.reduce_formula(formula)
        wanted_formula, _ = materials.reduce_formula(reduced_formula)
    except ValueError:
        return None
    if normalized_formula != wanted_formula:
        return None
    result: dict[str, Any] = {
        "reduced_formula": wanted_formula,
        "cid": cid,
        "molecular_formula": formula,
    }
    for source_key, output_key in (
        ("IUPACName", "iupac_name"),
        ("Title", "title"),
        ("InChI", "inchi"),
        ("InChIKey", "inchikey"),
    ):
        value = _text(row.get(source_key))
        if value is not None:
            result[output_key] = value
    return result


def parse_pubchem_rdf_formula_line(line: str) -> tuple[str, str] | None:
    """Parse one PubChemRDF compound-to-molecular-formula Turtle record."""
    match = _PUBCHEM_RDF_FORMULA_RE.match(line.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def audit_pubchem_rdf_lines(
    lines: Iterable[str], target_formulas: Sequence[str] | set[str]
) -> dict[str, Any]:
    """Audit an iterable of formula triples against reduced target formulas."""
    targets: set[str] = set()
    for formula in target_formulas:
        try:
            reduced, _ = materials.reduce_formula(formula)
        except ValueError:
            continue
        targets.add(reduced)

    matched_sets: dict[str, set[str]] = {}
    formula_records_scanned = 0
    unsupported_formula_records = 0
    for line in lines:
        parsed = parse_pubchem_rdf_formula_line(line)
        if parsed is None:
            continue
        formula_records_scanned += 1
        cid, formula = parsed
        try:
            reduced, _ = materials.reduce_formula(formula)
        except ValueError:
            unsupported_formula_records += 1
            continue
        if reduced in targets:
            matched_sets.setdefault(reduced, set()).add(cid)

    matched = {
        formula: sorted(cids, key=lambda value: int(value))
        for formula, cids in sorted(matched_sets.items())
    }
    return {
        "formula_records_scanned": formula_records_scanned,
        "unsupported_formula_records": unsupported_formula_records,
        "matched": matched,
    }


def build_pubchem_formula_variant_index(
    target_formulas: Sequence[str] | set[str], *, max_scale: int = 16
) -> dict[str, str]:
    """Map Hill-style formula-unit variants to Substitute reduced formulas."""
    if type(max_scale) is not int or max_scale <= 0:
        raise ValueError("max_scale must be a positive integer")
    result: dict[str, str] = {}
    for formula in target_formulas:
        try:
            reduced, _ = materials.reduce_formula(formula)
            counts = materials.parse_formula(reduced)
        except ValueError:
            continue
        if "C" in counts:
            order = ["C"]
            if "H" in counts:
                order.append("H")
            order.extend(sorted(element for element in counts if element not in {"C", "H"}))
        else:
            order = sorted(counts)
        for scale in range(1, max_scale + 1):
            raw = "".join(
                element + (str(counts[element] * scale) if counts[element] * scale != 1 else "")
                for element in order
            )
            current = result.get(raw)
            if current is None or reduced < current:
                result[raw] = reduced
    return result


def normalize_pubchem_primary_formula(formula: str) -> str | None:
    """Return a conservative fixed-inorganic reduced formula for catalog supplementation."""
    try:
        reduced, elements = materials.reduce_formula(formula)
        counts = materials.parse_formula(reduced)
    except ValueError:
        return None
    present = set(elements)
    if not 2 <= len(present) <= 4:
        return None
    if present.intersection({"C", "H"}):
        return None
    if not present.intersection(_PUBCHEM_PRIMARY_MATERIAL_FORMERS):
        return None
    if sum(counts.values()) > 12:
        return None
    return reduced


def audit_pubchem_rdf_binary_lines(
    lines: Iterable[bytes],
    formula_variants: Mapping[str, str],
    *,
    supplemental_limit: int = 0,
) -> dict[str, Any]:
    """Scan PubChemRDF triples and optionally retain bounded inorganic supplements."""
    if type(supplemental_limit) is not int or supplemental_limit < 0:
        raise ValueError("supplemental_limit must be a non-negative integer")
    matched_sets: dict[str, set[str]] = {}
    supplemental_sets: dict[str, set[str]] = {}
    target_reduced = set(formula_variants.values())
    formula_records_scanned = 0
    for line in lines:
        if not line.startswith(b"compound:CID"):
            continue
        try:
            subject, value = line.rstrip().split(_PUBCHEM_RDF_BINARY_SEPARATOR, 1)
        except ValueError:
            continue
        if not subject.startswith(b"compound:CID"):
            continue
        formula_records_scanned += 1
        first_quote = value.find(b'"')
        last_quote = value.rfind(b'"')
        if first_quote < 0 or last_quote <= first_quote:
            continue
        try:
            cid = subject[len(b"compound:CID") :].decode("ascii")
            formula = value[first_quote + 1 : last_quote].decode("ascii")
        except UnicodeDecodeError:
            continue
        reduced = formula_variants.get(formula)
        if reduced is not None:
            matched_sets.setdefault(reduced, set()).add(cid)
            continue
        if supplemental_limit and len(supplemental_sets) < supplemental_limit:
            supplemental = normalize_pubchem_primary_formula(formula)
            if supplemental is not None and supplemental not in target_reduced:
                supplemental_sets.setdefault(supplemental, set()).add(cid)
    return {
        "formula_records_scanned": formula_records_scanned,
        "matched": {
            formula: sorted(cids, key=lambda value: int(value))
            for formula, cids in sorted(matched_sets.items())
        },
        "supplemental": {
            formula: sorted(cids, key=lambda value: int(value))
            for formula, cids in sorted(supplemental_sets.items())
        },
    }


def _load_or_fetch_json(url: str, *, cache_path: Path | None, timeout: float, retries: int) -> Any:
    if cache_path is not None and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            return payload
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(2.0**attempt, 8.0))
    assert error is not None
    raise RuntimeError(f"unable to retrieve {url}: {error}") from error


def refresh_cod(*, query: Mapping[str, str] | None = None, cache_path: Path | None = None, timeout: float = 30.0, retries: int = 3) -> list[dict[str, Any]]:
    params = dict(query or {})
    params["format"] = "json"
    url = f"{COD_SEARCH_URL}?{urlencode(sorted(params.items()))}"
    payload = _load_or_fetch_json(url, cache_path=cache_path, timeout=timeout, retries=retries)
    if isinstance(payload, Mapping):
        rows = payload.get("records") or payload.get("data") or payload.get("results")
    else:
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("COD response does not contain a record array")
    normalized = [normalize_cod_row(row) for row in rows if isinstance(row, Mapping)]
    return sorted([row for row in normalized if row is not None], key=lambda row: (row["source_id"], row["formula"]))


def refresh_pubchem(formulas: Sequence[str], *, cache_dir: Path | None = None, timeout: float = 30.0, retries: int = 3, minimum_interval: float = 0.25) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    unique: dict[str, str] = {}
    for formula in formulas:
        try:
            reduced, _ = materials.reduce_formula(formula)
        except ValueError:
            continue
        unique.setdefault(reduced, formula)
    for index, reduced in enumerate(sorted(unique)):
        encoded = quote(unique[reduced], safe="")
        props = "MolecularFormula,IUPACName,Title,InChI,InChIKey"
        url = f"{PUBCHEM_PUG_URL}/compound/formula/{encoded}/property/{props}/JSON"
        cache_path = cache_dir / f"{materials.material_id(reduced)}.json" if cache_dir else None
        try:
            payload = _load_or_fetch_json(url, cache_path=cache_path, timeout=timeout, retries=retries)
        except RuntimeError:
            payload = None
        if isinstance(payload, Mapping):
            normalized = normalize_pubchem_payload(reduced, payload)
            if normalized is not None:
                result.append(normalized)
        if index + 1 < len(unique) and minimum_interval > 0:
            time.sleep(minimum_interval)
    return sorted(result, key=lambda row: (row["reduced_formula"], row["cid"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cod-output", type=Path, required=True)
    parser.add_argument("--pubchem-output", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--cod-query", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--pubchem", action="store_true", help="enrich COD formulas with PubChem")
    args = parser.parse_args(argv)
    query: dict[str, str] = {}
    for item in args.cod_query:
        if "=" not in item:
            parser.error("--cod-query must use KEY=VALUE")
        key, value = item.split("=", 1)
        if not key or not value:
            parser.error("--cod-query must use non-empty KEY=VALUE")
        query[key] = value
    cod_cache = args.cache_dir / "cod.json" if args.cache_dir else None
    cod_rows = refresh_cod(query=query, cache_path=cod_cache)
    args.cod_output.parent.mkdir(parents=True, exist_ok=True)
    args.cod_output.write_bytes(materials.canonical_json_bytes({"records": cod_rows}))
    if args.pubchem:
        if args.pubchem_output is None:
            parser.error("--pubchem-output is required with --pubchem")
        pubchem_cache = args.cache_dir / "pubchem" if args.cache_dir else None
        enriched = refresh_pubchem([row["formula"] for row in cod_rows], cache_dir=pubchem_cache)
        args.pubchem_output.parent.mkdir(parents=True, exist_ok=True)
        args.pubchem_output.write_bytes(materials.canonical_json_bytes({"records": enriched}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
