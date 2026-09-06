# Recipe chemistry evidence

Substitute keeps three concepts deliberately separate:

1. **Material identity** — `materials/catalog.json` contains 8,000 fixed-stoichiometry identities with identity provenance.
2. **Recipe chemistry evidence** — `recipes/evidence/process-evidence.json` records literature-backed target/reactant identity and publication provenance.
3. **Executable simulation recipes** — `recipes/compounds/catalog.json` points to deterministic, synthetic simulator programs. Their numerical execution values are not literature process conditions and are not fabrication instructions.

## Frozen coverage

The current evidence sweep examined all 8,000 material identities against the pinned AtomicLimits-derived AWASES export plus the public AtomicLimits process API. The canonical audit records:

- **250 executable recipes total**;
- **150 newly selected distinct materials** from the evidence expansion;
- **36 previously recipe-backed distinct material identities**;
- **186 distinct recipe-backed material identities** after the expansion;
- **7,814 identity-only materials remaining**;
- **134 thermal-ALD** and **16 plasma-ALD** selected additions;
- **150 R3 selections** and **zero selected R1/R2 records** in this frozen sweep.

Evidence exhaustion, not a round recipe-count target, is the stopping rule. Variable-composition targets such as `TaNx`, `FeOx`, and `HfSixOy` are intentionally excluded from the fixed-stoichiometry material catalog rather than being guessed into a composition. Precursor-only datasets cannot create a recipe unless a source explicitly links a fixed target to its reactants.

## Explore chemistry

The primary read-only interface is `ald-master chemistry`:

```bash
ald-master chemistry search HfO2
ald-master chemistry show HfO2
ald-master chemistry sources HfO2
ald-master chemistry list --process-family plasma-ald --limit 50
ald-master chemistry report
```

Use `--json` for machine-readable output. The chemistry projection exposes only target identity, process-family classification, source reactant labels/canonical identities when available, evidence grade, source references, origin, and recipe links. It does not project recipe instruction payloads or simulator operating values.

`ald-master materials show ...` remains the identity-oriented view. It cross-links an exact executable recipe when one exists, but missing recipe evidence remains identity-only rather than being inferred.

## Evidence sources and reproducibility

`recipes/evidence/source-manifest.json` pins the frozen AWASES repository/ref/blob/content digests and records the live AtomicLimits endpoint used for the acquisition sweep. The frozen acquisition combined 536 AWASES candidates with 1,198 live API candidates, for 1,734 source candidates before deterministic validation, deduplication, grading, and selection.

Normal runtime and canonical rebuild checks are offline. The network acquisition step is not needed to use the checked-in evidence or recipes.

Rebuild/check the generated state with:

```bash
python tools/audit_recipe_evidence.py
python tools/build_recipe_expansion.py --check
python tools/build_compound_catalog.py --check
python tools/build_material_catalog.py --check --target-count 8000
```

## Scientific and safety boundary

Literature evidence supports **chemistry identity/provenance only**. Generated expansion recipes carry exact source reactant labels and direct publication identifiers, while executable ordering and numerical simulator values come from a fixed synthetic template. `physical_fabrication_mapping` remains false.

Substitute does not turn literature temperatures, pressures, pulse times, purge times, flows, plasma settings, equipment details, or precursor-handling information into executable values. Recipe chemistry evidence is not a chemical-mixing, equipment-safety, process-window, or fabrication-readiness determination.
