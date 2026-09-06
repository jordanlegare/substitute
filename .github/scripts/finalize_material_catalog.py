from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


readme = Path("README.md")
replace_once(
    readme,
    "| Rank evidence-supported 2–6 precursor candidates | `ald-master candidates ...` |\n",
    "| Rank evidence-supported 2–6 precursor candidates | `ald-master candidates ...` |\n"
    "| Browse the 1,000-material identity catalog | `ald-master materials search ...` |\n",
)
replace_once(
    readme,
    "## Compatibility evidence engine\n",
    """## 1,000-material identity catalog

`materials/catalog.json` is a separate, offline identity catalog containing exactly **1,000 unique non-elemental fixed-stoichiometry reduced formulas** for the current milestone. Every counted entry is provenance-backed. COD is the primary crystallographic/existence source; PubChem identity fields are added only when an unambiguous formula-matched enrichment is available.

This catalog is **not** 1,000 executable ALD/MLD recipes. `recipes/compounds/catalog.json` remains the executable simulation-recipe index. A material without a linked recipe is identity-only, and its absence from the compatibility evidence graph remains `UNKNOWN`, not incompatible.

Common discovery commands:

```bash
ald-master materials search HfO2
ald-master materials show HfO2
ald-master materials list --class oxide --element Hf --limit 50
ald-master materials report
```

The material catalog rebuilds deterministically from committed frozen source metadata:

```bash
python tools/build_material_catalog.py --check --target-count 1000
```

See [`docs/material-catalog.md`](docs/material-catalog.md) for provenance, counting rules, offline rebuilds, CLI details, and the identity/process-evidence boundary.

## Compatibility evidence engine
""",
)

master = Path("ald_master/__init__.py")
replace_once(
    master,
    "Compatibility evidence engine\n-----------------------------\n",
    """Material identity catalog
-------------------------
Global input:
  --materials-catalog PATH  Offline identity catalog (default materials/catalog.json)

Commands:
  ald-master materials search TEXT [--limit N] [--json]
  ald-master materials show MATERIAL [--json]
  ald-master materials list [--class CLASS] [--element ELEMENT] [--limit N] [--json]
  ald-master materials report [--json]

Material identity is distinct from process/compatibility evidence. A catalog-only
material may be recognized while compatibility remains E0_UNKNOWN / UNKNOWN.

Compatibility evidence engine
-----------------------------
""",
)
