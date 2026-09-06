from __future__ import annotations

from dataclasses import replace

from .models import MacroState, SimulationResult
from .risk import check_constraints, make_risk_profiles, summarize_risk


_STRESS = {
    "baseline": {},
    "inflation_shock": {
        "services_inflation": 1.2,
        "goods_inflation": 1.8,
        "shelter_inflation": 0.8,
        "oil_price": 18.0,
    },
    "financial_stress": {
        "credit_spread": 1.25,
        "gdp_growth": -1.2,
        "unemployment": 0.7,
        "housing_index": -12.0,
    },
    "deep_recession": {
        "gdp_growth": -2.8,
        "unemployment": 1.5,
        "credit_spread": 0.8,
        "housing_index": -18.0,
    },
    "oil_fx_shock": {
        "oil_price": 30.0,
        "usdcad": 0.10,
        "goods_inflation": 1.0,
    },
}


def available_stresses() -> tuple[str, ...]:
    return tuple(_STRESS)


def apply_stress(state: MacroState, scenario: str) -> MacroState:
    if scenario not in _STRESS:
        raise ValueError(f"unknown stress scenario: {scenario}")
    changes = _STRESS[scenario]
    values = {field: getattr(state, field) + delta for field, delta in changes.items()}
    return replace(state, **values)


def compare_risk_profiles(result: SimulationResult) -> dict[str, dict[str, object]]:
    summary = summarize_risk(result)
    out: dict[str, dict[str, object]] = {}
    for name, limits in make_risk_profiles().items():
        violations = check_constraints(summary, limits)
        out[name] = {
            "feasible": not violations,
            "violations": violations,
            "risk": summary,
        }
    return out


def stress_test_policy(
    engine,
    state,
    bank,
    path,
    limits,
    *,
    scenarios=("baseline", "inflation_shock", "financial_stress", "deep_recession"),
    horizon=12,
    simulations=120,
):
    """Evaluate one policy path across explicit stresses with common random seeds."""
    from .models import PolicyEvaluation
    from .optimize import policy_loss

    seeds = engine.simulation_seeds(simulations)
    results = {}
    for scenario in scenarios:
        stressed_state = apply_stress(state, scenario)
        simulation = engine.simulate_path(
            stressed_state,
            bank,
            path,
            horizon=horizon,
            seeds=seeds,
        )
        risk = summarize_risk(simulation)
        violations = check_constraints(risk, limits)
        evaluation = PolicyEvaluation(
            path=path,
            policy_loss=policy_loss(simulation, path, engine.weights),
            risk=risk,
            violations=violations,
            feasible=not violations,
        )
        results[scenario] = {
            "evaluation": evaluation,
            "risk_profiles": compare_risk_profiles(simulation),
            "seeds": seeds,
        }
    return results
