from __future__ import annotations

import numpy as np

from .models import InstitutionalRiskLimits, RiskSummary, SimulationResult

MATERIAL_QUARTERLY_LOSS = -0.50
EXTREME_EQUITY_POSITION = -12.0


def make_risk_profiles() -> dict[str, InstitutionalRiskLimits]:
    return {
        "conservative": InstitutionalRiskLimits(
            name="conservative",
            max_probability_quarterly_loss=0.20,
            max_probability_material_loss=0.08,
            max_probability_extreme_deficiency=0.05,
            max_four_quarter_loss=0.75,
            minimum_terminal_equity=-9.5,
            max_probability_inflation_above_4=0.15,
            max_probability_credit_spread_above_3=0.10,
        ),
        "standard": InstitutionalRiskLimits(name="standard"),
        "mandate_first": InstitutionalRiskLimits(
            name="mandate_first",
            max_probability_quarterly_loss=0.50,
            max_probability_material_loss=0.25,
            max_probability_extreme_deficiency=0.15,
            max_four_quarter_loss=1.50,
            minimum_terminal_equity=-11.0,
            max_probability_inflation_above_4=0.30,
            max_probability_credit_spread_above_3=0.25,
        ),
    }


def summarize_risk(result: SimulationResult) -> RiskSummary:
    if not result.records:
        raise ValueError("simulation result is empty")
    records = result.records
    terminal = result.terminal_records()
    if len(terminal) != result.simulations:
        raise ValueError("simulation result is missing terminal records")

    quarterly_loss = np.mean([r.net_income < 0.0 for r in records])
    material_loss = np.mean([r.net_income <= MATERIAL_QUARTERLY_LOSS for r in records])
    extreme = np.mean([r.equity_position <= EXTREME_EQUITY_POSITION for r in records])
    inflation_tail = np.mean([r.core_inflation > 4.0 for r in terminal])
    credit_tail = np.mean([r.credit_spread > 3.0 for r in terminal])
    terminal_equity_p10 = float(np.quantile([r.equity_position for r in terminal], 0.10))

    worst_loss = 0.0
    for sim in range(result.simulations):
        sim_records = sorted(result.records_for_simulation(sim), key=lambda r: r.quarter)
        incomes = [r.net_income for r in sim_records]
        if len(incomes) >= 4:
            worst_window = min(sum(incomes[i : i + 4]) for i in range(len(incomes) - 3))
        else:
            worst_window = sum(incomes)
        worst_loss = max(worst_loss, max(0.0, -worst_window))

    return RiskSummary(
        probability_quarterly_loss=float(quarterly_loss),
        probability_material_loss=float(material_loss),
        probability_extreme_deficiency=float(extreme),
        worst_four_quarter_loss=float(worst_loss),
        terminal_equity_p10=terminal_equity_p10,
        probability_inflation_above_4=float(inflation_tail),
        probability_credit_spread_above_3=float(credit_tail),
    )


def check_constraints(summary: RiskSummary, limits: InstitutionalRiskLimits) -> tuple[str, ...]:
    violations: list[str] = []
    if summary.probability_quarterly_loss > limits.max_probability_quarterly_loss:
        violations.append("probability_quarterly_loss")
    if summary.probability_material_loss > limits.max_probability_material_loss:
        violations.append("probability_material_loss")
    if summary.probability_extreme_deficiency > limits.max_probability_extreme_deficiency:
        violations.append("probability_extreme_deficiency")
    if summary.worst_four_quarter_loss > limits.max_four_quarter_loss:
        violations.append("worst_four_quarter_loss")
    if summary.terminal_equity_p10 < limits.minimum_terminal_equity:
        violations.append("terminal_equity_p10")
    if summary.probability_inflation_above_4 > limits.max_probability_inflation_above_4:
        violations.append("probability_inflation_above_4")
    if summary.probability_credit_spread_above_3 > limits.max_probability_credit_spread_above_3:
        violations.append("probability_credit_spread_above_3")
    return tuple(violations)
