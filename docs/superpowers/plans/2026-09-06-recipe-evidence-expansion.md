# Recipe Evidence Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize distinct recipe-backed materials with direct ALD/PEALD/MLD/hybrid chemistry evidence, then make those chemistries easy to search, inspect, source-check, and run through Substitute's existing synthetic simulator workflow.

**Architecture:** Build a reusable evidence core that normalizes literature chemistry into deterministic R1/R2/R3 records, a network-capable refresh layer that ingests structured AtomicLimits-derived data and resolves publications, and an offline deterministic generator that emits one selected new recipe per previously unbacked material. Add a read-only `ald_chemistry.py` projection plus `ald-master chemistry ...` commands so users can explore target/reactant/provenance information without exposing synthetic operating parameters.

**Tech Stack:** Python 3.10+, standard library (`argparse`, `csv`, `hashlib`, `json`, `pathlib`, `urllib`), existing `ald_core`, `ald_materials`, `pytest`; GitHub Actions only for explicit network acquisition/verification helpers.

**Spec:** `docs/superpowers/specs/2026-09-06-recipe-evidence-expansion-design.md` and `docs/superpowers/specs/2026-09-06-recipe-chemistry-exploration-design.md`

## Global Constraints

- Preserve every pre-existing recipe file, recipe ID, and recipe path; the one-best rule applies only to newly generated expansion recipes.
- Only direct R2/R3 chemistry evidence may generate a new recipe; R1, ambiguous, inferred-analogue, review-only, and non-cyclic deposition records never generate recipes.
- Literature controls only target identity, precursor/co-reactant identities, process-family classification, and publication provenance.
- Never import or expose literature process temperature, pressure, pulse/dose timing, purge timing, growth rate, plasma power/bias, flow, hardware configuration, reactor geometry, or handling instructions.
- Generated executable values remain fixed synthetic simulator defaults and keep `physical_fabrication_mapping: false` plus the existing simulation-only notice.
- Normal runtime, normal tests, deterministic builders, and canonical CI checks are offline; only `tools/refresh_recipe_evidence.py` may use the network.
- AtomicLimits-derived structured data is the primary bulk discovery input. The refresh manifest must pin the upstream repository/ref/blob digest used. Do not scrape rendered AtomicLimits UI pages.
- Crossref is the preferred DOI metadata resolver; OpenAlex is the secondary resolver/fallback scholarly discovery source.
- The 8,000-material identity catalog is the search universe, not a claim that all 8,000 have ALD/MLD recipes.
- Material identity, process chemistry evidence, compatibility evidence, and simulator execution remain separate concepts.

---

### Task 1: Evidence normalization, grading, and deterministic selection core

**Files:**
- Create: `ald_recipe_evidence.py`
- Create: `tests/test_recipe_evidence.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `ald_materials.reduce_formula(formula)` for fixed-formula normalization.
- Produces:
  - `canonical_json_bytes(value: object) -> bytes`
  - `normalize_doi(value: str) -> str`
  - `normalize_process_family(value: str) -> str`
  - `normalize_reactants(raw: Sequence[Mapping[str, object]]) -> list[dict[str, str]]`
  - `chemistry_key(target_reduced_formula: str, process_family: str, reactants: Sequence[Mapping[str, str]]) -> str`
  - `evidence_id(record: Mapping[str, object]) -> str`
  - `validate_evidence_record(record: Mapping[str, object]) -> dict[str, object]`
  - `selection_sort_key(record: Mapping[str, object]) -> tuple[object, ...]`
  - `select_best_candidates(records: Sequence[Mapping[str, object]], existing_target_formulas: set[str]) -> list[dict[str, object]]`

- [ ] **Step 1: Write normalization and validation tests**

Create tests that prove DOI canonicalization, formula reduction, deterministic reactant ordering, process-family validation, evidence-grade validation, and rejection of operational-condition fields.

```python
from ald_recipe_evidence import (
    chemistry_key,
    normalize_doi,
    validate_evidence_record,
)


def direct_record(**overrides):
    record = {
        "target_material": "hafnium dioxide",
        "target_formula": "HfO2",
        "process_family": "thermal-ald",
        "reactants": [
            {"name": "hafnium tetrachloride", "formula": "HfCl4", "role": "metal-source"},
            {"name": "water", "formula": "H2O", "role": "co-reactant"},
        ],
        "publications": [{"type": "doi", "identifier": "https://doi.org/10.1234/example", "direct": True}],
        "discovery_sources": ["atomiclimits"],
        "evidence_grade": "R2",
        "selection_status": "candidate",
    }
    record.update(overrides)
    return record


def test_normalize_doi_removes_url_prefix_and_lowercases():
    assert normalize_doi(" HTTPS://DOI.ORG/10.1234/ABC ") == "10.1234/abc"


def test_validation_rejects_operational_fields():
    record = direct_record(process_temperature=250)
    try:
        validate_evidence_record(record)
    except ValueError as error:
        assert "operational" in str(error).lower()
    else:
        raise AssertionError("operational field was accepted")


def test_chemistry_key_is_reactant_order_independent():
    record = direct_record()
    reactants = record["reactants"]
    assert chemistry_key("HfO2", "thermal-ald", reactants) == chemistry_key(
        "HfO2", "thermal-ald", list(reversed(reactants))
    )
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python -m pytest tests/test_recipe_evidence.py -q
```

Expected: import failure because `ald_recipe_evidence.py` does not exist.

- [ ] **Step 3: Implement the evidence core**

Define exact constants:

```python
EVIDENCE_SCHEMA = "ald-recipe-evidence/1"
ALLOWED_PROCESS_FAMILIES = {"thermal-ald", "plasma-ald", "mld", "hybrid"}
ALLOWED_GRADES = {"R1", "R2", "R3"}
ALLOWED_STATUSES = {"candidate", "selected", "rejected", "covered-existing"}
FORBIDDEN_OPERATIONAL_KEYS = {
    "process_temperature", "temperature", "temperature_c", "pressure", "pressure_pa",
    "pulse", "pulse_time", "dose", "dose_time", "purge", "purge_time",
    "growth_rate", "growth_per_cycle", "plasma_power", "plasma_bias", "flow",
    "flow_sccm", "hardware", "reactor", "reactor_geometry", "handling_notes",
}
```

Canonical record validation must:
- reduce the target formula through `ald_materials.reduce_formula`;
- require at least two target elements;
- normalize DOI URL prefixes and case;
- require nonempty reactant `name`, `formula`, and `role` for R2/R3;
- sort reactants by `(role.casefold(), formula.casefold(), name.casefold())`;
- require at least one direct publication for R2/R3;
- derive `R3` only when direct evidence is corroborated by `atomiclimits` or a second independent direct publication;
- reject forbidden operational keys recursively at every mapping depth;
- create stable IDs as `ev-<formula-slug>-<sha256-prefix-12>` over the normalized target/process/reactants/publication identifiers.

Selection ordering must encode the approved policy exactly:

```python
GRADE_RANK = {"R3": 0, "R2": 1, "R1": 2}

def selection_sort_key(record):
    return (
        GRADE_RANK[record["evidence_grade"]],
        0 if record["reactant_identities_complete"] else 1,
        -int(record["independent_direct_publication_count"]),
        len(record["reactants"]),
        0 if record["stable_publication_identifier_count"] else 1,
        record["chemistry_key"],
        record["evidence_id"],
    )
```

`select_best_candidates` must mark all existing target formulas `covered-existing`, select at most one R2/R3 candidate per remaining reduced formula, and preserve deterministic rejection reasons on every non-selected record.

- [ ] **Step 4: Add selection tests**

Test R3 > R2, fewer reactants after evidence tie, existing-target skip, R1 never selected, and one selected record per target.

- [ ] **Step 5: Add the module to packaging and run GREEN**

Add `"ald_recipe_evidence"` to `pyproject.toml` `py-modules` and run:

```bash
python -m pytest tests/test_recipe_evidence.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add ald_recipe_evidence.py tests/test_recipe_evidence.py pyproject.toml
git commit -m "feat: add recipe evidence selection core"
```

---

### Task 2: Structured AtomicLimits-derived acquisition adapters

**Files:**
- Create: `tools/refresh_recipe_evidence.py`
- Create: `tests/fixtures/recipe_evidence/awases_sample.csv`
- Create: `tests/fixtures/recipe_evidence/crossref_work.json`
- Create: `tests/fixtures/recipe_evidence/openalex_work.json`
- Create: `tests/test_recipe_evidence_refresh.py`

**Interfaces:**
- Consumes Task 1 normalizers.
- Produces:
  - `parse_awases_rows(stream: TextIO) -> list[dict[str, object]]`
  - `normalize_crossref_work(payload: Mapping[str, object]) -> dict[str, object]`
  - `normalize_openalex_work(payload: Mapping[str, object]) -> dict[str, object]`
  - `resolve_publication(candidate, crossref_client, openalex_client) -> dict[str, object]`
  - `build_refresh_artifacts(...) -> tuple[dict[str, object], dict[str, object], dict[str, object]]`

- [ ] **Step 1: Create a minimal structured-source fixture and failing parser tests**

The AWASES fixture must contain only non-operational fields required by the adapter, including `reference_doi`, target/material identity, reactant identities, and process classification. The parser test must prove that unknown columns are ignored but operational-looking columns are never copied into output records.

```python
def test_awases_adapter_never_preserves_operational_conditions():
    rows = parse_awases_rows(io.StringIO(AWASES_FIXTURE_WITH_TEMPERATURE_COLUMN))
    serialized = json.dumps(rows).lower()
    assert "temperature" not in serialized
    assert "pressure" not in serialized
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
python -m pytest tests/test_recipe_evidence_refresh.py -q
```

- [ ] **Step 3: Implement the structured source adapter**

Use `csv.DictReader` with explicit header aliases and fail closed when the target, reactant, or publication-identifier families cannot be resolved. Never infer chemistry from a chemical family name alone.

The upstream default must be pinned to the public structured source rather than AtomicLimits rendered HTML:

```python
AWASES_REPOSITORY = "jd-coderepos/awases-ald"
AWASES_PATH = "step 1/data/2-filtered-data.csv"
ATOMICLIMITS_DATABASE_DOI = "10.6100/alddatabase"
```

The refresh CLI must require an explicit upstream `--awases-ref` for production refreshes so the manifest records a stable ref/commit rather than silently using a moving `main` snapshot.

- [ ] **Step 4: Implement publication resolvers with standard-library HTTP**

Use `urllib.request` only in the refresh tool. Crossref requests resolve known DOIs. OpenAlex is fallback for title/DOI resolution and searches over currently unmatched materials. Add deterministic request caching under a user-supplied `--cache-dir`; cached response filenames are SHA256 of the canonical request URL.

No network function may be imported by `ald_recipe_evidence.py`, `ald_chemistry.py`, recipe builders, or CLI runtime modules.

- [ ] **Step 5: Test deterministic normalization and cache replay**

Mock HTTP by injecting fetch callables. Tests must show two identical refreshes from fixtures produce byte-identical normalized artifacts and that the second run can succeed from cache with the network callable configured to fail.

- [ ] **Step 6: Run GREEN and commit**

```bash
python -m pytest tests/test_recipe_evidence_refresh.py -q
git add tools/refresh_recipe_evidence.py tests/fixtures/recipe_evidence tests/test_recipe_evidence_refresh.py
git commit -m "feat: add structured recipe evidence refresh"
```

---

### Task 3: Canonical evidence ledger and offline audit

**Files:**
- Create: `tools/audit_recipe_evidence.py`
- Create: `tests/test_recipe_evidence_audit.py`
- Create initially with test-sized valid content, later replaced by the bulk refresh: `recipes/evidence/process-evidence.json`
- Create: `recipes/evidence/source-manifest.json`
- Create: `recipes/evidence/acquisition-audit.json`

**Interfaces:**
- Consumes Task 1 validation/selection functions and material/recipe catalogs.
- Produces `audit_evidence(evidence, manifest, acquisition_audit, recipe_catalog, material_catalog) -> dict[str, object]` and a CLI returning 0 only when all invariants hold.

- [ ] **Step 1: Write audit RED tests**

Tests must reject:
- R1 with `selection_status=selected`;
- duplicate selected reduced formulas;
- selected target already covered by an existing recipe;
- selected record without a direct stable publication identifier;
- generated recipe evidence ID missing from the ledger;
- source-manifest digest mismatch;
- any forbidden operational key anywhere in the evidence JSON.

- [ ] **Step 2: Implement canonical artifact structure**

Use these top-level schemas:

```json
{"schema":"ald-recipe-evidence/1","records":[]}
{"schema":"ald-recipe-evidence-manifest/1","sources":{},"digests":{}}
{"schema":"ald-recipe-evidence-audit/1","counts":{},"rejections":{}}
```

Write canonical JSON as sorted keys, compact separators, UTF-8, one trailing newline.

- [ ] **Step 3: Implement audit linkage**

The audit must derive pre-expansion target formulas from recipe entries whose `recipe_origin` is absent or not `evidence-expansion`, so generated recipes do not make themselves appear pre-existing on later checks.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_recipe_evidence_audit.py -q
python tools/audit_recipe_evidence.py
git add tools/audit_recipe_evidence.py tests/test_recipe_evidence_audit.py recipes/evidence
git commit -m "feat: add offline recipe evidence audit"
```

---

### Task 4: Deterministic expansion recipe generator

**Files:**
- Create: `tools/build_recipe_expansion.py`
- Create: `tests/test_recipe_expansion.py`
- Modify: `tools/build_compound_catalog.py`
- Modify: `tests/test_compound_catalog.py`

**Interfaces:**
- Consumes selected R2/R3 evidence records.
- Produces:
  - `recipe_category(record) -> str`
  - `recipe_filename(record) -> str`
  - `build_recipe(record) -> dict[str, object]`
  - `expected_expansion_files(evidence) -> dict[Path, bytes]`
  - CLI `python tools/build_recipe_expansion.py [--check]`

- [ ] **Step 1: Write generator RED tests**

Test one representative thermal ALD record, one plasma record, one MLD record, and one hybrid record. Assert:
- target/reactant/source metadata follows evidence exactly;
- recipe has `recipe_origin="evidence-expansion"` and exact `evidence_record_id`;
- literature operational fields cannot influence generated executable values;
- two records with same target cannot both generate;
- generated recipe validates and compiles.

- [ ] **Step 2: Define one synthetic simulator template**

Use fixed values independent of literature and evidence source. Keep the existing repository safety notice exactly:

```text
Literature-recognition chemistry only. Executable ordering and numbers are synthetic simulator values; not a physical fabrication recipe or machine-control instruction.
```

The generator may vary only the number/order of synthetic exposures required to include every selected reactant. It must not branch synthetic numbers by publication, target material, process family, or reported conditions.

- [ ] **Step 3: Map process families to existing recipe directories**

Use deterministic material-class-first mapping:
- MLD/hybrid organic-inorganic records -> `molecular_layer_deposition` unless explicitly multicomponent inorganic;
- oxide -> `oxides`;
- nitride -> `nitrides`;
- sulfide/selenide/telluride -> `chalcogenides`;
- elemental metal target -> `metals`;
- carbide/boride/silicide/phosphide/other binary inorganic -> `carbides_and_other_inorganics`;
- three-or-more-element inorganic -> `ternary_and_multicomponent`;
- fallback uncertain but valid research target -> `research`.

Do not create new recipe category directories in this project.

- [ ] **Step 4: Make compound catalog carry additive expansion metadata**

`tools/build_compound_catalog.py` must add optional entry fields only when present in recipe metadata:

```python
for key in ("process_family", "recipe_origin", "evidence_record_id"):
    if key in metadata:
        entry[key] = metadata[key]
```

Existing catalog entries remain byte-semantically compatible apart from the global regenerated catalog ordering/content required by new recipes.

- [ ] **Step 5: Implement exact-tree `--check` behavior**

`--check` must fail if:
- a selected evidence record has no expected recipe;
- an expected recipe differs byte-for-byte;
- an expansion recipe exists with no selected evidence record;
- a selected record collides with a historical recipe target.

- [ ] **Step 6: Run GREEN and commit**

```bash
python -m pytest tests/test_recipe_expansion.py tests/test_compound_catalog.py -q
python tools/build_recipe_expansion.py --check
python tools/build_compound_catalog.py --check
git add tools/build_recipe_expansion.py tools/build_compound_catalog.py tests/test_recipe_expansion.py tests/test_compound_catalog.py recipes/compounds
git commit -m "feat: generate evidence-backed expansion recipes"
```

---

### Task 5: Read-only chemistry projection library

**Files:**
- Create: `ald_chemistry.py`
- Create: `tests/test_chemistry_catalog.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces exactly:

```python
load_chemistry_catalog(recipe_catalog_path, evidence_path=None, material_catalog_path=None) -> list[dict[str, object]]
search_chemistries(entries, text, *, limit=20) -> list[dict[str, object]]
resolve_chemistries(entries, query) -> list[dict[str, object]]
filter_chemistries(entries, *, process_family=None, chemistry_family=None, element=None, precursor=None, evidence=None, origin=None, limit=50) -> list[dict[str, object]]
chemistry_sources(entries, query) -> list[dict[str, object]]
chemistry_report(entries, material_count=8000) -> dict[str, object]
```

- [ ] **Step 1: Write projection/search RED tests**

Fixtures must include:
- two historical HfO2 variants;
- one expansion-selected TiN chemistry with evidence ID;
- one identity-only material in the material catalog.

Assert `resolve_chemistries("HfO2")` returns both historical variants, exact target formula ranks before precursor substring hits, and expansion entries join evidence by exact ID.

- [ ] **Step 2: Implement projection without reading simulator instructions**

Input data comes from `recipes/compounds/catalog.json`, optional evidence ledger, and optional material catalog. Historical entries get:

```python
{"origin": "historical", "evidence_grade": "historical", "process_family": "historical-unspecified"}
```

Expansion entries must resolve their `evidence_record_id` exactly or raise `ValueError`.

- [ ] **Step 3: Enforce non-operational public projection**

Every returned chemistry entry is allow-list built. Do not copy arbitrary recipe metadata. Tests serialize projection output and assert absence of `temperature`, `pressure`, `dose`, `purge`, `power`, `flow`, and `hardware` keys.

- [ ] **Step 4: Implement search/filter/report deterministically**

Search ranking follows the UX addendum. Filter ordering is `(target_reduced_formula, recipe_id)`. `chemistry_report` counts total recipes, unique targets, origins, process families, evidence grades, unique reactant identities, unique publication IDs, recipe-backed share, and identity-only remainder.

- [ ] **Step 5: Package, run GREEN, commit**

```bash
python -m pytest tests/test_chemistry_catalog.py -q
git add ald_chemistry.py tests/test_chemistry_catalog.py pyproject.toml
git commit -m "feat: add chemistry exploration projection"
```

---

### Task 6: `ald-master chemistry` CLI and material cross-link

**Files:**
- Modify: `ald_master/__init__.py`
- Create: `tests/test_chemistry_cli.py`
- Modify: `tests/test_material_cli.py`

**Interfaces:**
- New global override: `--recipe-evidence PATH`.
- New commands:
  - `chemistry search`
  - `chemistry show`
  - `chemistry list`
  - `chemistry sources`
  - `chemistry report`

- [ ] **Step 1: Write CLI RED tests**

Use monkeypatched catalog/evidence/material paths and assert:

```python
assert ald_master.main(["chemistry", "search", "HfO2", "--json"]) == 0
assert ald_master.main(["chemistry", "show", "HfO2", "--json"]) == 0
assert ald_master.main(["chemistry", "list", "--process-family", "plasma-ald", "--json"]) == 0
assert ald_master.main(["chemistry", "sources", "HfO2", "--json"]) == 0
assert ald_master.main(["chemistry", "report", "--json"]) == 0
```

Also assert unknown `show` returns 2 and empty search/list returns 1.

- [ ] **Step 2: Extend global path parsing**

Add `--recipe-evidence` beside the existing `--materials-catalog`, `--compatibility-snapshot`, and evidence overrides. Preserve legacy core invocation behavior.

- [ ] **Step 3: Implement chemistry parser and dispatcher**

Human-readable output must show only the allow-listed chemistry projection. JSON output serializes projection records, never raw recipes.

- [ ] **Step 4: Add material-show cross-link**

For human-readable `materials show`, when linked recipe paths exist, append:

```text
chemistry: N recipe-backed chemistry variant(s); use `ald-master chemistry show <formula>`
```

JSON additions are additive only; retain existing keys and semantics.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_chemistry_cli.py tests/test_material_cli.py -q
git add ald_master/__init__.py tests/test_chemistry_cli.py tests/test_material_cli.py
git commit -m "feat: add ald-master chemistry commands"
```

---

### Task 7: Interactive chemistry exploration

**Files:**
- Modify: `ald_master/__init__.py`
- Create or modify: `tests/test_ald_master_interactive.py` using the repository's existing interactive test pattern.

**Interfaces:**
- Adds `Explore recipe chemistries` before compatibility operations in the top-level interactive menu.

- [ ] **Step 1: Write interactive RED tests**

Patch `input()` with deterministic answer queues and verify:
- selecting chemistry exploration opens search/browse;
- selecting an item prints target/reactants/sources only;
- choosing `Run recipe workflow` delegates to the existing run path using the selected recipe file;
- `Back` returns without mutating anything.

- [ ] **Step 2: Implement the flow as thin UI over `ald_chemistry`**

Do not duplicate search or resolution logic in the menu code. Use the same projection and dispatcher data used by CLI commands.

- [ ] **Step 3: Test that interactive chemistry output excludes operating fields**

Capture stdout and assert no simulator temperature, pressure, dose, purge, power, or flow values appear.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_ald_master_interactive.py tests/test_chemistry_cli.py -q
git add ald_master/__init__.py tests/test_ald_master_interactive.py
git commit -m "feat: add interactive chemistry explorer"
```

---

### Task 8: Execute the full evidence sweep and promote only defensible recipes

**Files:**
- Modify with real frozen output: `recipes/evidence/process-evidence.json`
- Modify: `recipes/evidence/source-manifest.json`
- Modify: `recipes/evidence/acquisition-audit.json`
- Create many deterministic recipe files under existing `recipes/compounds/*/`
- Regenerate: `recipes/compounds/catalog.json`
- Regenerate: `materials/catalog.json` only if exact recipe links require its deterministic rebuild.
- Temporary helper workflow may be created only on a helper branch, not left on the feature branch.

**Interfaces:**
- Uses the explicit network refresh tool and offline builders from Tasks 1–4.

- [ ] **Step 1: Pin the structured AtomicLimits-derived upstream snapshot**

Resolve the AWASES repository commit containing `step 1/data/2-filtered-data.csv`, record repository, commit/ref, path, blob SHA, license, AtomicLimits database DOI, and fetched-content SHA256 in `source-manifest.json`.

The manifest must make clear that AWASES is a transport/structured derivative and AtomicLimits is the primary process-discovery provenance.

- [ ] **Step 2: Run the primary AtomicLimits-derived sweep over all unmatched material identities**

For each normalized target, retain only candidate chemistry fields and publication identifiers. Do not persist unrelated full text or operating-condition columns.

- [ ] **Step 3: Resolve publication metadata and grade primary candidates**

Resolve DOIs through Crossref first, OpenAlex second. Candidate records without direct stable publication evidence remain R1/rejected.

- [ ] **Step 4: Run fallback scholarly discovery for every still-unbacked material**

Construct deterministic queries from canonical material names/formulas plus the approved process phrases. Accept only records that pass the same direct chemistry validator; a search hit alone is never R2.

If direct full chemistry cannot be extracted from available structured/public metadata without guessing, record `insufficient-direct-chemistry` and move on.

- [ ] **Step 5: Select one best candidate per new target and generate recipes**

Run:

```bash
python tools/audit_recipe_evidence.py
python tools/build_recipe_expansion.py
python tools/build_compound_catalog.py
python tools/build_material_catalog.py --target-count 8000
```

- [ ] **Step 6: Inspect the acquisition audit before promotion**

The audit must include real counts for:
- 8,000 identities examined;
- historical recipe-backed targets;
- primary candidates;
- fallback candidates;
- R3/R2 selected;
- all rejection reasons;
- new distinct targets added;
- process-family additions;
- final executable recipe count;
- remaining identity-only count.

Reject the sweep if the count grows because duplicate target variants, R1 records, or unresolved chemistry were promoted.

- [ ] **Step 7: Commit the frozen evidence + generated recipe data**

```bash
git add recipes/evidence recipes/compounds materials/catalog.json materials/build-audit.json materials/source-manifest.json
git commit -m "data: add audited literature-backed recipe expansion"
```

---

### Task 9: User documentation for chemistry exploration

**Files:**
- Create: `docs/recipe-chemistry.md`
- Modify: `README.md`
- Modify: `docs/material-catalog.md`

**Interfaces:**
- Documents the three-layer workflow without implying fabrication readiness.

- [ ] **Step 1: Add the primary user path**

README quick discovery must lead with:

```bash
ald-master chemistry search HfO2
ald-master chemistry show HfO2
ald-master chemistry sources HfO2
ald-master chemistry list --process-family plasma-ald --limit 50
ald-master chemistry report
```

Then explain:

```text
materials  = known material identities
chemistry  = literature-backed recipe chemistry/provenance
run        = synthetic simulator execution
```

- [ ] **Step 2: Document evidence grades and historical behavior**

State plainly that historical recipes preserve their original sources and are labeled `historical`; new generated recipes require R2/R3; R1 never generates.

- [ ] **Step 3: Document refresh vs offline use**

Show canonical checks and make clear that normal users do not need network access to browse chemistry or run the simulator.

- [ ] **Step 4: Add documentation assertions where repository tests support them and commit**

```bash
git add README.md docs/recipe-chemistry.md docs/material-catalog.md
git commit -m "docs: explain chemistry exploration workflow"
```

---

### Task 10: Exact-head verification and review readiness

**Files:**
- No product files unless verification reveals defects.
- Any temporary verification workflow must live on a helper branch and must not remain in the final feature diff.

**Interfaces:**
- Verifies the exact final SHA of `feature/recipe-evidence-expansion`.

- [ ] **Step 1: Run all deterministic checks**

```bash
python tools/audit_recipe_evidence.py
python tools/build_recipe_expansion.py --check
python tools/build_compound_catalog.py --check
python tools/build_material_catalog.py --check --target-count 8000
git diff --check origin/feature/material-catalog-8000...HEAD
```

Expected: all exit 0.

- [ ] **Step 2: Run focused suites**

```bash
python -m pytest \
  tests/test_recipe_evidence.py \
  tests/test_recipe_evidence_refresh.py \
  tests/test_recipe_evidence_audit.py \
  tests/test_recipe_expansion.py \
  tests/test_chemistry_catalog.py \
  tests/test_chemistry_cli.py \
  tests/test_material_cli.py \
  tests/test_compound_catalog.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the complete repository suite with the same FFmpeg prerequisites as native CI**

```bash
python -m pytest -q
```

Expected: all tests pass; record the exact test count and duration.

- [ ] **Step 4: Verify user-facing smoke commands**

```bash
ald-master chemistry report
ald-master chemistry search HfO2 --json
ald-master chemistry show HfO2 --json
ald-master chemistry sources HfO2 --json
ald-master materials show HfO2
```

Expected: chemistry/provenance visible, no operating-condition values printed by chemistry commands.

- [ ] **Step 5: Verify native HLS and Product MP4 workflows on the exact feature SHA**

Require both repository-native workflows to complete successfully before presenting the branch as review-ready.

- [ ] **Step 6: Review the final diff for scientific-boundary regressions**

Specifically inspect for:
- fabricated target/reactant chemistry;
- copied literature operating conditions;
- generated duplicates of historical targets;
- generated R1 recipes;
- unpinned source provenance;
- chemistry CLI exposing raw recipe instructions;
- accidental compatibility inference from material/recipe presence.

- [ ] **Step 7: Open a stacked pull request only after exact-head verification**

Base the PR on `feature/material-catalog-8000` while PR #20 remains unmerged. Include exact acquisition counts, evidence-grade counts, generated distinct-material count, verification commands/results, and the explicit statement that no merge was performed.
