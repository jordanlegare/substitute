from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


readme_path = Path("README.md")
readme = readme_path.read_text(encoding="utf-8")
readme = replace_once(
    readme,
    "| Browse the 1,000-material identity catalog | `ald-master materials search ...` |",
    "| Browse the 8,000-material identity catalog | `ald-master materials search ...` |",
    "README catalog table",
)
readme = replace_once(
    readme,
    "## 1,000-material identity catalog",
    "## 8,000-material identity catalog",
    "README catalog heading",
)
readme = replace_once(
    readme,
    "`materials/catalog.json` is a separate, offline identity catalog containing exactly **1,000 unique non-elemental fixed-stoichiometry reduced formulas** for the current milestone. Every counted entry is provenance-backed. COD is the primary crystallographic/existence source; PubChem identity fields are added only when an unambiguous formula-matched enrichment is available.",
    "`materials/catalog.json` is a separate, offline identity catalog containing exactly **8,000 unique non-elemental fixed-stoichiometry reduced formulas** for the current milestone. Every counted entry has an exact formula/CID match in the full PubChemRDF molecular-formula mirror release dated 2026-07-25. Of the selected identities, **7,122 are also COD-backed** and **878 are explicitly PubChem-primary supplements**. PubChem-primary status is identity evidence only; it does not create process or compatibility evidence.",
    "README catalog provenance paragraph",
)
readme = replace_once(
    readme,
    "This catalog is **not** 1,000 executable ALD/MLD recipes.",
    "This catalog is **not** 8,000 executable ALD/MLD recipes.",
    "README recipe boundary",
)
readme = replace_once(
    readme,
    "python tools/build_material_catalog.py --check --target-count 1000",
    "python tools/build_material_catalog.py --check --target-count 8000",
    "README rebuild command",
)
readme_path.write_text(readme, encoding="utf-8")


doc_path = Path("docs/material-catalog.md")
doc = doc_path.read_text(encoding="utf-8")
doc = replace_once(
    doc,
    "2. `materials/catalog.json` is the provenance-backed material identity catalog. Its `ald-material-catalog/1` schema contains exactly 1,000 counted, unique, non-elemental fixed-stoichiometry reduced formulas for the current milestone.",
    "2. `materials/catalog.json` is the provenance-backed material identity catalog. Its `ald-material-catalog/1` schema contains exactly 8,000 counted, unique, non-elemental fixed-stoichiometry reduced formulas for the current milestone.",
    "catalog overview count",
)
doc = replace_once(
    doc,
    "For `ald-material-catalog/1`, CI requires exactly 1,000 counted records.",
    "For `ald-material-catalog/1`, CI requires exactly 8,000 counted records.",
    "CI count",
)
doc = replace_once(
    doc,
    "Polymorphs, multiple COD structures, and repeated literature structures merge under one reduced-formula material identity. Elemental and symbolic/nonstoichiometric records do not contribute to the 1,000 count.",
    "Polymorphs, multiple COD structures, and repeated literature structures merge under one reduced-formula material identity. Elemental and symbolic/nonstoichiometric records do not contribute to the 8,000 count.",
    "counting rule",
)
old_provenance = """The primary existence and structural-provenance source is the Crystallography Open Database (COD). The committed frozen source snapshot preserves normalized COD metadata, including COD identifiers and available phase/bibliographic fields, rather than mirroring CIF payloads.

The canonical snapshot for this milestone was acquired from a dated public mirror of COD metadata and retains COD as the provenance source. The mirror is transport only; it does not replace COD identity/provenance.

PubChem enrichment is optional. An enrichment is accepted only when the query resolves unambiguously and its returned molecular formula normalizes to the same reduced formula. Failure or ambiguity in PubChem does not invalidate a COD-backed material.

Materials Project is not required to build or use the canonical catalog."""
new_provenance = """The catalog uses a two-tier identity-provenance model. COD-backed identities remain the preferred tier because they carry crystallographic/existence provenance plus available phase and bibliographic metadata. The frozen COD pool was built from 533,486 public mirror rows, yielding 33,777 eligible unique fixed inorganic reduced formulas after deterministic filtering.

Every counted identity is also required to have an exact molecular-formula match in the full PubChemRDF mirror release dated 2026-07-25. The audit streams all nine molecular-formula shards; the current frozen audit scanned 124,004,129 formula records. Of the 33,777 COD candidate formulas, 7,122 had exact PubChemRDF matches.

Because the COD-plus-PubChem intersection is smaller than the 8,000 milestone, the remaining 878 selected records come from an explicitly lower provenance tier named `pubchem-primary`. These supplemental records are fixed-stoichiometry, non-elemental, material-like inorganic identities with PubChem CID/formula evidence and no claim of COD crystallographic backing. The bulk audit retained a bounded pool of 4,000 such supplemental formulas, producing 11,122 total eligible PubChem-matched identities before final ranking and selection.

PubChem-primary identity evidence never creates ALD/MLD process evidence, compatibility evidence, fabrication mappings, or operating conditions. Materials Project is not required to build or use the canonical catalog."""
doc = replace_once(doc, old_provenance, new_provenance, "provenance section")
doc = replace_once(
    doc,
    "python tools/build_material_catalog.py --target-count 1000",
    "python tools/build_material_catalog.py --target-count 8000",
    "build command",
)
doc = replace_once(
    doc,
    "python tools/build_material_catalog.py --check --target-count 1000",
    "python tools/build_material_catalog.py --check --target-count 8000",
    "check command",
)
doc = replace_once(
    doc,
    "The exhaustive compatibility snapshot remains bounded to the executable recipe catalog. The 1,000 identity records are **not** expanded into a roughly one-million-edge mostly-unknown graph.",
    "The exhaustive compatibility snapshot remains bounded to the executable recipe catalog. The 8,000 identity records are **not** expanded into an enormous mostly-unknown compatibility graph.",
    "compatibility graph boundary",
)
doc_path.write_text(doc, encoding="utf-8")

for path in (readme_path, doc_path):
    text = path.read_text(encoding="utf-8")
    forbidden = ("1,000-material identity catalog", "--target-count 1000", "exactly **1,000")
    leftovers = [token for token in forbidden if token in text]
    if leftovers:
        raise RuntimeError(f"{path}: stale milestone text remains: {leftovers}")

print("updated 8,000-material documentation")
