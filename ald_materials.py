"""Offline material identity helpers for Substitute's provenance catalog."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


CATALOG_SCHEMA = "ald-material-catalog/1"
DEFAULT_MATERIAL_CATALOG = Path("materials/catalog.json")

_ELEMENT_SYMBOLS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
    "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
    "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc "
    "Lv Ts Og".split()
)
_TOKEN_RE = re.compile(r"[A-Z][a-z]?|[0-9]+|[()]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _tokenize_formula(value: str) -> list[str]:
    if type(value) is not str or not value:
        raise ValueError("formula must be a non-empty string")
    if any(ch.isspace() for ch in value):
        value = "".join(value.split())
    if not value:
        raise ValueError("formula must be a non-empty string")
    tokens = _TOKEN_RE.findall(value)
    if "".join(tokens) != value:
        raise ValueError(f"unsupported or ambiguous formula: {value}")
    return tokens


def parse_formula(value: str) -> dict[str, int]:
    """Parse a fixed-stoichiometry formula into integer element counts."""
    tokens = _tokenize_formula(value)
    stack: list[dict[str, int]] = [{}]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "(":
            stack.append({})
            index += 1
            continue
        if token == ")":
            if len(stack) == 1:
                raise ValueError("unmatched closing parenthesis")
            group = stack.pop()
            if not group:
                raise ValueError("empty parenthetical group")
            multiplier = 1
            if index + 1 < len(tokens) and tokens[index + 1].isdigit():
                multiplier = int(tokens[index + 1])
                if multiplier <= 0:
                    raise ValueError("formula counts must be positive")
                index += 1
            target = stack[-1]
            for element, count in group.items():
                target[element] = target.get(element, 0) + count * multiplier
            index += 1
            continue
        if token.isdigit():
            raise ValueError("formula multiplier must follow an element or group")
        if token not in _ELEMENT_SYMBOLS:
            raise ValueError(f"unknown element symbol: {token}")
        count = 1
        if index + 1 < len(tokens) and tokens[index + 1].isdigit():
            count = int(tokens[index + 1])
            if count <= 0:
                raise ValueError("formula counts must be positive")
            index += 1
        current = stack[-1]
        current[token] = current.get(token, 0) + count
        index += 1
    if len(stack) != 1:
        raise ValueError("unmatched opening parenthesis")
    if not stack[0]:
        raise ValueError("formula contains no elements")
    return dict(sorted(stack[0].items()))


def reduce_formula(value: str) -> tuple[str, tuple[str, ...]]:
    counts = parse_formula(value)
    divisor = math.gcd(*counts.values())
    reduced = {element: count // divisor for element, count in counts.items()}
    elements = tuple(sorted(reduced))
    canonical = "".join(
        element + (str(reduced[element]) if reduced[element] != 1 else "")
        for element in elements
    )
    return canonical, elements


def material_id(reduced_formula: str) -> str:
    canonical, _ = reduce_formula(reduced_formula)
    slug = _SLUG_RE.sub("-", canonical.casefold()).strip("-") or "material"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    return f"mat-{slug}-{digest}"


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def load_material_catalog(path: Path | str = DEFAULT_MATERIAL_CATALOG) -> list[dict[str, Any]]:
    catalog_path = Path(path)
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"unable to read material catalog {catalog_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"material catalog is not valid JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("catalog_schema") != CATALOG_SCHEMA:
        raise ValueError(f"material catalog must use schema {CATALOG_SCHEMA}")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("material catalog must contain an entries array")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ValueError(f"material catalog entry {index} is not an object")
        for key in ("material_id", "name", "formula", "reduced_formula", "elements", "material_classes", "provenance"):
            if key not in raw:
                raise ValueError(f"material catalog entry {index} is missing {key}")
        entry_id = raw["material_id"]
        if type(entry_id) is not str or not entry_id or entry_id in seen_ids:
            raise ValueError(f"invalid or duplicate material_id at entry {index}")
        seen_ids.add(entry_id)
        entries.append(dict(raw))
    return entries


def _material_tokens(entry: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("material_id", "name", "formula", "reduced_formula"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    for key in ("aliases", "elements", "material_classes"):
        value = entry.get(key, [])
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values.extend(str(item) for item in value)
    identifiers = entry.get("identifiers", {})
    if isinstance(identifiers, Mapping):
        for value in identifiers.values():
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                values.extend(str(item) for item in value)
            elif value is not None:
                values.append(str(value))
    return values


def resolve_material(entries: Sequence[Mapping[str, Any]], query: str) -> Mapping[str, Any]:
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("material query must not be empty")
    matches: list[Mapping[str, Any]] = []
    for entry in entries:
        tokens = {token.casefold() for token in _material_tokens(entry)}
        if needle in tokens:
            matches.append(entry)
    if not matches:
        raise ValueError(f"unknown material: {query}")
    if len(matches) > 1:
        labels = sorted(str(item.get("formula") or item.get("name")) for item in matches)
        raise ValueError(f"ambiguous material {query!r}: {', '.join(labels)}")
    return matches[0]


def search_materials(
    entries: Sequence[Mapping[str, Any]], query: str, limit: int = 20
) -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    if not needle or limit <= 0:
        return []
    ranked: list[tuple[tuple[int, str, str], dict[str, Any]]] = []
    for original in entries:
        entry = dict(original)
        direct = [
            str(entry.get("material_id", "")),
            str(entry.get("formula", "")),
            str(entry.get("reduced_formula", "")),
        ]
        name = str(entry.get("name", ""))
        tokens = _material_tokens(entry)
        folded = [token.casefold() for token in tokens]
        if needle in {value.casefold() for value in direct if value}:
            rank = 0
        elif needle == name.casefold():
            rank = 1
        elif any(value.startswith(needle) for value in folded):
            rank = 2
        elif any(needle in value for value in folded):
            rank = 3
        else:
            continue
        key = (rank, str(entry.get("reduced_formula", "")), str(entry.get("material_id", "")))
        ranked.append((key, entry))
    ranked.sort(key=lambda item: item[0])
    return [entry for _, entry in ranked[:limit]]


def filter_materials(
    entries: Sequence[Mapping[str, Any]],
    *,
    material_class: str | None = None,
    element: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    class_needle = material_class.casefold() if material_class else None
    element_needle = element.casefold() if element else None
    result: list[dict[str, Any]] = []
    for original in entries:
        entry = dict(original)
        classes = {str(value).casefold() for value in entry.get("material_classes", [])}
        elements = {str(value).casefold() for value in entry.get("elements", [])}
        if class_needle is not None and class_needle not in classes:
            continue
        if element_needle is not None and element_needle not in elements:
            continue
        result.append(entry)
    result.sort(key=lambda item: (str(item.get("reduced_formula", "")), str(item.get("material_id", ""))))
    return result[:limit]


def material_report(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    class_counts: Counter[str] = Counter()
    counted = 0
    supplemental = 0
    recipe_linked = 0
    pubchem_enriched = 0
    for entry in entries:
        if entry.get("counted") is True:
            counted += 1
        else:
            supplemental += 1
        class_counts.update(str(value) for value in entry.get("material_classes", []))
        process = entry.get("process_evidence", {})
        if isinstance(process, Mapping) and process.get("recipe_ids"):
            recipe_linked += 1
        identifiers = entry.get("identifiers", {})
        if isinstance(identifiers, Mapping) and identifiers.get("pubchem_cid"):
            pubchem_enriched += 1
    return {
        "total_material_records": len(entries),
        "counted_non_elemental_reduced_formula_count": counted,
        "supplemental_records": supplemental,
        "material_classes": dict(sorted(class_counts.items())),
        "recipe_linked_materials": recipe_linked,
        "pubchem_enriched_materials": pubchem_enriched,
    }
