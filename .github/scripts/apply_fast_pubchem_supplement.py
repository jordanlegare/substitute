from pathlib import Path

path = Path("tools/refresh_material_sources.py")
text = path.read_text(encoding="utf-8")
old = '''def normalize_pubchem_primary_formula(formula: str) -> str | None:\n    """Return a conservative fixed-inorganic reduced formula for catalog supplementation."""\n    try:\n        reduced, elements = materials.reduce_formula(formula)\n'''
new = '''def normalize_pubchem_primary_formula(formula: str) -> str | None:\n    """Return a conservative fixed-inorganic reduced formula for catalog supplementation."""\n    # PubChem molecular formulas use Hill ordering. Carbon-bearing formulas therefore\n    # overwhelmingly begin with a carbon token; reject those before full parsing while\n    # preserving element symbols such as Ca, Cd, Ce, Cl, Co, Cr, Cs, and Cu. Apply the\n    # same safe fast path to a leading hydrogen token while preserving Hf, Hg, and Ho.\n    if formula and formula[0] in {"C", "H"} and (len(formula) == 1 or not formula[1].islower()):\n        return None\n    try:\n        reduced, elements = materials.reduce_formula(formula)\n'''
if text.count(old) != 1:
    raise SystemExit(f"expected one target, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("applied fast PubChem supplement prefilter")
