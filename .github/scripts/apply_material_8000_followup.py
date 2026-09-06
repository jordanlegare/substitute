from pathlib import Path

builder = Path("tools/build_material_catalog.py")
text = builder.read_text(encoding="utf-8")
old = '''def _pubchem_index(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        reduced = str(record.get("reduced_formula", "")).strip()
        if not reduced:
            formula = record.get("molecular_formula") or record.get("formula")
            if isinstance(formula, str):
                try:
                    reduced, _ = materials.reduce_formula(formula)
                except ValueError:
                    continue
        if reduced and reduced not in result:
            result[reduced] = record
    return result
'''
new = '''def _pubchem_index(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        formula = record.get("reduced_formula") or record.get("molecular_formula") or record.get("formula")
        if not isinstance(formula, str) or not formula.strip():
            continue
        try:
            reduced, _ = materials.reduce_formula(formula.strip())
        except ValueError:
            continue
        if reduced not in result:
            result[reduced] = record
    return result
'''
assert old in text
text = text.replace(old, new, 1)
builder.write_text(text, encoding="utf-8")

refresh = Path("tools/refresh_material_sources.py")
text = refresh.read_text(encoding="utf-8")
marker = '''def _load_or_fetch_json(url: str, *, cache_path: Path | None, timeout: float, retries: int) -> Any:
'''
assert marker in text
insert = '''def build_pubchem_formula_variant_index(
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


'''
if "def build_pubchem_formula_variant_index(" not in text:
    text = text.replace(marker, insert + marker, 1)
refresh.write_text(text, encoding="utf-8")
