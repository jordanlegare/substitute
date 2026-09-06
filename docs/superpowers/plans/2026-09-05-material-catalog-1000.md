# 1,000-Material Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline, deterministic, provenance-backed catalog containing exactly 1,000 counted real non-elemental thin-film/materials-relevant compounds, while preserving the existing executable ALD/MLD recipe catalog and compatibility semantics.

**Architecture:** Keep `recipes/compounds/catalog.json` as the executable recipe index. Add a focused `ald_materials.py` module for formula normalization, catalog loading/querying, and reporting; a network-capable refresh tool that freezes normalized COD/PubChem source data; and an offline deterministic builder that produces `materials/catalog.json`, `materials/source-manifest.json`, and `materials/build-audit.json`. Extend the `ald_master` package facade with discovery commands and catalog-only compatibility fallback without adding catalog-only nodes to the exhaustive compatibility graph.

**Tech Stack:** Python 3.10+, Python standard library (`argparse`, `collections`, `fractions`, `hashlib`, `json`, `math`, `pathlib`, `re`, `urllib`), pytest. Existing runtime dependencies remain unchanged. Network access is allowed only in the refresh tool; runtime, CI catalog checks, compatibility, Product MP4, and HLS remain offline.

**Spec:** `docs/superpowers/specs/2026-09-05-material-catalog-1000-design.md`

## Global Constraints

- Counted milestone size is exactly `1000` unique non-elemental fixed-stoichiometry reduced formulas.
- Counted records require at least one public identity/provenance source.
- COD is the primary structural/existence source; PubChem is optional identity normalization; Materials Project remains optional enrichment and is not required by the canonical build.
- Identity evidence must never be promoted automatically to process evidence or compatibility evidence.
- `recipes/compounds/catalog.json` semantics remain unchanged.
- Existing compatibility graph remains anchored to executable recipe-backed materials; do not create the roughly 999,000 directed catalog-only interfaces.
- Missing compatibility evidence is `UNKNOWN`/unavailable, never incompatible.
- Normal runtime and CI do not access the network.
- Material records must not contain process temperature, dose/pulse timing, flow, pressure, handling instructions, equipment settings, or inferred fabrication mappings.
- Identical frozen source inputs and recipe catalog bytes must generate byte-identical catalog/audit artifacts.
- No merge is part of this plan unless separately requested.

---

## File Structure

### New files

- `ald_materials.py` — formula parser/reducer, material catalog validation/loading, deterministic search/filter/show/report helpers, material identity resolver.
- `tools/build_material_catalog.py` — offline deterministic source merge, relevance classification, recipe linkage, exact-1,000 selection, canonical artifact generation/check mode.
- `tools/refresh_material_sources.py` — network-only COD/PubChem refresh into normalized frozen snapshots.
- `materials/sources/cod-materials.json` — normalized COD-backed candidate snapshot used by the canonical builder.
- `materials/sources/pubchem-identities.json` — optional normalized PubChem enrichments keyed by reduced formula.
- `materials/source-manifest.json` — frozen-source provenance/hashes/refresh metadata.
- `materials/catalog.json` — `ald-material-catalog/1` canonical catalog.
- `materials/build-audit.json` — deterministic count/exclusion/distribution/hash audit.
- `tests/test_material_catalog.py` — formula/parser/schema/determinism/count/linkage/safety tests.
- `tests/test_material_cli.py` — `ald-master materials` parser/dispatch/output tests.

### Existing files modified

- `ald_master/__init__.py` — add material commands and catalog-only compatibility fallback.
- `pyproject.toml` — package `ald_materials` as a top-level module.
- `tests/test_ald_master_compatibility.py` — regression for known identity + unknown compatibility evidence.
- `tests/test_ald_compatibility_real_catalog.py` — prove exhaustive graph counts remain recipe-backed and unchanged in scope.
- `README.md` — document material catalog boundary and discovery commands.

---

### Task 1: Formula parser, reduced-formula identity, and material catalog query core

**Files:**
- Create: `ald_materials.py`
- Create: `tests/test_material_catalog.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces:
  - `parse_formula(value: str) -> dict[str, int]`
  - `reduce_formula(value: str) -> tuple[str, tuple[str, ...]]`
  - `material_id(reduced_formula: str) -> str`
  - `canonical_json_bytes(value: object) -> bytes`
  - `load_material_catalog(path: Path | str = Path("materials/catalog.json")) -> list[dict[str, Any]]`
  - `resolve_material(entries: Sequence[Mapping[str, Any]], query: str) -> Mapping[str, Any]`
  - `search_materials(entries, query: str, limit: int = 20) -> list[dict[str, Any]]`
  - `filter_materials(entries, material_class: str | None = None, element: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
  - `material_report(entries) -> dict[str, Any]`

- [ ] **Step 1: Write parser/reduction RED tests**

Add tests including:

```python
@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("HfO2", "HfO2"),
        ("Al2O3", "Al2O3"),
        ("Fe2O4", "FeO2"),
        ("Ca3(PO4)2", "Ca3O8P2"),
        ("Li2FeSiO4", "FeLi2O4Si"),
    ],
)
def test_reduce_formula_is_fixed_and_deterministic(formula, expected):
    reduced, elements = materials.reduce_formula(formula)
    assert reduced == expected
    assert tuple(sorted(elements)) == elements
```

Also assert rejection of `CoSx`, `TiO2-x`, `A/B`, decimals/occupancy notation, unmatched parentheses, empty strings, unknown element symbols, and zero/negative counts.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/test_material_catalog.py -q
```

Expected: import failure for `ald_materials`.

- [ ] **Step 3: Implement a strict recursive formula parser**

Use a tokenizer matching only known IUPAC element symbols, integer multiplicities, and parentheses. Do not support variables or decimal occupancies in the counted parser. Parenthetical groups multiply nested element counts.

Canonical reduction algorithm:

```python
counts = parse_formula(value)
divisor = math.gcd(*counts.values())
reduced_counts = {element: count // divisor for element, count in counts.items()}
ordered = sorted(reduced_counts)
formula = "".join(
    element + (str(reduced_counts[element]) if reduced_counts[element] != 1 else "")
    for element in ordered
)
```

`material_id()` uses a readable normalized formula slug plus a short SHA-256 suffix to avoid collisions, e.g. `mat-hfo2-<8hex>`.

- [ ] **Step 4: Implement catalog validation/query helpers**

`load_material_catalog()` validates top-level schema `ald-material-catalog/1`, entries array, unique `material_id`, deterministic ordering, and required fields. `resolve_material()` accepts exact material ID, formula, reduced formula, canonical name, or alias; ambiguity raises `ValueError`.

Search ranking tuple:

```python
(
    match_rank,        # 0 exact id/formula, 1 exact name, 2 prefix, 3 substring
    material["reduced_formula"],
    material["material_id"],
)
```

- [ ] **Step 5: Add packaging assertion and implementation**

Test:

```python
def test_pyproject_packages_material_module():
    assert '"ald_materials"' in Path("pyproject.toml").read_text()
```

Add `"ald_materials"` to `[tool.setuptools].py-modules`.

- [ ] **Step 6: Run focused tests GREEN**

```bash
python -m pytest tests/test_material_catalog.py -q
```

- [ ] **Step 7: Commit**

```bash
git add ald_materials.py tests/test_material_catalog.py pyproject.toml
git commit -m "feat: add material identity core"
```

---

### Task 2: Offline deterministic builder and audit schema with fixture data

**Files:**
- Create: `tools/build_material_catalog.py`
- Modify: `tests/test_material_catalog.py`

**Interfaces:**
- Consumes normalized source snapshots shaped as arrays of records containing at minimum `source`, `source_id`, `formula`, `name`, and optional phase/identifier fields.
- Produces:
  - `build_material_artifacts(source_records, pubchem_records, recipe_entries, *, target_count: int = 1000, manifest_template: Mapping[str, Any] | None = None) -> tuple[dict, dict, dict]`
  - `classify_material(elements: Sequence[str], reduced_formula: str, metadata: Mapping[str, Any]) -> list[str]`
  - `relevance_score(record: Mapping[str, Any]) -> tuple[int, ...]`
  - CLI `python tools/build_material_catalog.py [--check] [--target-count 1000]`

- [ ] **Step 1: Write builder RED tests with a compact frozen fixture**

Use 6–10 synthetic *source records representing real formulas* only as unit-test fixtures. Assert duplicate `HfO2` source records collapse into one counted material, phases merge, `Fe` is excluded from counted size, `CoSx` is rejected from counted selection, and missing provenance cannot enter the counted set.

Example assertion:

```python
catalog, manifest, audit = builder.build_material_artifacts(
    source_records,
    pubchem_records,
    recipe_entries,
    target_count=4,
    manifest_template={"retrieved_at": "2026-09-05T00:00:00Z"},
)
assert catalog["counted_non_elemental_reduced_formula_count"] == 4
assert len({m["reduced_formula"] for m in catalog["entries"] if m["counted"]}) == 4
assert audit["duplicate_reduced_formula_collapses"] >= 1
```

- [ ] **Step 2: Run tests RED**

```bash
python -m pytest tests/test_material_catalog.py -q
```

Expected: missing builder functions.

- [ ] **Step 3: Implement deterministic candidate normalization/merge**

For each source record:

1. require non-empty source/source_id/provenance identity;
2. attempt fixed formula reduction;
3. classify elemental/symbolic/parse-failed exclusion reason;
4. merge fixed candidates by reduced formula;
5. merge source IDs and phases by canonical JSON bytes;
6. choose canonical name using source precedence `pubchem normalized title > COD mineral/chemical name > lexical source name` only when the source supplied it;
7. never invent a name.

- [ ] **Step 4: Implement deterministic composition classification**

Rules are explicit and composition based. Examples:

```python
if "O" in elements: classes.add("oxide")
if "N" in elements and "O" not in elements: classes.add("nitride")
if "S" in elements: classes.add("sulfide")
if "Se" in elements: classes.add("selenide")
if "Te" in elements: classes.add("telluride")
if "F" in elements: classes.add("fluoride")
if any(x in elements for x in ("Cl", "Br", "I")): classes.add("halide")
if "C" in elements and not organic_metadata: classes.add("carbide-or-inorganic-carbon")
if "B" in elements: classes.add("boride")
if "Si" in elements and len(elements) >= 2: classes.add("silicide-or-silicate")
if "P" in elements: classes.add("phosphide-or-phosphate")
if "As" in elements: classes.add("arsenide")
```

Additional tags such as `perovskite`, `spinel`, `layered`, `battery`, `transparent-conductor`, `dielectric`, `magnetic`, or `catalyst` may only come from explicit normalized source tags/curated classification fields, not guesses from formula alone.

- [ ] **Step 5: Implement deterministic selection and audit**

Counted eligibility: fixed formula, two or more elements, provenance, relevant class. Sort eligible candidates by versioned relevance tuple then reduced formula/source ID. Select exactly `target_count`; raise `ValueError` if fewer are eligible.

Audit fields include every spec-required count plus `final_material_ids` and SHA-256 hashes of source inputs/catalog.

- [ ] **Step 6: Implement canonical `--check` mode**

The tool reads frozen `materials/sources/*.json` and recipe catalog, builds all three artifacts, and either writes them or byte-compares checked-in versions under `--check`.

- [ ] **Step 7: Run focused tests GREEN and commit**

```bash
python -m pytest tests/test_material_catalog.py -q
git add tools/build_material_catalog.py tests/test_material_catalog.py
git commit -m "feat: add deterministic material catalog builder"
```

---

### Task 3: Network refresh tool and source snapshot normalization

**Files:**
- Create: `tools/refresh_material_sources.py`
- Modify: `tests/test_material_catalog.py`

**Interfaces:**
- Produces normalized COD and PubChem snapshots only; it never writes canonical catalog records directly.
- Key functions:
  - `normalize_cod_row(row: Mapping[str, Any]) -> dict[str, Any] | None`
  - `normalize_pubchem_payload(reduced_formula: str, payload: Mapping[str, Any]) -> dict[str, Any] | None`
  - `refresh_cod(...) -> list[dict[str, Any]]`
  - `refresh_pubchem(formulas: Sequence[str], ...) -> list[dict[str, Any]]`

- [ ] **Step 1: Add network-free normalization tests**

Feed captured/minimal response dictionaries directly to normalization helpers. Assert only allowed fields survive and no process parameters can enter snapshots.

- [ ] **Step 2: Run RED and implement normalizers**

The normalized COD record permits only identity/structural provenance fields such as `source_id`, `formula`, `name`, `space_group`, bibliographic DOI/reference, and explicit source tags. PubChem permits `cid`, `molecular_formula`, `iupac_name`/title, `inchi`, `inchikey`.

- [ ] **Step 3: Implement refresh CLI with cache/retry/rate controls**

Use `urllib.request` so there is no new dependency. The refresh command accepts explicit output paths and supports cached responses. Retrieval timestamps belong in the source snapshot manifest metadata and are not inserted into material records.

- [ ] **Step 4: Verify network-free tests and commit**

```bash
python -m pytest tests/test_material_catalog.py -q
git add tools/refresh_material_sources.py tests/test_material_catalog.py
git commit -m "feat: add material source refresh pipeline"
```

---

### Task 4: Build the real COD-backed candidate snapshot and exact 1,000 selection

**Files:**
- Create: `materials/sources/cod-materials.json`
- Create: `materials/sources/pubchem-identities.json`
- Create: `materials/source-manifest.json`
- Create: `materials/catalog.json`
- Create: `materials/build-audit.json`
- Modify: `tests/test_material_catalog.py`

**Interfaces:**
- Consumes public COD identity/structure records and optional PubChem normalization.
- Produces exactly 1,000 counted fixed reduced formulas plus any necessary non-counted supplemental records.

- [ ] **Step 1: Add hard acceptance RED tests before adding data**

```python
def test_real_material_catalog_has_exactly_1000_counted_unique_compounds():
    payload = json.loads(Path("materials/catalog.json").read_text())
    counted = [entry for entry in payload["entries"] if entry["counted"]]
    assert payload["counted_non_elemental_reduced_formula_count"] == 1000
    assert len(counted) == 1000
    assert len({entry["reduced_formula"] for entry in counted}) == 1000
    assert all(len(entry["elements"]) >= 2 for entry in counted)
    assert all(entry["provenance"] for entry in counted)
```

Also test `tools/build_material_catalog.py --check` against checked-in artifacts.

- [ ] **Step 2: Run RED**

Expected: files absent.

- [ ] **Step 3: Acquire and normalize more than 1,000 real eligible COD candidates**

Use the refresh path or a one-time reviewed source export. Preserve COD IDs and supplied structural/bibliographic provenance. Do not generate formulas combinatorially and call them real; every counted formula must originate from an actual public source record.

- [ ] **Step 4: PubChem-normalize where matches are unambiguous**

A missing PubChem match remains valid COD-backed identity. Ambiguous formula-only PubChem results must not be guessed; record unresolved enrichment.

- [ ] **Step 5: Run offline builder and inspect audit**

Require accepted eligible pool `>= 1000`, exact counted selection `== 1000`, nonzero provenance coverage `== 100%`, and sensible class distributions. Review the most common elements/classes and rejection reasons for obvious parser/source artifacts before committing.

- [ ] **Step 6: Run exact-catalog tests GREEN and commit data artifacts**

```bash
python -m pytest tests/test_material_catalog.py -q
python tools/build_material_catalog.py --check
git add materials tests/test_material_catalog.py
git commit -m "data: add 1000 real material identities"
```

---

### Task 5: Link material identities to existing executable recipes

**Files:**
- Modify: `tools/build_material_catalog.py`
- Modify: `materials/catalog.json`
- Modify: `materials/build-audit.json`
- Modify: `tests/test_material_catalog.py`

**Interfaces:**
- Fixed recipe targets link by `ald_materials.reduce_formula(entry["target_formula"])`.
- `process_evidence` shape:

```json
{
  "status": "executable-recipe",
  "recipe_ids": ["..."],
  "recipe_paths": ["..."]
}
```

Catalog-only records use:

```json
{"status":"identity-only","recipe_ids":[],"recipe_paths":[]}
```

- [ ] **Step 1: Add RED linkage tests**

Assert known fixed targets such as `HfO2`, `Al2O3`, and `ZnS` link to their recipe IDs if present in the recipe catalog. Assert identity-only materials have no executable recipe claim. Symbolic recipe targets are skipped unless explicitly mapped.

- [ ] **Step 2: Implement deterministic recipe linkage and rebuild artifacts**

Never infer a recipe for a material based on family similarity.

- [ ] **Step 3: Run GREEN and commit**

```bash
python -m pytest tests/test_material_catalog.py -q
python tools/build_material_catalog.py --check
git add tools/build_material_catalog.py materials tests/test_material_catalog.py
git commit -m "feat: link materials to executable recipes"
```

---

### Task 6: Add `ald-master materials` discovery CLI

**Files:**
- Modify: `ald_master/__init__.py`
- Create: `tests/test_material_cli.py`
- Modify: `README.md`

**Interfaces:**
- Add global `--materials-catalog PATH`, default `materials/catalog.json`.
- Commands:
  - `materials search TEXT [--limit N] [--json]`
  - `materials show MATERIAL [--json]`
  - `materials list [--class CLASS] [--element ELEMENT] [--limit N] [--json]`
  - `materials report [--json]`

- [ ] **Step 1: Write parser/dispatch RED tests**

Assert parser fields and JSON output. Example:

```python
args = ald_master.build_parser().parse_args([
    "materials", "list", "--class", "oxide", "--element", "Hf", "--json"
])
assert args.command == "materials"
assert args.materials_command == "list"
```

- [ ] **Step 2: Implement parser wiring**

Import `ald_materials as materials`. Add `DEFAULT_MATERIAL_CATALOG = Path("materials/catalog.json")`. Add nested subparsers and material dispatch helpers.

- [ ] **Step 3: Implement human and JSON renderers**

Human output must clearly distinguish `identity-only` from `executable-recipe`; do not print process instructions.

- [ ] **Step 4: Add real CLI acceptance tests**

Run `ald_master.main()` against the checked-in catalog for exact formula search, class/element filtering, show, report, not-found, and stable JSON output.

- [ ] **Step 5: Update CLI reference/README and run GREEN**

```bash
python -m pytest tests/test_material_cli.py tests/test_material_catalog.py -q
```

- [ ] **Step 6: Commit**

```bash
git add ald_master/__init__.py tests/test_material_cli.py README.md
git commit -m "feat: add material catalog discovery commands"
```

---

### Task 7: Compatibility fallback for known catalog-only materials without graph expansion

**Files:**
- Modify: `ald_master/__init__.py`
- Modify: `tests/test_ald_master_compatibility.py`
- Modify: `tests/test_ald_compatibility_real_catalog.py`

**Interfaces:**
- Existing `ald_compatibility.query_material()` remains unchanged and graph-local.
- Add facade helper:
  - `_query_material_with_identity_fallback(args, snapshot, a: str, b: str | None, top: int) -> Any`

Fallback result for a catalog-only single material:

```json
{
  "kind": "material-identity-without-compatibility-evidence",
  "material": {"material_id":"...","formula":"...","name":"..."},
  "evidence_level": "E0_UNKNOWN",
  "verdict": "UNKNOWN",
  "compatibility_evidence_available": false,
  "note": "Material identity is known, but Substitute has no recipe-backed compatibility node for this material."
}
```

For a pair where either endpoint is catalog-only, return the same explicit unknown-evidence result containing both resolved identities; never fabricate a score/edge.

- [ ] **Step 1: Write RED regression tests**

Monkeypatch an identity catalog containing a material absent from the compatibility snapshot and assert `compatible material` returns code 0 with `UNKNOWN`, not `ValueError`/incompatible. Assert recipe-backed `HfO2 -> Al2O3` output remains byte/semantically equivalent to current behavior.

- [ ] **Step 2: Implement fallback only in material CLI dispatch**

Precursor queries and candidate ranking are unchanged.

- [ ] **Step 3: Assert graph scope remains recipe-backed**

Existing real-catalog test continues to assert `m*(m-1)` where `m` is compatibility snapshot material count, not 1,000.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_ald_master_compatibility.py tests/test_ald_compatibility_real_catalog.py -q
git add ald_master/__init__.py tests/test_ald_master_compatibility.py tests/test_ald_compatibility_real_catalog.py
git commit -m "feat: report unknown compatibility for identity-only materials"
```

---

### Task 8: Repository-wide safety, canonical, and documentation regression coverage

**Files:**
- Modify: `tests/test_material_catalog.py`
- Modify: `README.md`

- [ ] **Step 1: Add prohibited-field recursive scan**

Reject any material/source record keys matching operational concepts such as `process_temperature`, `pulse_time`, `dose_time`, `flow_sccm`, `process_pressure`, `growth_window`, `handling_notes`, `equipment_settings`, or equivalents introduced by this feature.

- [ ] **Step 2: Add canonical-artifact and determinism tests**

Build twice from the same frozen sources to temporary paths and assert all generated bytes match each other and checked-in artifacts.

- [ ] **Step 3: Document source/evidence boundary**

README must say the 1,000 records are real material identities, not 1,000 validated ALD recipes; describe COD/PubChem provenance and offline rebuild; list material commands.

- [ ] **Step 4: Run focused catalog/CLI/compatibility suite**

```bash
python -m pytest \
  tests/test_material_catalog.py \
  tests/test_material_cli.py \
  tests/test_compound_catalog.py \
  tests/test_ald_master.py \
  tests/test_ald_master_compatibility.py \
  tests/test_ald_compatibility_real_catalog.py -q
python tools/build_compound_catalog.py --check
python tools/build_material_catalog.py --check
```

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_material_catalog.py
git commit -m "test: harden material catalog acceptance"
```

---

### Task 9: Full verification, workflow evidence, and PR

**Files:**
- No production changes unless verification exposes a defect.

- [ ] **Step 1: Compile all Python modules**

```bash
python -m compileall -q .
```

Expected: success.

- [ ] **Step 2: Run complete pytest suite**

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Re-run both catalog canonical checks**

```bash
python tools/build_compound_catalog.py --check
python tools/build_material_catalog.py --check
```

Expected: both exit 0.

- [ ] **Step 4: Run Product MP4 and HLS acceptance in CI on the final head**

Require both existing GitHub Actions workflows to complete successfully. Record run IDs and exact test counts in the PR body.

- [ ] **Step 5: Inspect final audit and diff**

Record:

- counted materials = 1,000;
- unique counted reduced formulas = 1,000;
- provenance coverage = 100%;
- source candidate/accepted/rejection counts;
- PubChem enrichment coverage;
- recipe-linked material count;
- final catalog/source/audit hashes;
- changed-file list and net additions/deletions.

- [ ] **Step 6: Open PR without merging**

Title: `Add 1000-material provenance catalog`

PR body must explain:

1. the identity-vs-process-evidence boundary;
2. source architecture and licensing/provenance;
3. exact 1,000 counting rule;
4. compatibility graph intentionally not expanded to 1,000 nodes;
5. canonical/determinism results;
6. pytest/Product/HLS verification evidence;
7. safety boundary unchanged.

Do not merge unless the user explicitly requests it.
