from __future__ import annotations

from itertools import product
from typing import Iterable, Sequence

import numpy as np

from .engine import ResearchPolicyEngine
from .models import (
    BankFinancialState,
    InstitutionalRiskLimits,
    MacroState,
    OptimizationResult,
    PolicyEvaluation,
    PolicyPath,
    PolicyWeights,
    SimulationResult,
)
from .risk import check_constraints, summarize_risk


def policy_loss(
    result: SimulationResult,
    path: PolicyPath,
    weights: PolicyWeights | None = None,
) -> float:
    weights = weights or PolicyWeights()
    if not result.records:
        raise ValueError("simulation result is empty")
    records = result.records
    inflation = np.mean([(r.core_inflation - 2.0) ** 2 for r in records])
    unemployment = np.mean([(r.unemployment - 5.8) ** 2 for r in records])
    output = np.mean([r.output_gap**2 for r in records])
    housing = np.mean([max(0.0, r.housing_index - 190.0) ** 2 / 100.0 for r in records])
    credit = np.mean([max(0.0, r.credit_spread - 2.0) ** 2 for r in records])
    inflation_tail = np.mean([r.core_inflation > 4.0 for r in records])
    financial_tail = np.mean([r.credit_spread > 3.0 for r in records])
    changes = np.asarray(path.as_list(), dtype=float)
    smoothing = float(np.mean(np.diff(changes) ** 2)) if len(changes) > 1 else 0.0
    policy_level = float(np.mean((changes / 25.0) ** 2))
    return float(
        weights.inflation * inflation
        + weights.unemployment * unemployment
        + weights.output * output
        + weights.housing * housing
        + weights.credit * credit
        + weights.policy_smoothing * smoothing / 625.0
        + weights.policy_level * policy_level
        + weights.inflation_tail * inflation_tail
        + weights.financial_tail * financial_tail
    )


def evaluate_policy(
    engine: ResearchPolicyEngine,
    state: MacroState,
    bank: BankFinancialState,
    path: PolicyPath,
    limits: InstitutionalRiskLimits,
    *,
    horizon: int,
    seeds: Sequence[int],
) -> PolicyEvaluation:
    result = engine.simulate_path(state, bank, path, horizon=horizon, seeds=tuple(seeds))
    risk = summarize_risk(result)
    violations = check_constraints(risk, limits)
    return PolicyEvaluation(
        path=path,
        policy_loss=policy_loss(result, path, engine.weights),
        risk=risk,
        violations=violations,
        feasible=not violations,
    )


def select_best_feasible(evaluations: Iterable[PolicyEvaluation]) -> PolicyEvaluation | None:
    feasible = [evaluation for evaluation in evaluations if evaluation.feasible]
    if not feasible:
        return None
    return min(feasible, key=lambda evaluation: (evaluation.policy_loss, tuple(evaluation.path.as_list())))


def generate_policy_paths(
    actions: Sequence[int] = (-25, 0, 25),
    *,
    max_candidates: int | None = 729,
) -> tuple[PolicyPath, ...]:
    candidates = [PolicyPath(*combo) for combo in product(actions, repeat=8)]
    candidates.sort(
        key=lambda path: (
            sum(abs(value) for value in path.as_list()),
            sum(abs(b - a) for a, b in zip(path.as_list(), path.as_list()[1:])),
            tuple(path.as_list()),
        )
    )
    if max_candidates is not None:
        candidates = candidates[: max(1, int(max_candidates))]
    return tuple(candidates)


def optimize_policy_path(
    engine: ResearchPolicyEngine,
    state: MacroState,
    bank: BankFinancialState,
    limits: InstitutionalRiskLimits,
    *,
    candidates: Sequence[PolicyPath] | None = None,
    horizon: int = 12,
    simulations: int = 120,
    max_candidates: int | None = 729,
) -> OptimizationResult:
    paths = tuple(candidates) if candidates is not None else generate_policy_paths(max_candidates=max_candidates)
    seeds = engine.simulation_seeds(simulations)
    evaluations = tuple(
        evaluate_policy(engine, state, bank, path, limits, horizon=horizon, seeds=seeds)
        for path in paths
    )
    return OptimizationResult(
        best=select_best_feasible(evaluations),
        evaluations=evaluations,
        profile=limits,
        seeds=seeds,
    )
