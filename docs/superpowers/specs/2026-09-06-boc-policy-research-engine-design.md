# Bank of Canada Research Policy Engine Design

## Purpose

Add an isolated, research-oriented stochastic monetary-policy simulator to `substitute` without coupling it to the repository's ALD execution paths. The subsystem explores quarterly Bank of Canada policy-rate paths under macroeconomic uncertainty while treating the Bank's simplified accounting position as an institutional-risk envelope rather than as a profit objective.

This is explicitly **not an official Bank of Canada model** and does not replicate the Bank's internal projection, DSGE, accounting, balance-sheet, or policy framework.

## Research question

Identify policy paths that minimize a mandate-oriented loss over inflation, unemployment, output, housing, and macro-financial stress while remaining inside a configurable institutional-risk envelope for the simulated Bank financial position.

The optimizer applies a hard ordering:

1. simulate each candidate with the same random-number seeds;
2. reject candidates that violate the selected institutional-risk limits;
3. rank only feasible candidates by mandate loss;
4. return no selected path when no candidate is feasible.

Bank accounting outcomes never enter the mandate loss directly.

## Isolation boundary

The implementation lives in a new `boc_policy/` Python package. Existing ALD modules do not import it, and it does not import ALD code. The only repository-wide changes are packaging metadata and a dedicated CI workflow.

Core simulation requires only NumPy, already a project dependency. pandas and matplotlib are optional through the `boc` extra and are imported lazily by the plotting module.

## Components

### State models

`MacroState` contains the observable macro-financial state: policy and terminal-market rates, USD/CAD, oil, four inflation components, GDP growth, unemployment, wages, credit spread, housing, leverage, lending rates, credit growth, term premium, and expected long rates.

`LatentState` contains potential growth, neutral rate, NAIRU, output gap, inflation trend, and regime.

`PolicyPath` stores eight quarterly basis-point changes. `rate_path()` applies each change with a 0-8% policy-rate clamp and extends the eighth change beyond the explicit eight-quarter path when a longer simulation horizon is requested.

### Bank financial state

`BankFinancialState` is a deliberately simplified Bank balance-sheet/income approximation in CAD billions. It tracks investment assets, loans, remunerated liabilities, notes, duration/yield assumptions, operating expense, accumulated accounting deficit and reserve accounts, and asset runoff.

`FinancialMetrics` reports quarterly revenue, expense, net interest income, operating expense, net income, accumulated deficit, equity position, and asset size.

Interest rates are annualized and converted to quarterly cash-flow equivalents. The financial module is an institutional-risk approximation, not an accounting forecast.

### Macro transition

`ResearchPolicyEngine.step()` receives an explicit NumPy RNG. It must not consume hidden engine RNG state. A transition updates policy rate, long-rate expectations, term premium, spreads, lending conditions, credit, GDP, unemployment, wages, FX, oil, housing, leverage, inflation components, latent trend/regime, and Bank financial metrics.

Regimes are `inflation_shock`, `inflation_pressure`, `financial_stress`, `deep_recession`, `recession`, and `normal`.

### Monte Carlo and common random numbers

`simulate_path()` accepts explicit simulation seeds. `simulation_seeds()` deterministically derives a seed vector from the engine seed. The optimizer generates one seed vector and reuses it for every candidate path, so candidate differences are not contaminated by different shock realizations.

Simulation output is immutable `QuarterRecord` data wrapped by `SimulationResult`.

The engine exposes logger `BoCInstitutionalEngine` at INFO level with timestamp, level, logger name, and message fields for reproducible operational diagnostics.

### Institutional risk

Three profiles are provided: conservative, standard, and mandate-first.

Risk statistics include quarterly-loss probability, material-loss probability, extreme-deficiency probability, worst rolling four-quarter loss, terminal equity 10th percentile, terminal inflation-above-4 probability, and terminal credit-spread-above-3 probability.

The accounting position is distinct from the federal fiscal deficit. Simulated Bank losses are not interpreted as loss of monetary-policy capacity.

### Policy objective

`policy_loss()` uses only mandate and macro-financial variables: inflation deviation, unemployment deviation, output gap, excess housing, excess credit spread, path smoothing, policy-action magnitude, inflation tail probability, and macro-financial credit-spread tail probability.

No Bank net-income, accumulated-deficit, equity, or asset-size term appears in the objective.

### Optimization

Candidate paths use {-25, 0, +25} basis-point quarterly actions by default. The generator is deterministic and can cap the candidate count for tractability, preferring lower-action/smoother paths before larger action sequences. Callers can supply an explicit candidate set for exhaustive or specialized research.

Every candidate is evaluated against identical seeds. `select_best_feasible()` returns the lowest-loss feasible candidate and returns `None` if the envelope rejects all candidates.

### Stress testing and profile comparison

Explicit stress transforms cover baseline, inflation shock, financial stress, deep recession, and oil/FX shock. Stress testing reuses a single seed vector across scenarios for a given policy path. A separate risk-profile comparison applies all three institutional envelopes to one already-simulated distribution.

### Reporting and CLI

`institutional_report()` emits a human-readable research report with feasibility, policy path, mandate loss, risk metrics, and the institutional/accounting disclaimers.

`boc-policy-research` runs the optimizer from default research states and supports profile, seed, simulation count, horizon, candidate cap, and JSON output. If no candidate is feasible, it exits non-zero and does not promote a least-infeasible path as the recommendation.

### Visualization

`plot_fan_chart()` lazily imports pandas/matplotlib and plots p10/p25/p50/p75/p90 bands for supported simulation variables. Importing the package does not require optional visualization dependencies.

## Testing

The dedicated test module verifies documented inflation weights; policy-rate path extension/clamping; Bank accounting identities; explicit RNG isolation; deterministic simulations from explicit common seeds; probability-based risk summaries and profile limits; mandate loss independence from Bank accounting metrics; hard rejection of infeasible lower-loss candidates; stress non-mutation and shared-seed behavior; risk-profile comparison; report boundary language; candidate generation determinism; optimizer seed reuse; machine-readable CLI output; lazy plotting imports; and the documented logger configuration.

A path-filtered GitHub Actions workflow installs the normal test extra, runs the BoC tests, compiles the package, and performs a CLI smoke run.

## Scientific limitations

The coefficients are stylized and unestimated. The model is not calibrated to a formal historical sample in this milestone. Regime switching is rule-based, structural parameters are fixed within regimes, and the Bank balance-sheet model is intentionally simplified. Results are scenario-analysis outputs, not forecasts or policy advice.

Backtesting, empirical coefficient estimation, richer term-structure dynamics, fiscal-monetary interactions, and official-data ingestion are intentionally outside this PR.
