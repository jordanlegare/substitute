# Bank of Canada Research Policy Simulator

`boc_policy` is an isolated, research-only stochastic monetary-policy simulator. It explores eight-quarter Bank of Canada policy-rate paths, propagates them through stylized macro/credit/housing/FX/inflation channels, simulates a simplified Bank financial position, and applies configurable institutional-risk constraints before ranking feasible paths by a mandate-oriented loss.

## Important boundary

This is **not an official Bank of Canada model**. It does not reproduce the Bank's internal projection, DSGE, accounting, balance-sheet, or policy framework, and its output is not a forecast or policy recommendation.

The simulated Bank accumulated accounting deficit/equity position is **not the federal fiscal deficit**. Accounting losses do not imply that the Bank cannot conduct monetary policy. In this simulator, Bank financial outcomes are used only as an **institutional-risk constraint**.

## Architecture

The package is separate from Substitute's ALD simulator:

```text
boc_policy/
├── models.py      immutable states, paths, metrics, simulation/result types
├── engine.py      macro transition, inflation channels, Bank financial step, Monte Carlo
├── risk.py        risk profiles, probability summaries, constraint checks
├── optimize.py    mandate loss, candidate generation, common-seed evaluation
├── stress.py      explicit stress transforms and risk-profile comparison
├── report.py      institutional research report
├── cli.py         `boc-policy-research` command
└── plotting.py    optional pandas/matplotlib fan chart
```

Existing ALD modules do not import `boc_policy`, and `boc_policy` does not import the ALD implementation.

## Core state

`MacroState` tracks the policy rate, market terminal rate, USD/CAD, oil, services/goods/shelter/admin inflation, GDP growth, unemployment, wages, credit spread, housing, household leverage, mortgage/business rates, credit growth, term premium, and expected short rate embedded in the 10-year curve.

`LatentState` tracks potential growth, neutral rate, NAIRU, output gap, inflation trend, and the active rule-based regime.

`PolicyPath` contains eight quarterly basis-point changes. Rates are clamped to 0-8%. For horizons beyond eight quarters, the eighth action is extended.

## Common random numbers

Candidate paths must be compared under the same shock realizations. `ResearchPolicyEngine.simulation_seeds()` creates a deterministic vector of simulation seeds. `optimize_policy_path()` generates that vector once and passes it unchanged to every candidate evaluation.

`ResearchPolicyEngine.step()` consumes only the explicit RNG passed to it. The engine's constructor seed cannot silently alter a transition when the same RNG state is supplied.

Operational diagnostics use logger `BoCInstitutionalEngine` at INFO level with timestamp/level/name/message formatting.

## Institutional-risk profiles

The included envelopes are:

| Limit | Conservative | Standard | Mandate-first |
| --- | ---: | ---: | ---: |
| P(quarterly accounting loss) | 0.20 | 0.35 | 0.50 |
| P(material quarterly loss) | 0.08 | 0.15 | 0.25 |
| P(extreme deficiency) | 0.05 | 0.10 | 0.15 |
| Worst rolling four-quarter loss, CAD bn | 0.75 | 1.00 | 1.50 |
| Minimum terminal equity p10, CAD bn | -9.5 | -10.0 | -11.0 |
| P(terminal inflation > 4%) | 0.15 | 0.20 | 0.30 |
| P(terminal credit spread > 3pp) | 0.10 | 0.15 | 0.25 |

The current operational definitions use a material quarterly loss threshold of CAD 0.5bn and an extreme equity-position threshold of CAD -12bn. These are research conventions, not Bank definitions.

## Mandate-first optimization

The policy objective penalizes inflation deviation from 2%, unemployment deviation from the research NAIRU anchor, output gaps, excess housing/credit conditions, policy-path volatility/action magnitude, inflation tails, and credit-spread tails.

It does **not** include Bank net income, accumulated deficit, equity, or asset size.

Optimization is therefore lexicographic:

1. simulate every candidate under common random numbers;
2. apply the chosen institutional-risk envelope;
3. discard infeasible paths;
4. rank only feasible paths by mandate loss.

If every path is infeasible, the optimizer returns no selected path. The CLI may expose the closest infeasible candidate for diagnostics in JSON, but does not label it as the recommendation.

## CLI

Install the repository normally and run:

```bash
boc-policy-research --profile standard --seed 42 --simulations 120 --horizon 12 --max-candidates 729
```

Machine-readable output:

```bash
boc-policy-research \
  --profile mandate_first \
  --simulations 120 \
  --horizon 12 \
  --max-candidates 729 \
  --json
```

Default candidate actions are -25, 0, and +25 basis points in each of eight quarters. The default candidate cap prioritizes lower-action and smoother paths for tractability. Research callers can pass explicit candidate sets through the Python API when they require a different search design.

## Python API

```python
from boc_policy import (
    BankFinancialState,
    MacroState,
    ResearchPolicyEngine,
    make_risk_profiles,
    optimize_policy_path,
)

engine = ResearchPolicyEngine(seed=42)
result = optimize_policy_path(
    engine,
    MacroState(),
    BankFinancialState(),
    make_risk_profiles()["standard"],
    simulations=120,
    horizon=12,
)

if result.best is not None:
    print(result.best.path.as_list())
    print(result.best.policy_loss)
```

## Stress testing

```python
from boc_policy.models import PolicyPath
from boc_policy.stress import stress_test_policy

stress = stress_test_policy(
    engine,
    MacroState(),
    BankFinancialState(),
    PolicyPath(),
    make_risk_profiles()["standard"],
)
```

Available scenarios are baseline, inflation shock, financial stress, deep recession, and oil/FX shock. The same simulation seed vector is reused across requested scenarios for cleaner comparisons.

## Optional fan charts

Install visualization dependencies only when needed:

```bash
python -m pip install -e '.[boc]'
```

Then:

```python
from boc_policy.plotting import plot_fan_chart
fig, ax = plot_fan_chart(simulation_result, "core_inflation")
```

## Current limitations

The transition coefficients are stylized rather than estimated from a historical dataset. Regime changes are rule-based. The term structure, credit channel, housing channel, and inflation decomposition are deliberately compact. The Bank balance-sheet model is an institutional-risk approximation rather than a faithful accounting model. No fiscal reaction function, official-data ingestion, or historical backtest is included in this milestone.

Those limitations should be treated as part of the model output: numerical precision from a Monte Carlo run does not imply empirical identification or institutional endorsement.
