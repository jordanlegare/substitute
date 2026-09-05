# Compatibility Evidence Engine

Substitute's compatibility evidence engine is an offline, deterministic research layer for the compound recipe catalog. It exhaustively evaluates catalog-derived evidence for precursor pairs and directed material interfaces, then uses the frozen precursor graph to rank bounded 2–6 precursor candidate sets.

> **Scientific and safety boundary**
>
> A compatibility score means evidence support inside this model for offline sequential ALD-style simulation research. It is **not** a chemical-mixing, storage, gas-line, reactor, equipment-safety, process-window, or fabrication-readiness determination. The engine does not provide temperature, pressure, flow, dose, purge, hazard-control, or machine-operation instructions. `UNKNOWN` means insufficient evidence, not incompatibility. `SUPPORTED` means supported by the configured evidence model, not experimentally validated unless the cited evidence explicitly establishes that fact.

## Inputs and reproducibility

The default inputs are:

- `recipes/compounds/catalog.json` — catalog recipes and their precursor/material metadata;
- `compatibility/model-v1.json` — versioned weights, thresholds, role taxonomy, reliability values, and beam-search defaults;
- `compatibility/evidence-overrides.json` — versioned curated evidence extension point.

`ald-master` accepts alternate model/evidence files through global switches placed before the command:

```bash
ald-master --compat-model compatibility/model-v1.json \
  --compat-evidence compatibility/evidence-overrides.json \
  compatibility-report
```

Runtime compatibility commands are local/offline. The engine does not fetch web services while scoring. For identical catalog/model/override inputs, stable entity IDs, graph ordering, snapshot bytes, candidate IDs, and candidate ordering are deterministic.

## Exhaustive graphs

### Precursor graph

If the normalized catalog contains `n` unique precursor entities, the snapshot contains exactly:

```text
n * (n - 1) / 2
```

unordered precursor-pair records. Absence from a recipe is not treated as negative evidence.

Catalog-derived evidence families include:

- `exact_process` — exact pair co-occurrence in catalog recipes;
- `direct_literature` — source references attached to supporting catalog entries;
- `surface_sequence` — mapped exposure-sequence support, with adjacency stronger than non-adjacent co-occurrence;
- `role_complementarity` — coarse source/reactant complementarity;
- `chemistry_analogue` — deterministic shared-neighbor analogue support.

`external_thermochemistry` and `physical_property` are explicit model families but remain unavailable unless curated evidence supplies them.

### Material graph

If the normalized catalog contains `m` base material entities, the snapshot contains exactly:

```text
m * (m - 1)
```

directed material-interface records. `A -> B` and `B -> A` are separate records.

Slash-delimited composite targets such as `HfO2/Al2O3` can provide `direct_stack` evidence when their constituents resolve to existing base-material nodes. When the catalog establishes only co-membership in a stack rather than direction, the evidence is attached conservatively to both directed edges with provenance explaining that direction was not established.

Other material evidence can include direct source references, shared precursor sets, and weak family/category/product analogues. No bulk thermodynamic or interface-stability claim is invented when the required evidence is absent.

## Score and coverage are different quantities

Each available evidence feature has a configured weight, a value in `[-1, +1]`, and reliability in `[0, 1]`.

For available families:

```text
R = sum(weight * reliability * value) / sum(weight * reliability)
score = clamp(50 * (R + 1), 0, 100)
```

Evidence coverage is calculated independently:

```text
coverage = sum(weight for available families) / sum(all configured family weights)
```

A high score with low coverage therefore means the available evidence is favorable but sparse. It must not be read as comprehensive validation.

Candidate ranking further shrinks sparse pair evidence toward neutral:

```text
effective_pair_score = 50 + (pair_score - 50) * pair_coverage
```

## Evidence levels

Evidence level describes the kind and strength of provenance rather than duplicating the numeric score.

| Level | Interpretation |
| --- | --- |
| `E4_DIRECT` | Direct catalog process/stack evidence plus direct references at an established or literature-grounded status. |
| `E3_CORROBORATED` | Exact catalog evidence with additional supporting evidence, or catalog set/subset support with corroborating pair evidence. |
| `E2_ANALOGUE` | Meaningful analogue evidence without direct pair/process evidence. |
| `E1_HEURISTIC` | Role/family heuristic evidence only. |
| `E0_UNKNOWN` | Evidence is insufficient. |
| `E_CONFLICT` | Explicit credible negative curated evidence triggers a hard conflict state. |

Positive filtering order is:

```text
E0_UNKNOWN < E1_HEURISTIC < E2_ANALOGUE < E3_CORROBORATED < E4_DIRECT
```

`E_CONFLICT` is a rejection state, not a lower positive evidence tier.

## Verdicts

With the default model:

- `CONFLICTING` — explicit `E_CONFLICT` evidence;
- `UNKNOWN` — evidence coverage is below the configured minimum;
- `LOW_SUPPORT` — score below 45;
- `UNCERTAIN` — score from 45 through below 60;
- `PLAUSIBLE` — score from 60 through below 75;
- `SUPPORTED` — score 75 or above.

These verdicts describe support within the evidence model only.

## Candidate ranking

Candidate generation is bounded rather than brute-force. Every size-two pair is evaluated from the exhaustive precursor graph, then larger candidates are generated with deterministic beam search.

A candidate must:

- contain 2–6 unique precursor entities;
- contain at least one `SOURCE` role and at least one recognized reactant class;
- contain no pair in `E_CONFLICT`/`CONFLICTING` state.

For each candidate the engine computes:

- `H` — harmonic mean of coverage-shrunk pair scores;
- `M` — minimum coverage-shrunk pair score;
- `E` — mean pair coverage on a 0–100 scale;
- `R` — role completeness, 100 when source/reactant complete;
- `K` — known-set support: 100 for an exact catalog precursor set, 60 for a strict subset of a catalog set, otherwise 0.

The default model uses:

```text
candidate_score = 0.40*H + 0.20*M + 0.15*E + 0.15*R + 0.10*K
```

At each size the beam is sorted deterministically and truncated to the configured width. The default width is 500. The harmonic and minimum terms make weak pair relations visible instead of allowing them to disappear inside several strong relations.

## CLI workflow

Install the project and use `ald-master` from the repository root so the default catalog/model/evidence paths resolve directly.

### Report graph coverage

```bash
ald-master compatibility-report
ald-master compatibility-report --json
```

The report shows precursor/material counts, verdict histograms, evidence-level histograms, and input digests.

### Build a deterministic snapshot

```bash
ald-master compatibility-build --output build/compatibility/snapshot.json
```

The snapshot schema is `ald-compatibility-snapshot/1` and contains normalized entities, every precursor pair, every directed material interface, provenance features, summaries, and digests.

### Query precursor evidence

```bash
ald-master compatible precursor HfCl4
ald-master compatible precursor HfCl4 H2O
ald-master compatible precursor HfCl4 H2O --json
```

One entity lists best-supported partners. Two entities return/explain that exact unordered pair.

### Query directed material evidence

```bash
ald-master compatible material HfO2
ald-master compatible material HfO2 Al2O3
ald-master compatible material HfO2 Al2O3 --json
```

One entity lists outgoing directed interfaces. Two entities query the requested `A -> B` edge.

### Rank 2–6 precursor candidates

```bash
ald-master candidates --min-size 2 --max-size 6 --top 20
ald-master candidates --search hafnium --minimum-evidence E2_ANALOGUE
ald-master candidates --novel-only
ald-master candidates --json
```

Useful filters include `--min-size`, `--max-size`, `--top`, `--beam-width`, `--search`, `--novel-only`, `--minimum-score`, and `--minimum-evidence`.

### Explain one result

```bash
ald-master explain precursor HfCl4 H2O
ald-master explain material HfO2 Al2O3
ald-master explain candidate HfCl4 H2O ZrCl4 O3
```

Candidate explanation includes all constituent pair records, the weakest pair, component sub-scores, matching/subset catalog recipe IDs, evidence level, and final score.

## JSON and snapshot audit workflow

Machine-readable commands use `--json`:

```bash
ald-master compatibility-report --json
ald-master compatible precursor HfCl4 H2O --json
ald-master candidates --top 10 --json
ald-master explain candidate HfCl4 H2O --json
```

To verify deterministic snapshot serialization locally:

```bash
ald-master compatibility-build --output build/compatibility/a.json
ald-master compatibility-build --output build/compatibility/b.json
cmp build/compatibility/a.json build/compatibility/b.json
```

The snapshot records SHA-256 digests of the canonicalized model, catalog entries, and curated evidence. Generated snapshots are audit/build artifacts; the checked-in catalog/model/evidence files remain the source inputs.

## Adding curated evidence

`compatibility/evidence-overrides.json` uses schema `ald-compatibility-evidence/1`:

```json
{
  "schema": "ald-compatibility-evidence/1",
  "records": [
    {
      "graph": "precursor",
      "a": "HfCl4",
      "b": "H2O",
      "family": "external_thermochemistry",
      "value": 0.4,
      "reliability": 0.8,
      "source": {
        "type": "literature",
        "identifier": "replace-with-auditable-source-id"
      },
      "note": "Example schema only; replace with reviewed evidence."
    }
  ]
}
```

For material evidence, set `"graph": "material"`. A material record may include `"directional": true` when the source specifically establishes `a -> b`; without that flag, matching is treated as nondirectional evidence and may apply to both directions.

Rules enforced by the loader include:

- `graph` is `precursor` or `material`;
- `a`, `b`, and `family` are non-empty strings and must resolve to known entities when applied;
- `value` is between -1 and +1;
- `reliability` is between 0 and 1;
- `source` contains string `type` and `identifier` fields;
- the selected evidence `family` must exist in the configured graph model.

Strong negative curated evidence (`value <= -0.75` with `reliability >= 0.75`) can produce `E_CONFLICT`/`CONFLICTING`. Do not use absence of evidence as a negative override.

After changing the model or curated evidence, rebuild the snapshot and review the changed digests, histograms, affected edge explanations, and candidate ranking before treating results as comparable to an earlier run.

## Interactive mode

Running `ald-master` without a subcommand opens a five-option menu:

1. Recipe workflow
2. Precursor compatibility
3. Material compatibility
4. Rank precursor candidates
5. Compatibility report

The normal recipe path is shortened to:

```text
Search -> recipe -> workflow -> Run / Dry run / Advanced / Cancel
```

Normal execution uses seed 42, INFO logging, deterministic output paths, no overwrite, and no signing/signature requirement. `Advanced` exposes the detailed existing controls. Arrow-key and number-key menu selection remains available.

## Interpretation checklist

Before using a result in research analysis, inspect all of the following:

1. **Score** — direction and magnitude of the evidence that is available.
2. **Coverage** — how much of the configured evidence model is actually populated.
3. **Evidence level** — whether support is direct, corroborated, analogue, heuristic, unknown, or conflicting.
4. **Provenance** — recipe IDs, source references, curated evidence records, and notes attached to each contributing feature.
5. **Weakest pair** for multi-precursor candidates — sparse or weak relations can dominate practical uncertainty.
6. **Model/catalog/evidence digests** — comparisons are meaningful only when inputs are understood.
7. **Safety boundary** — model support never substitutes for chemical hazard review, equipment engineering, laboratory validation, or process qualification.

The engine is intentionally conservative about information that is not present in the repository catalog or the reviewed evidence-override file.