# Recipe Evidence Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize distinct recipe-backed materials with defensible ALD/PEALD/MLD/hybrid chemistry evidence, then make those chemistries easy to search, inspect, source-check, and run through Substitute's existing synthetic simulator workflow.

**Architecture:** Normalize literature chemistry into a strict offline evidence ledger; select at most one best R2/R3 chemistry for each previously unbacked material; generate deterministic simulation-safe recipes; expose a read-only `ald-master chemistry` layer over recipe/evidence data. Network access is confined to the explicit refresh tool. Material identity, process chemistry, compatibility evidence, and simulator execution remain separate concepts.

**Tech Stack:** Python 3.10+, standard library (`argparse`, `csv`, `hashlib`, `json`, `pathlib`, `urllib`), existing `ald_core`, `ald_materials`, `ald_master`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-06-recipe-evidence-expansion-design.md`

## Global Constraints

- Preserve every pre-existing recipe file, recipe ID, and recipe path. The one-best rule applies only to newly generated expansion recipes.
- Only R2/R3 evidence may generate a new recipe. R1/rejected evidence never may.
- An exact source reactant label is sufficient identity when the source itself uses a formula, shorthand, plasma label, or other stable chemical label. Canonical reactant `name`/`formula` fields are optional enrichments and must never be invented.
- Literature controls target identity, exact reactant/source labels, process-family classification, and publication provenance only.
- Never persist or expose literature operating conditions: temperature, pressure, pulse/dose timing, purge timing, growth rate, plasma power/bias, flow, hardware configuration, reactor geometry, or handling instructions.
- Generated executable values remain fixed synthetic simulator defaults and keep `physical_fabrication_mapping: false` plus the existing simulation-only notice.
- Normal runtime, normal tests, deterministic builders, and canonical CI checks are offline. Only `tools/refresh_recipe_evidence.py` may use the network.
- Primary transport is the AtomicLimits-derived AWASES repository pinned at commit `1c67909db3b6219f168907f0552550bf82edb487`. The primary source file is `step 1/data/2-filtered-data.csv` with blob SHA `f6d08aaaadfbc834d9556b83167102381d72db14`. AtomicLimits remains the scientific provenance and database DOI is `10.6100/alddatabase`.
- Crossref is the preferred DOI metadata resolver; OpenAlex is the secondary resolver/fallback discovery source.
- The 8,000-material identity catalog is the search universe, not a claim that all 8,000 have ALD/MLD recipes.
- User-facing chemistry output is allow-list built and never exposes raw simulator instruction values.

---

### Task 1: Evidence normalization, grading, and deterministic selection core

**Files:**
- Create: `ald_recipe_evidence.py`
- Create: `tests/test_recipe_evidence.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `canonical_json_bytes(value: object) -> bytes`
- `normalize_doi(value: str) -> str`
- `normalize_process_family(value: str) -> str`
- `normalize_reactants(raw: Sequence[Mapping[str, object]]) -> list[dict[str, object]]`
- `chemistry_key(target_reduced_formula: str, process_family: str, reactants: Sequence[Mapping[str, object]]) -> str`
- `evidence_id(record: Mapping[str, object]) -> str`
- `validate_evidence_record(record: Mapping[str, object]) -> dict[str, object]`
- `selection_sort_key(record: Mapping[str, object]) -> tuple[object, ...]`
- `select_best_candidates(records: Sequence[Mapping[str, object]], existing_target_formulas: set[str]) -> list[dict[str, object]]`

- [ ] **Step 1: Write RED tests**

```python
def source_label_record():
    return {
        "target_material": "hafnium dioxide",
        "target_formula": "HfO2",
        "process_family": "thermal-ald",
        "reactants": [
            {"label": "HfCl4", "role": "reactant-a"},
            {"label": "H2O", "role": "reactant-b"},
        ],
        "publications": [{"type": "doi", "identifier": "10.1234/example", "direct": True}],
        "discovery_sources": ["atomiclimits"],
        "evidence_grade": "R2",
        "selection_status": "candidate",
    }


def test_r2_accepts_exact_source_labels_without_invented_canonical_identity():
    normalized = validate_evidence_record(source_label_record())
    assert normalized["reactants"][0]["label"] == "HfCl4"
    assert "name" not in normalized["reactants"][0]
```

Also test DOI normalization, reduced target formula, optional canonical reactant enrichment, deterministic reactant ordering, recursive operational-key rejection, and evidence-grade/status validation.

- [ ] **Step 2: Run RED**

`python -m pytest tests/test_recipe_evidence.py -q`

- [ ] **Step 3: Implement strict evidence core**

```python
EVIDENCE_SCHEMA = "ald-recipe-evidence/1"
ALLOWED_PROCESS_FAMILIES = {"thermal-ald", "plasma-ald", "mld", "hybrid"}
ALLOWED_GRADES = {"R1", "R2", "R3"}
ALLOWED_STATUSES = {"candidate", "selected", "rejected", "covered-existing"}
```

Validation rules:
- reduce target formula via `ald_materials.reduce_formula` and require at least two target elements for new expansion records;
- every reactant requires exact non-empty `label` and deterministic `role`;
- optional `name`/`formula` may be preserved only when supplied by an authoritative source; they are never derived from the label;
- R2/R3 require at least one direct stable publication identifier;
- R3 requires direct evidence plus AtomicLimits corroboration or a second independent direct publication;
- reject forbidden operational fields recursively;
- stable evidence ID uses target/process/reactant labels/publication IDs.

Selection tuple: R3 before R2; canonical-enriched identities before label-only when otherwise tied; more independent direct publications; fewer reactants; stable publication IDs; normalized chemistry lexical key; evidence ID tie-break.

- [ ] **Step 4: Add selection tests**

Test existing-target skip, R1 never selected, one selected record per target, deterministic ties, and label-only R2 eligibility.

- [ ] **Step 5: Package and GREEN**

Add `ald_recipe_evidence` to `pyproject.toml`; run focused tests.

- [ ] **Step 6: Commit**

`git commit -m "feat: add recipe evidence selection core"`

---

### Task 2: AtomicLimits-derived refresh adapters and publication resolution

**Files:**
- Create: `tools/refresh_recipe_evidence.py`
- Create: `tests/fixtures/recipe_evidence/atomiclimits_sample.csv`
- Create: `tests/fixtures/recipe_evidence/crossref_work.json`
- Create: `tests/fixtures/recipe_evidence/openalex_work.json`
- Create: `tests/test_recipe_evidence_refresh.py`

**Interfaces:**
- `parse_atomiclimits_rows(stream: TextIO) -> list[dict[str, object]]`
- `normalize_crossref_work(payload) -> dict[str, object]`
- `normalize_openalex_work(payload) -> dict[str, object]`
- `build_refresh_artifacts(...) -> tuple[dict[str, object], dict[str, object], dict[str, object]]`

- [ ] **Step 1: Write parser RED tests**

Fixture columns include `process_id`, `process_material`, `process_reactanta`, `process_reactantb`, `process_reactantc`, `process_reactantd`, and `reference_doi`. Tests prove exact labels survive and unrelated/operational columns are discarded.

- [ ] **Step 2: Run RED**

`python -m pytest tests/test_recipe_evidence_refresh.py -q`

- [ ] **Step 3: Implement pinned primary transport**

Constants:

```python
ATOMICLIMITS_DATABASE_DOI = "10.6100/alddatabase"
AWASES_REPOSITORY = "jd-coderepos/awases-ald"
AWASES_COMMIT = "1c67909db3b6219f168907f0552550bf82edb487"
AWASES_PATH = "step 1/data/2-filtered-data.csv"
AWASES_BLOB_SHA = "f6d08aaaadfbc834d9556b83167102381d72db14"
```

Parse only allow-listed chemistry/provenance columns. `process_material` maps to target label/formula candidate; non-empty reactant A-D values become exact source labels with roles `reactant-a` through `reactant-d`.

- [ ] **Step 4: Implement DOI resolution and cache**

Use `urllib.request` only inside this tool. Crossref first, OpenAlex second. Cache canonical request results under `--cache-dir` by SHA256 URL key. Do not persist abstracts/full text in canonical evidence.

- [ ] **Step 5: Implement fallback search over unmatched material identities**

Queries combine canonical formula/name with `atomic layer deposition`, `plasma-enhanced atomic layer deposition`, `PEALD`, `molecular layer deposition`, and hybrid terminology. A hit stays R1 unless direct target + full reactant labels can be established without inference.

- [ ] **Step 6: Test cache replay and deterministic artifacts GREEN**

Second refresh from cache must succeed with network disabled and produce byte-identical artifacts.

- [ ] **Step 7: Commit**

`git commit -m "feat: add structured recipe evidence refresh"`

---

### Task 3: Canonical evidence ledger and offline audit

**Files:**
- Create: `tools/audit_recipe_evidence.py`
- Create: `tests/test_recipe_evidence_audit.py`
- Create: `recipes/evidence/process-evidence.json`
- Create: `recipes/evidence/source-manifest.json`
- Create: `recipes/evidence/acquisition-audit.json`

**Interfaces:**
- schemas: `ald-recipe-evidence/1`, `ald-recipe-evidence-manifest/1`, `ald-recipe-evidence-audit/1`
- CLI: `python tools/audit_recipe_evidence.py [--check]`

- [ ] **Step 1: Write RED invariants**

Reject selected R1, duplicate selected targets, selected historical target, missing stable direct publication, manifest digest mismatch, generated recipe/evidence mismatch, and any forbidden operational field.

- [ ] **Step 2: Implement canonical JSON artifacts**

Sorted keys, compact separators, UTF-8, one trailing newline. Initial artifacts may be valid `refresh_not_yet_run` state but may not claim evidence exhaustion.

- [ ] **Step 3: Implement baseline/historical separation**

Pre-expansion targets are recipe entries whose `recipe_origin` is absent or not `evidence-expansion` so generated recipes never bootstrap themselves as historical coverage.

- [ ] **Step 4: GREEN and commit**

`python -m pytest tests/test_recipe_evidence_audit.py -q`

---

### Task 4: Deterministic expansion recipe generator

**Files:**
- Create: `tools/build_recipe_expansion.py`
- Create: `tests/test_recipe_expansion.py`
- Modify: `tools/build_compound_catalog.py`
- Modify: `tests/test_compound_catalog.py`

**Interfaces:**
- `build_recipe(record) -> dict[str, object]`
- `recipe_category(record) -> str`
- `recipe_filename(record) -> str`
- `expected_expansion_files(evidence) -> dict[Path, bytes]`
- CLI: `python tools/build_recipe_expansion.py [--check]`

- [ ] **Step 1: Write RED tests for thermal/plasma/MLD/hybrid**

Assert exact target/reactant/source linkage, `recipe_origin="evidence-expansion"`, exact `evidence_record_id`, no literature conditions, unique target, and successful `ald_core.validate_recipe` + `ald_core.compile_recipe`.

- [ ] **Step 2: Implement one fixed synthetic template**

Use the existing simulation notice verbatim. Executable values never vary by publication or reported conditions; only the number/order of synthetic exposure slots changes to include all selected reactants.

- [ ] **Step 3: Preserve source-label semantics in legacy recipe schema**

If canonical identity exists, recipe precursor `name`/`formula` use it. Otherwise both display/token fields use the exact source label and metadata records that the identity mode is `source-label`; user-facing chemistry output must label it accordingly.

- [ ] **Step 4: Route to existing category directories**

MLD/hybrid -> `molecular_layer_deposition` where appropriate; oxides/nitrides/chalcogenides/metals/other binaries/ternaries route to existing directories; uncertain but valid cyclic chemistry -> `research`. Create no new category directories.

- [ ] **Step 5: Extend compound catalog additively**

Carry optional `process_family`, `recipe_origin`, `evidence_record_id` when present. Historical entries retain existing semantics.

- [ ] **Step 6: Implement exact-tree `--check`, GREEN, commit**

Fail for missing/stale/orphan expansion recipe, historical target collision, or nonselected evidence.

---

### Task 5: Read-only chemistry projection and search

**Files:**
- Create: `ald_chemistry.py`
- Create: `tests/test_chemistry_catalog.py`
- Modify: `pyproject.toml`

**Interfaces:**

```python
load_chemistry_catalog(recipe_catalog_path, evidence_path=None, material_catalog_path=None)
search_chemistries(entries, text, *, limit=20)
resolve_chemistries(entries, query)
filter_chemistries(entries, *, process_family=None, element=None, precursor=None, evidence=None, origin=None, limit=50)
chemistry_sources(entries, query)
chemistry_report(entries, material_count=8000)
```

- [ ] **Step 1: Write RED projection tests**

Fixtures: two historical HfO2 variants, one expansion recipe, one identity-only material. Expansion evidence joins by exact evidence ID.

- [ ] **Step 2: Implement allow-list projection only**

Return target, process family, reactant source labels, optional canonical identity, evidence grade, source references, origin, recipe ID/path. Never read/copy simulator instructions or executable values into chemistry output.

- [ ] **Step 3: Implement deterministic search/filter/report**

Search formula/name/reactant labels/canonical identities/publication IDs/recipe IDs. Exact target matches rank first. Report historical/expansion counts, unique targets, process-family/evidence distributions, recipe-backed share, and identity-only remainder.

- [ ] **Step 4: GREEN and commit**

`git commit -m "feat: add chemistry exploration projection"`

---

### Task 6: `ald-master chemistry` CLI and material cross-links

**Files:**
- Modify: `ald_master/__init__.py`
- Create: `tests/test_chemistry_cli.py`
- Modify: `tests/test_material_cli.py`

**Interfaces:**
- global `--recipe-evidence PATH`
- `chemistry search TEXT [--process-family ...] [--precursor ...] [--evidence R2|R3] [--origin historical|expansion] [--limit N] [--json]`
- `chemistry show TARGET_OR_RECIPE [--json]`
- `chemistry list [--process-family ...] [--element ...] [--precursor ...] [--evidence ...] [--origin ...] [--limit N] [--json]`
- `chemistry sources TARGET_OR_RECIPE [--json]`
- `chemistry report [--json]`

- [ ] **Step 1: Write parser/dispatch RED tests**
- [ ] **Step 2: Implement commands over `ald_chemistry` only**
- [ ] **Step 3: Human `show` output separates source label from canonical identity**
- [ ] **Step 4: `materials show` adds recipe-chemistry cross-link without changing compatibility semantics**
- [ ] **Step 5: Add `Explore recipe chemistries` to interactive top menu**
- [ ] **Step 6: GREEN and commit**

Human chemistry output must state that process chemistry/provenance is literature-backed while simulator conditions are synthetic. No operating-condition values are printed.

---

### Task 7: Full acquisition sweep and canonical data promotion

**Files:**
- Replace initial evidence artifacts with real frozen output
- Create deterministic expansion recipes under `recipes/compounds/*/`
- Regenerate `recipes/compounds/catalog.json`
- Rebuild `materials/catalog.json` only when exact recipe-link enrichment requires it

- [ ] **Step 1: Acquire pinned AtomicLimits-derived source and verify blob SHA**
- [ ] **Step 2: Sweep every identity not already recipe-backed**
- [ ] **Step 3: Resolve direct publications and run fallback discovery for unmatched identities**
- [ ] **Step 4: Grade/reject/select every candidate deterministically**
- [ ] **Step 5: Inspect audit counts before recipe promotion**
- [ ] **Step 6: Generate recipes and canonical catalogs**
- [ ] **Step 7: Commit frozen evidence + generated data**

Stopping condition is evidence exhaustion, not a round recipe count.

---

### Task 8: Documentation, CI, and exact-head verification

**Files:**
- Create: `docs/recipe-chemistry.md`
- Modify: `README.md`
- Modify: `docs/material-catalog.md`
- Create: `tests/test_recipe_evidence_integration.py`
- Modify existing CI workflows only as needed for offline canonical checks

- [ ] **Step 1: Document primary user path**

```bash
ald-master chemistry search HfO2
ald-master chemistry show HfO2
ald-master chemistry sources HfO2
ald-master chemistry list --process-family plasma-ald --limit 50
ald-master chemistry report
```

Explain: `materials = identity`, `chemistry = literature-backed chemistry/provenance`, existing recipe workflow = synthetic execution.

- [ ] **Step 2: Add integration invariants**

Exactly one selected ledger record per expansion recipe; zero selected R1; zero expansion duplicate targets; zero overlap with historical targets; exact source-reference linkage; all generated recipes compile; canonical rebuilds match.

- [ ] **Step 3: Run exact offline checks**

```bash
python tools/audit_recipe_evidence.py --check
python tools/build_recipe_expansion.py --check
python tools/build_compound_catalog.py --check
python tools/build_material_catalog.py --check --target-count 8000
git diff --check origin/feature/material-catalog-8000...HEAD
python -m pytest -q
```

- [ ] **Step 4: Smoke-test user-facing commands**

Confirm chemistry commands expose chemistry/provenance and no simulator conditions.

- [ ] **Step 5: Verify native HLS and Product MP4 workflows on exact feature SHA**
- [ ] **Step 6: Review final diff for fabricated chemistry, operational leakage, R1 generation, duplicate targets, and unpinned provenance**
- [ ] **Step 7: Open stacked PR on `feature/material-catalog-8000` only after exact-head verification; do not merge without explicit user instruction**
