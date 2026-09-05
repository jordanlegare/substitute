# Compatibility Evidence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, deterministic evidence graph that exhaustively evaluates every catalog precursor pair and directed base-material interface, then rank 2–6 precursor candidate sets with auditable evidence levels and a shortened `ald-master` interactive flow.

**Architecture:** Add a focused `ald_compatibility.py` module that owns entity normalization, evidence extraction, pair/interface scoring, snapshot serialization, queries, and bounded beam ranking. `ald_master.py` remains the CLI/UI orchestration layer and imports that module. Model weights and curated evidence live in versioned JSON files so ranking behavior is reproducible and reviewable.

**Tech Stack:** Python 3.10+, standard library (`argparse`, `dataclasses`, `hashlib`, `itertools`, `json`, `math`, `pathlib`), pytest. No new runtime dependency, no network dependency, no FFmpeg dependency for compatibility features.

**Spec:** `docs/superpowers/specs/2026-09-05-compatibility-evidence-engine-design.md`

## Global Constraints

- Compatibility means evidence support for offline sequential ALD-style simulation research, not physical mixing safety, equipment compatibility, or production readiness.
- Exhaustively emit exactly `n*(n-1)/2` precursor-pair records and `m*(m-1)` directed base-material-interface records.
- Missing evidence is unavailable/unknown, never automatic negative evidence.
- `CONFLICTING` requires explicit negative curated evidence.
- Candidate sets are 2–6 unique precursors and must contain at least one `SOURCE` and one recognized reactant class.
- Candidate generation uses deterministic beam search; it must not brute-force the entire 2–6 combination space.
- All scoring constants live in `compatibility/model-v1.json`.
- Identical catalog/model/override bytes produce byte-identical compatibility snapshots and ranking order.
- Runtime compatibility commands are offline.
- Existing `ald-media-controller` behavior is unchanged.

---

### Task 1: Model files, entity normalization, and catalog indexing

**Files:**
- Create: `compatibility/model-v1.json`
- Create: `compatibility/evidence-overrides.json`
- Create: `ald_compatibility.py`
- Create: `tests/test_ald_compatibility.py`

**Interfaces:**
- Consumes: catalog entries in the same dictionary form returned by `ald_master.load_catalog()`.
- Produces:
  - `load_model(path: Path) -> dict[str, Any]`
  - `load_evidence_overrides(path: Path) -> list[dict[str, Any]]`
  - `normalize_formula(value: str) -> str`
  - `normalize_name(value: str) -> str`
  - `build_precursor_entities(entries: Sequence[dict[str, Any]], model: Mapping[str, Any]) -> list[dict[str, Any]]`
  - `build_material_entities(entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]`
  - `classify_role(role: str, model: Mapping[str, Any]) -> str`

- [ ] **Step 1: Write failing model/normalization tests**

Add tests equivalent to:

```python
def test_normalization_and_duplicate_precursors_are_deterministic(tmp_path):
    entries = [
        sample_entry("r1", [{"id": "A", "name": "water", "formula": "H2O", "role": "oxygen co-reactant"}]),
        sample_entry("r2", [{"id": "A", "name": "Water", "formula": " H2O ", "role": "oxidant"}]),
    ]
    entities = compat.build_precursor_entities(entries, MODEL)
    assert len(entities) == 1
    assert entities[0]["formula"] == "H2O"
    assert entities[0]["roles"] == ["OXIDANT"]
    assert entities == compat.build_precursor_entities(entries, MODEL)
```

Also test malformed model schema, invalid evidence values, stable IDs, role classification, and material composite detection.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

Expected: import/module/function failures because `ald_compatibility.py` and model files do not yet exist.

- [ ] **Step 3: Add deterministic model and empty curated-evidence schemas**

`compatibility/model-v1.json` must include:

```json
{
  "schema": "ald-compatibility-model/1",
  "precursor_weights": {
    "exact_process": 0.25,
    "direct_literature": 0.20,
    "external_thermochemistry": 0.15,
    "role_complementarity": 0.10,
    "surface_sequence": 0.10,
    "physical_property": 0.10,
    "chemistry_analogue": 0.10
  },
  "material_weights": {
    "direct_stack": 0.30,
    "direct_literature": 0.20,
    "external_thermodynamics": 0.20,
    "shared_precursors": 0.10,
    "family_analogue": 0.10,
    "surface_interface": 0.10
  },
  "coverage_unknown_below": 0.15,
  "verdict_thresholds": {"low_support": 45.0, "plausible": 60.0, "supported": 75.0},
  "candidate_weights": {"harmonic": 0.40, "minimum": 0.20, "coverage": 0.15, "roles": 0.15, "known": 0.10},
  "beam_width": 500,
  "default_top": 20,
  "status_reliability": {
    "established": 1.0,
    "literature-grounded": 0.95,
    "literature-grounded-surrogate": 0.90,
    "conceptual-multicomponent-surrogate": 0.60,
    "default": 0.50
  },
  "role_keywords": {
    "OXIDANT": ["oxygen co-reactant", "oxidant", "ozone", "water"],
    "REDUCTANT": ["reducing co-reactant", "reductant", "hydrogen"],
    "CHALCOGEN_REACTANT": ["sulfur co-reactant", "selenium co-reactant", "tellurium co-reactant"],
    "NITROGEN_REACTANT": ["nitrogen co-reactant", "ammonia", "nitrogen reactant"],
    "HALOGEN_REACTANT": ["fluorine co-reactant", "halogen co-reactant"],
    "CARBON_REACTANT": ["carbon co-reactant"],
    "OTHER_REACTANT": ["co-reactant", "reactant"],
    "SOURCE": ["source"]
  }
}
```

`compatibility/evidence-overrides.json` initially contains:

```json
{"schema":"ald-compatibility-evidence/1","records":[]}
```

- [ ] **Step 4: Implement model validation and entity builders**

Use dataclass-free serializable dictionaries for snapshot-facing records. Stable IDs use `sha256(normalized_key.encode()).hexdigest()[:16]` with prefixes `p-` and `m-`.

Formula normalization strips Unicode/ASCII whitespace only. Name normalization uses Unicode NFKC, casefolding, and whitespace collapse. Never attempt speculative stoichiometric canonicalization.

Material entities mark slash-delimited targets as composite evidence containers rather than base nodes when every constituent can later resolve to a base target formula.

- [ ] **Step 5: Run focused tests to GREEN**

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

Expected: entity/model tests pass.

- [ ] **Step 6: Commit**

```bash
git add compatibility/model-v1.json compatibility/evidence-overrides.json ald_compatibility.py tests/test_ald_compatibility.py
git commit -m "feat: add compatibility entity model"
```

---

### Task 2: Exhaustive precursor graph, material interfaces, scoring, and overrides

**Files:**
- Modify: `ald_compatibility.py`
- Modify: `tests/test_ald_compatibility.py`

**Interfaces:**
- Consumes Task 1 entity/model functions.
- Produces:
  - `build_compatibility_snapshot(entries, model, overrides) -> dict[str, Any]`
  - `score_evidence(features, weights) -> tuple[float, float]`
  - `query_precursor(snapshot, a: str, b: str | None = None, top: int = 20) -> Any`
  - `query_material(snapshot, a: str, b: str | None = None, top: int = 20) -> Any`
  - `canonical_json_bytes(value: Any) -> bytes`

- [ ] **Step 1: Add failing exhaustive-graph tests**

Use a compact fixture with four unique precursors and three base materials. Assert:

```python
snapshot = compat.build_compatibility_snapshot(entries, MODEL, [])
assert len(snapshot["precursor_pairs"]) == 4 * 3 // 2
assert len(snapshot["material_interfaces"]) == 3 * 2
assert len({pair["id"] for pair in snapshot["precursor_pairs"]}) == 6
```

Add tests proving:

- no-cooccurrence pair is not automatically negative;
- co-occurrence creates `exact_process` support;
- source references create `direct_literature` evidence;
- adjacent `exposure_signature` IDs create stronger `surface_sequence` than non-adjacent co-occurrence;
- `HfO2/Al2O3` creates direct stack evidence for both directions only when `HfO2` and `Al2O3` base nodes exist;
- explicit override with negative value/reliability can create `E_CONFLICT`;
- pair score and coverage differ when only one family is available;
- snapshot bytes are stable across repeated builds.

- [ ] **Step 2: Run tests and confirm RED**

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

Expected: missing graph/scoring functions.

- [ ] **Step 3: Implement catalog evidence indexing**

Create internal indexes:

```python
recipe_precursors: dict[str, list[str]]
recipe_precursor_id_map: dict[str, dict[str, str]]
recipe_sources: dict[str, list[dict[str, str]]]
recipe_status: dict[str, str]
recipe_exposure_keys: dict[str, list[str]]
material_recipes: dict[str, set[str]]
```

Map `exposure_signature` IDs through each entry's precursor IDs. Ignore signature tokens that cannot be resolved instead of guessing.

- [ ] **Step 4: Implement evidence scoring**

For available features:

```python
numerator = sum(weight * reliability * value)
denominator = sum(weight * reliability)
raw = 0.0 if denominator == 0 else numerator / denominator
score = max(0.0, min(100.0, 50.0 * (raw + 1.0)))
coverage = sum(weight for each available family) / sum(weights.values())
```

If no features are available: score `50.0`, coverage `0.0`, evidence `E0_UNKNOWN`, verdict `UNKNOWN`.

Apply explicit negative override conflict before normal thresholding when a curated feature has `value <= -0.75` and `reliability >= 0.75`.

- [ ] **Step 5: Implement evidence levels and verdicts**

Direct referenced catalog evidence at established/literature-grounded status -> `E4_DIRECT`.

Exact pair/stack evidence plus another available family -> `E3_CORROBORATED`.

Analogue-only evidence -> `E2_ANALOGUE`.

Role/family-only evidence -> `E1_HEURISTIC`.

Coverage below configured minimum -> `UNKNOWN` unless conflict.

- [ ] **Step 6: Implement exhaustive precursor/material enumeration**

Precursor pairs use `itertools.combinations(sorted_entities, 2)`.

Material interfaces use nested ordered loops over all distinct sorted base-material IDs.

Every emitted record includes stable ID, endpoint IDs/names/formulas, features, score, coverage, evidence level, verdict, and provenance IDs.

- [ ] **Step 7: Implement queries and deterministic snapshot metadata**

Snapshot must include digests of canonicalized model, catalog entries, and overrides; summary counts; evidence/verdict histograms; and sorted entity/pair/interface arrays.

Entity lookup accepts exact formula, exact canonical name, normalized alias, or stable ID. Ambiguous aliases raise `ValueError` listing matching display names.

- [ ] **Step 8: Run focused tests to GREEN**

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

- [ ] **Step 9: Commit**

```bash
git add ald_compatibility.py tests/test_ald_compatibility.py
git commit -m "feat: build exhaustive compatibility graphs"
```

---

### Task 3: Deterministic 2–6 precursor candidate ranking

**Files:**
- Modify: `ald_compatibility.py`
- Modify: `tests/test_ald_compatibility.py`

**Interfaces:**
- Consumes exhaustive precursor graph from Task 2.
- Produces:
  - `rank_candidates(snapshot, *, min_size=2, max_size=6, top=20, beam_width=None, search=None, novel_only=False, minimum_score=0.0, minimum_evidence="E0_UNKNOWN") -> list[dict[str, Any]]`
  - `explain_candidate(snapshot, items: Sequence[str]) -> dict[str, Any]`

- [ ] **Step 1: Add failing ranking tests**

Fixture must include:

- known recipe set `{metal-source, oxidant}`;
- role-compatible but novel analogue set;
- explicit conflicting pair;
- one unknown pair.

Assert:

```python
ranked = compat.rank_candidates(snapshot, min_size=2, max_size=4, top=20)
assert all(2 <= len(item["precursors"]) <= 4 for item in ranked)
assert all(item["role_complete"] for item in ranked)
assert not any(conflicting_id in item["precursor_ids"] for item in ranked)
assert ranked == compat.rank_candidates(snapshot, min_size=2, max_size=4, top=20)
```

Also assert exact catalog set gets a higher `known_support` than an otherwise comparable novel set, `novel_only=True` excludes exact known sets, and evidence filtering is respected.

- [ ] **Step 2: Run tests and confirm RED**

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

- [ ] **Step 3: Implement candidate metrics**

For each candidate, resolve all pair edges and calculate:

```python
effective = 50.0 + (pair["score"] - 50.0) * pair["coverage"]
H = harmonic_mean(effective_pair_scores)
M = min(effective_pair_scores)
E = 100.0 * mean(pair_coverages)
R = 100.0 if at_least_one_source_and_one_reactant else 0.0
K = 100.0 if exact_catalog_set else 60.0 if subset_of_catalog_set else 0.0
score = 0.40*H + 0.20*M + 0.15*E + 0.15*R + 0.10*K
```

Use the configured candidate weights rather than hard-coding values.

- [ ] **Step 4: Implement deterministic beam expansion**

Represent candidate states as sorted tuples of stable precursor IDs. Expand only with IDs lexicographically greater than the tuple's last ID. Reject conflicts immediately. At each size, sort by `(-partial_score, candidate_tuple)` and retain configured `beam_width`.

Final ranking uses `(-score, -coverage, candidate_id)`.

- [ ] **Step 5: Implement candidate evidence level and explanation**

Candidate explanation includes all pair records, weakest pair, harmonic/minimum/coverage/roles/known sub-scores, matching catalog recipes, novelty flag, final evidence level, and final score.

- [ ] **Step 6: Run focused tests to GREEN**

```bash
python -m pytest tests/test_ald_compatibility.py -q
```

- [ ] **Step 7: Commit**

```bash
git add ald_compatibility.py tests/test_ald_compatibility.py
git commit -m "feat: rank compatibility candidates"
```

---

### Task 4: `ald-master` CLI and shortened interactive flow

**Files:**
- Modify: `ald_master.py`
- Create: `tests/test_ald_master_compatibility.py`
- Modify: `tests/test_ald_master_review.py`

**Interfaces:**
- Imports `ald_compatibility as compatibility`.
- Produces subcommands:
  - `compatibility-build`
  - `compatible precursor|material`
  - `candidates`
  - `explain precursor|material|candidate`
  - `compatibility-report`

- [ ] **Step 1: Write failing parser/dispatch tests**

Test parser examples:

```python
args = ald_master.build_parser().parse_args(["compatible", "precursor", "HfCl4", "H2O", "--json"])
assert args.command == "compatible"
assert args.graph == "precursor"
assert args.entities == ["HfCl4", "H2O"]
```

Add tests for candidates size validation, snapshot build output, JSON renderability, report command, explain command, and no network calls.

Update interactive review test to expect the new top menu and shortened recipe path.

- [ ] **Step 2: Run tests and confirm RED**

```bash
python -m pytest tests/test_ald_master_compatibility.py tests/test_ald_master_review.py -q
```

- [ ] **Step 3: Add parser switches and lazy snapshot construction**

Add globals:

```text
--compat-model compatibility/model-v1.json
--compat-evidence compatibility/evidence-overrides.json
```

Each compatibility command loads catalog/model/overrides and builds the snapshot in memory. `compatibility-build` additionally writes canonical snapshot JSON.

- [ ] **Step 4: Add human and JSON renderers**

Human pair output must show score, coverage percentage, evidence level, verdict, and evidence-family lines.

Candidate output must show rank, candidate score, evidence level, formulas/names, coverage, known/novel status, and weakest pair.

Every human compatibility output starts with or ends with a one-line simulation-research safety notice.

- [ ] **Step 5: Shorten interactive routing**

Refactor `_interactive_main()` into a five-option top menu. Recipe mode becomes:

```text
Search -> Select recipe -> Select workflow -> Run / Dry run / Advanced / Cancel
```

Normal Run/Dry run uses seed 42, INFO logging, deterministic output, no overwrite, no signing/signature flags.

Advanced reuses the existing detailed seed/output/signature/log prompts.

Compatibility/candidate modes ask for only the minimum query text and then display results; detailed filters remain CLI-only.

- [ ] **Step 6: Run CLI tests to GREEN**

```bash
python -m pytest tests/test_ald_master_compatibility.py tests/test_ald_master.py tests/test_ald_master_review.py -q
```

- [ ] **Step 7: Commit**

```bash
git add ald_master.py tests/test_ald_master_compatibility.py tests/test_ald_master_review.py
git commit -m "feat: expose compatibility engine in ald-master"
```

---

### Task 5: Packaging and user documentation

**Files:**
- Modify: `pyproject.toml`
- Create: `docs/compatibility-engine.md`
- Modify: `README.md`

**Interfaces:**
- `ald_compatibility` is packaged as a top-level Python module.
- Documentation uses the exact CLI from Task 4.

- [ ] **Step 1: Add a packaging test assertion**

In `tests/test_ald_master_compatibility.py`, read `pyproject.toml` and assert `"ald_compatibility"` is present in `tool.setuptools.py-modules`.

- [ ] **Step 2: Run assertion and confirm RED**

```bash
python -m pytest tests/test_ald_master_compatibility.py -q
```

- [ ] **Step 3: Add module to package config**

Append `"ald_compatibility"` to the `py-modules` list without changing dependencies.

- [ ] **Step 4: Write `docs/compatibility-engine.md`**

Document:

- evidence levels and verdicts;
- score vs coverage distinction;
- exhaustive pair counts;
- material directionality;
- candidate beam search;
- commands with examples;
- JSON/snapshot audit workflow;
- how to add curated evidence records;
- explicit non-safety/non-fabrication boundary.

- [ ] **Step 5: Update README**

Add a concise "Compatibility evidence engine" section with examples:

```bash
ald-master compatibility-report
ald-master compatible precursor HfCl4 H2O
ald-master compatible material HfO2 Al2O3
ald-master candidates --min-size 2 --max-size 6 --top 20
ald-master compatibility-build --output build/compatibility/snapshot.json
```

- [ ] **Step 6: Run focused tests**

```bash
python -m pytest tests/test_ald_compatibility.py tests/test_ald_master_compatibility.py tests/test_ald_master.py tests/test_ald_master_review.py -q
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml README.md docs/compatibility-engine.md tests/test_ald_master_compatibility.py
git commit -m "docs: document compatibility evidence engine"
```

---

### Task 6: Full repository verification and PR

**Files:**
- No intended source changes unless verification finds a defect.

**Interfaces:**
- Verifies the complete feature against the repository.

- [ ] **Step 1: Run full pytest**

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Compile Python modules**

```bash
python -m py_compile ald_compatibility.py ald_master.py ald_media_controller.py ald_media_cli.py
```

Expected: exit 0.

- [ ] **Step 3: Exercise compatibility CLI against the real catalog**

```bash
ald-master compatibility-report
ald-master compatibility-build --output build/compatibility/snapshot.json
ald-master compatible precursor HfCl4 H2O
ald-master compatible material HfO2 Al2O3
ald-master candidates --min-size 2 --max-size 6 --top 10
```

Expected: successful deterministic outputs, complete pair/interface counts, and no network access.

- [ ] **Step 4: Run snapshot twice and compare bytes**

```bash
ald-master compatibility-build --output build/compatibility/a.json
ald-master compatibility-build --output build/compatibility/b.json
cmp build/compatibility/a.json build/compatibility/b.json
```

Expected: byte-identical snapshots.

- [ ] **Step 5: Push branch and let both existing repository workflows run**

Require the HLS integration and Product MP4 workflows to pass on the final head, proving the compatibility feature did not regress media/controller behavior.

- [ ] **Step 6: Review changed-file scope and open a PR to `main`**

PR summary must explicitly report:

- exhaustive precursor-pair count from the real catalog;
- exhaustive directed material-interface count;
- evidence/verdict histograms;
- final pytest count;
- HLS/Product workflow results;
- deterministic snapshot comparison result;
- scientific/safety boundary.
