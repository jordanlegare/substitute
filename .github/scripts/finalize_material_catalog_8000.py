from pathlib import Path

README = Path("README.md")
DOC = Path("docs/material-catalog.md")
BUILDER = Path("tools/build_material_catalog.py")

text = README.read_text(encoding="utf-8")
text = text.replace("Browse the 1,000-material identity catalog", "Browse the 8,000-material identity catalog")
text = text.replace("## 1,000-material identity catalog", "## 8,000-material identity catalog")
text = text.replace(
    "`materials/catalog.json` is a separate, offline identity catalog containing exactly **1,000 unique non-elemental fixed-stoichiometry reduced formulas** for the current milestone. Every counted entry is provenance-backed. COD is the primary crystallographic/existence source; PubChem identity fields are added only when an unambiguous formula-matched enrichment is available.",
    "`materials/catalog.json` is a separate, offline identity catalog containing exactly **8,000 unique non-elemental fixed-stoichiometry reduced formulas** for the current milestone. Every counted entry is backed by COD crystallographic provenance and an exact molecular-formula match found by scanning the full nine-shard PubChemRDF compound formula mirror (release 2026-07-25). PubChem contributes identity/provenance only; it does not add process conditions or compatibility evidence.",
)
text = text.replace("This catalog is **not** 1,000 executable ALD/MLD recipes.", "This catalog is **not** 8,000 executable ALD/MLD recipes.")
text = text.replace("python tools/build_material_catalog.py --check --target-count 1000", "python tools/build_material_catalog.py --check --target-count 8000")
README.write_text(text, encoding="utf-8")

text = DOC.read_text(encoding="utf-8")
text = text.replace("exactly 1,000 counted, unique, non-elemental fixed-stoichiometry reduced formulas", "exactly 8,000 counted, unique, non-elemental fixed-stoichiometry reduced formulas")
text = text.replace("For `ald-material-catalog/1`, CI requires exactly 1,000 counted records.", "For `ald-material-catalog/1`, CI requires exactly 8,000 counted records.")
text = text.replace("do not contribute to the 1,000 count.", "do not contribute to the 8,000 count.")
text = text.replace(
    "PubChem enrichment is optional. An enrichment is accepted only when the query resolves unambiguously and its returned molecular formula normalizes to the same reduced formula. Failure or ambiguity in PubChem does not invalidate a COD-backed material.",
    "For this milestone, PubChem verification is mandatory for canonical selection. The build streams all nine official PubChemRDF `compound:CID → vocab:molecular_formula` shards from the 2026-07-25 release (803,480,392 compressed bytes in the audited release). A COD candidate is eligible for the canonical 8,000 only when at least one PubChem CID has an exact formula-unit match that reduces to the same Substitute formula. All matching CIDs are retained in deterministic order. This is an identity audit only and does not imply process compatibility or experimental qualification.",
)
text = text.replace("python tools/build_material_catalog.py --target-count 1000", "python tools/build_material_catalog.py --target-count 8000")
text = text.replace("python tools/build_material_catalog.py --check --target-count 1000", "python tools/build_material_catalog.py --check --target-count 8000")
text = text.replace("The 1,000 identity records are **not** expanded", "The 8,000 identity records are **not** expanded")
text = text.replace("PubChem enrichment coverage", "PubChemRDF full-mirror audit coverage")
DOC.write_text(text, encoding="utf-8")

text = BUILDER.read_text(encoding="utf-8")
text = text.replace('parser.add_argument("--target-count", type=int, default=1000)', 'parser.add_argument("--target-count", type=int, default=8000)')
BUILDER.write_text(text, encoding="utf-8")
