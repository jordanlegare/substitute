from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class MacroState:
    overnight_rate: float = 2.25
    market_terminal_rate: float = 2.25
    usdcad: float = 1.39
    oil_price: float = 72.0
    services_inflation: float = 2.8
    goods_inflation: float = 1.5
    shelter_inflation: float = 3.5
    admin_inflation: float = 1.8
    gdp_growth: float = 1.2
    unemployment: float = 6.4
    wage_growth: float = 3.0
    credit_spread: float = 1.40
    housing_index: float = 182.0
    household_leverage: float = 175.0
    mortgage_rate: float = 4.55
    business_rate: float = 5.05
    credit_growth: float = 3.2
    term_premium: float = 0.65
    expected_short_rate_10y: float = 2.99

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> "MacroState":
        allowed = cls.__dataclass_fields__
        return cls(**{k: v for k, v in values.items() if k in allowed})


@dataclass(frozen=True)
class LatentState:
    potential_growth: float = 1.8
    neutral_rate: float = 2.5
    nairu: float = 5.8
    output_gap: float = -0.3
    inflation_trend: float = 2.0
    regime: str = "normal"


@dataclass(frozen=True)
class PolicyPath:
    q1: int = 0
    q2: int = 0
    q3: int = 0
    q4: int = 0
    q5: int = 0
    q6: int = 0
    q7: int = 0
    q8: int = 0

    def as_list(self) -> list[int]:
        return [self.q1, self.q2, self.q3, self.q4, self.q5, self.q6, self.q7, self.q8]

    def rate_path(self, initial_rate: float, horizon: int = 16) -> list[float]:
        if horizon < 1:
            return []
        changes = self.as_list()
        rate = float(initial_rate)
        out: list[float] = []
        for quarter in range(horizon):
            change = changes[quarter] if quarter < len(changes) else changes[-1]
            rate = float(np.clip(rate + change / 100.0, 0.0, 8.0))
            out.append(rate)
        return out


@dataclass(frozen=True)
class BankFinancialState:
    investment_assets: float = 192.2
    loans_receivables: float = 27.8
    government_deposits: float = 65.0
    settlement_balances: float = 59.4
    bank_notes: float = 124.3
    asset_duration: float = 5.5
    asset_yield_spread: float = 0.35
    deposit_spread: float = 0.05
    annual_operating_expense: float = 0.740
    accumulated_deficit: float = -9.899
    reserves: float = 0.100
    revaluation_reserve: float = 0.656
    actuarial_reserve: float = 0.616
    quarterly_asset_runoff: float = 0.015

    def copy(self) -> "BankFinancialState":
        return BankFinancialState(**asdict(self))


@dataclass(frozen=True)
class FinancialMetrics:
    interest_revenue: float
    interest_expense: float
    net_interest_income: float
    operating_expense: float
    net_income: float
    accumulated_deficit: float
    equity_position: float
    asset_size: float


@dataclass(frozen=True)
class InstitutionalRiskLimits:
    name: str = "standard"
    max_probability_quarterly_loss: float = 0.35
    max_probability_material_loss: float = 0.15
    max_probability_extreme_deficiency: float = 0.10
    max_four_quarter_loss: float = 1.00
    minimum_terminal_equity: float = -10.0
    max_probability_inflation_above_4: float = 0.20
    max_probability_credit_spread_above_3: float = 0.15


@dataclass(frozen=True)
class PolicyWeights:
    inflation: float = 5.0
    unemployment: float = 1.5
    output: float = 1.5
    housing: float = 0.40
    credit: float = 0.40
    policy_smoothing: float = 0.75
    policy_level: float = 0.10
    inflation_tail: float = 1.50
    financial_tail: float = 1.00


@dataclass(frozen=True)
class QuarterRecord:
    simulation: int
    quarter: int
    policy_rate: float
    core_inflation: float
    gdp_growth: float
    unemployment: float
    output_gap: float
    housing_index: float
    credit_spread: float
    net_income: float
    accumulated_deficit: float
    equity_position: float
    asset_size: float


@dataclass(frozen=True)
class SimulationResult:
    records: tuple[QuarterRecord, ...]
    horizon: int
    simulations: int

    def terminal_records(self) -> tuple[QuarterRecord, ...]:
        return tuple(r for r in self.records if r.quarter == self.horizon)

    def records_for_simulation(self, simulation: int) -> tuple[QuarterRecord, ...]:
        return tuple(r for r in self.records if r.simulation == simulation)


@dataclass(frozen=True)
class RiskSummary:
    probability_quarterly_loss: float
    probability_material_loss: float
    probability_extreme_deficiency: float
    worst_four_quarter_loss: float
    terminal_equity_p10: float
    probability_inflation_above_4: float
    probability_credit_spread_above_3: float


@dataclass(frozen=True)
class PolicyEvaluation:
    path: PolicyPath
    policy_loss: float
    risk: RiskSummary
    violations: tuple[str, ...]
    feasible: bool


@dataclass(frozen=True)
class OptimizationResult:
    best: PolicyEvaluation | None
    evaluations: tuple[PolicyEvaluation, ...]
    profile: InstitutionalRiskLimits
    seeds: tuple[int, ...]
