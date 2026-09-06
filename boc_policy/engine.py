from __future__ import annotations

from dataclasses import asdict
import logging

import numpy as np

from .models import (
    BankFinancialState,
    FinancialMetrics,
    LatentState,
    MacroState,
    PolicyPath,
    PolicyWeights,
    QuarterRecord,
    SimulationResult,
)

logger = logging.getLogger("BoCInstitutionalEngine")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
logger.propagate = False


class ResearchPolicyEngine:
    TARGET = 2.0

    def __init__(self, seed: int = 42, weights: PolicyWeights | None = None):
        self.seed = int(seed)
        self.weights = weights or PolicyWeights()
        self.rng = np.random.default_rng(self.seed)

    def core_inflation(self, s: MacroState) -> float:
        return (
            0.45 * s.services_inflation
            + 0.25 * s.goods_inflation
            + 0.25 * s.shelter_inflation
            + 0.05 * s.admin_inflation
        )

    def detect_regime(self, s: MacroState) -> str:
        core = self.core_inflation(s)
        if core >= 4.0:
            return "inflation_shock"
        if s.credit_spread >= 2.25:
            return "financial_stress"
        if s.gdp_growth <= -1.0:
            return "deep_recession"
        if s.gdp_growth < 0.0:
            return "recession"
        if core >= 3.0:
            return "inflation_pressure"
        return "normal"

    def estimate_latent(self, s: MacroState) -> LatentState:
        regime = self.detect_regime(s)
        neutral = {
            "inflation_shock": 2.70,
            "inflation_pressure": 2.60,
            "financial_stress": 2.10,
            "deep_recession": 1.80,
            "recession": 2.10,
            "normal": 2.50,
        }[regime]
        potential = {
            "inflation_shock": 1.75,
            "inflation_pressure": 1.75,
            "financial_stress": 1.60,
            "deep_recession": 1.40,
            "recession": 1.60,
            "normal": 1.80,
        }[regime]
        return LatentState(
            potential_growth=potential,
            neutral_rate=neutral,
            nairu=5.8,
            output_gap=float(np.clip(s.gdp_growth - potential, -5.0, 5.0)),
            inflation_trend=self.core_inflation(s),
            regime=regime,
        )

    def update_credit(self, s: MacroState, latent: LatentState) -> MacroState:
        current_core = self.core_inflation(s)
        real_rate = s.overnight_rate - current_core
        mortgage_rate = s.overnight_rate + 2.20 + 0.25 * s.credit_spread
        business_rate = s.overnight_rate + 2.70 + 0.40 * s.credit_spread
        credit_growth = float(
            np.clip(
                3.5
                - 0.60 * real_rate
                - 0.45 * (s.credit_spread - 1.40)
                + 0.15 * latent.output_gap,
                -4.0,
                10.0,
            )
        )
        values = asdict(s)
        values.update(
            mortgage_rate=mortgage_rate,
            business_rate=business_rate,
            credit_growth=credit_growth,
        )
        return MacroState(**values)

    def bank_financial_step(
        self,
        bank: BankFinancialState,
        policy_rate: float,
        credit_spread: float,
    ) -> tuple[BankFinancialState, FinancialMetrics]:
        values = asdict(bank)
        values["investment_assets"] = max(
            130.0,
            bank.investment_assets * (1.0 - bank.quarterly_asset_runoff),
        )
        investment_assets = float(values["investment_assets"])
        effective_asset_yield = float(
            np.clip(
                policy_rate + bank.asset_yield_spread - 0.015 * bank.asset_duration,
                0.25,
                8.0,
            )
        )
        # Rates are annualized; convert flows to one quarter.
        interest_revenue = (
            investment_assets * effective_asset_yield / 100.0
            + bank.loans_receivables * (policy_rate + 1.10) / 100.0
        ) / 4.0
        stress_penalty = max(credit_spread - 1.40, 0.0) * 0.10
        interest_expense = (
            (bank.government_deposits + bank.settlement_balances)
            * max(policy_rate - bank.deposit_spread, 0.0)
            / 100.0
            / 4.0
            + stress_penalty
        )
        net_interest_income = interest_revenue - interest_expense
        operating_expense = bank.annual_operating_expense / 4.0
        net_income = net_interest_income - operating_expense
        accumulated_deficit = bank.accumulated_deficit + net_income
        values["accumulated_deficit"] = accumulated_deficit
        updated = BankFinancialState(**values)
        equity_position = (
            accumulated_deficit
            + updated.reserves
            + updated.revaluation_reserve
            + updated.actuarial_reserve
        )
        metrics = FinancialMetrics(
            interest_revenue=interest_revenue,
            interest_expense=interest_expense,
            net_interest_income=net_interest_income,
            operating_expense=operating_expense,
            net_income=net_income,
            accumulated_deficit=accumulated_deficit,
            equity_position=equity_position,
            asset_size=updated.investment_assets + updated.loans_receivables,
        )
        return updated, metrics

    def step(
        self,
        s: MacroState,
        latent: LatentState,
        bank: BankFinancialState,
        rate_change_bp: int,
        rng: np.random.Generator,
    ) -> tuple[MacroState, LatentState, BankFinancialState, FinancialMetrics]:
        values = asdict(s)
        rate_change = rate_change_bp / 100.0
        values["overnight_rate"] = float(np.clip(s.overnight_rate + rate_change, 0.0, 8.0))
        values["expected_short_rate_10y"] = 0.85 * s.expected_short_rate_10y + 0.15 * values["overnight_rate"]
        term_premium = s.term_premium + float(rng.normal(0.0, 0.015))
        if latent.regime == "financial_stress":
            term_premium += 0.05
        values["term_premium"] = float(np.clip(term_premium, 0.0, 3.0))
        values["credit_spread"] = float(
            np.clip(
                s.credit_spread
                + 0.12 * rate_change
                + 0.08 * max(-latent.output_gap, 0.0)
                + float(rng.normal(0.0, 0.025)),
                0.50,
                5.0,
            )
        )
        ns = self.update_credit(MacroState(**values), latent)

        current_core = self.core_inflation(s)
        real_rate = ns.overnight_rate - current_core
        demand_impulse = 0.12 * (ns.credit_growth - 3.0) - 0.08 * (real_rate - latent.neutral_rate)
        values = asdict(ns)
        values["gdp_growth"] = float(
            np.clip(
                0.78 * s.gdp_growth
                + 0.22 * (latent.potential_growth + demand_impulse)
                + float(rng.normal(0.0, 0.15)),
                -4.0,
                6.0,
            )
        )
        pressure = -0.22 * (values["gdp_growth"] - latent.potential_growth)
        values["unemployment"] = float(
            np.clip(
                0.90 * s.unemployment
                + 0.10 * (5.8 + pressure)
                + float(rng.normal(0.0, 0.05)),
                3.5,
                12.0,
            )
        )
        values["wage_growth"] = float(
            np.clip(
                0.82 * s.wage_growth
                + 0.10 * current_core
                + 0.08 * (latent.nairu - values["unemployment"]),
                1.0,
                8.0,
            )
        )
        values["usdcad"] = float(
            np.clip(
                0.90 * s.usdcad
                + 0.10 * (1.39 - 0.035 * (values["overnight_rate"] - 2.25))
                + float(rng.normal(0.0, 0.005)),
                1.05,
                1.70,
            )
        )
        values["oil_price"] = float(
            np.clip(0.90 * s.oil_price + 0.10 * 72.0 + float(rng.normal(0.0, 2.0)), 25.0, 160.0)
        )
        housing_demand = 0.25 * (ns.credit_growth - 3.0) - 0.15 * (ns.mortgage_rate - 4.5)
        values["housing_index"] = float(
            np.clip(s.housing_index * (1.0 + housing_demand / 100.0) + float(rng.normal(0.0, 0.7)), 100.0, 320.0)
        )
        values["household_leverage"] = float(
            np.clip(
                0.96 * s.household_leverage
                + 0.04 * (s.household_leverage + 0.8 * (ns.credit_growth - 3.0)),
                100.0,
                230.0,
            )
        )

        demand_gap = float(np.clip(values["gdp_growth"] - latent.potential_growth, -4.0, 4.0))
        wage_gap = float(np.clip(values["wage_growth"] - 3.0, -3.0, 5.0))
        fx_change = 100.0 * (values["usdcad"] / max(s.usdcad, 1e-9) - 1.0)
        oil_change = 100.0 * (values["oil_price"] / max(s.oil_price, 1e-9) - 1.0)
        housing_change = 100.0 * (values["housing_index"] / max(s.housing_index, 1e-9) - 1.0)
        values["services_inflation"] = float(
            np.clip(
                0.78 * s.services_inflation
                + 0.22 * latent.inflation_trend
                + 0.055 * wage_gap
                + 0.045 * demand_gap
                + float(rng.normal(0.0, 0.07)),
                -1.0,
                8.0,
            )
        )
        values["goods_inflation"] = float(
            np.clip(
                0.62 * s.goods_inflation
                + 0.38 * latent.inflation_trend
                + 0.045 * fx_change
                + 0.012 * oil_change
                + 0.025 * demand_gap
                + float(rng.normal(0.0, 0.10)),
                -3.0,
                10.0,
            )
        )
        mortgage_gap = ns.mortgage_rate - 4.50
        values["shelter_inflation"] = float(
            np.clip(
                0.84 * s.shelter_inflation
                + 0.16 * latent.inflation_trend
                + 0.055 * housing_change
                - 0.025 * mortgage_gap
                + float(rng.normal(0.0, 0.06)),
                -1.0,
                10.0,
            )
        )
        values["admin_inflation"] = float(
            np.clip(
                0.90 * s.admin_inflation
                + 0.10 * latent.inflation_trend
                + float(rng.normal(0.0, 0.035)),
                -1.0,
                7.0,
            )
        )
        ns = MacroState(**values)
        observed_core = self.core_inflation(ns)
        new_regime = self.detect_regime(ns)
        neutral = {
            "inflation_shock": 2.70,
            "inflation_pressure": 2.60,
            "financial_stress": 2.10,
            "deep_recession": 1.80,
            "recession": 2.10,
            "normal": 2.50,
        }[new_regime]
        potential = {
            "inflation_shock": 1.75,
            "inflation_pressure": 1.75,
            "financial_stress": 1.60,
            "deep_recession": 1.40,
            "recession": 1.60,
            "normal": 1.80,
        }[new_regime]
        nl = LatentState(
            potential_growth=potential,
            neutral_rate=neutral,
            nairu=latent.nairu,
            output_gap=float(np.clip(ns.gdp_growth - potential, -5.0, 5.0)),
            inflation_trend=float(np.clip(0.92 * latent.inflation_trend + 0.08 * observed_core, 1.0, 5.0)),
            regime=new_regime,
        )
        new_bank, metrics = self.bank_financial_step(bank, ns.overnight_rate, ns.credit_spread)
        return ns, nl, new_bank, metrics

    def simulation_seeds(self, simulations: int) -> tuple[int, ...]:
        if simulations < 1:
            raise ValueError("simulations must be >= 1")
        rng = np.random.default_rng(self.seed)
        return tuple(int(v) for v in rng.integers(0, np.iinfo(np.uint32).max, size=simulations, dtype=np.uint32))

    def simulate_path(
        self,
        state: MacroState,
        bank: BankFinancialState,
        path: PolicyPath,
        *,
        horizon: int = 16,
        simulations: int | None = None,
        seeds: list[int] | tuple[int, ...] | None = None,
    ) -> SimulationResult:
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        if seeds is None:
            seeds = self.simulation_seeds(simulations or 250)
        else:
            seeds = tuple(int(seed) for seed in seeds)
        if not seeds:
            raise ValueError("at least one simulation seed is required")
        changes = path.as_list()
        records: list[QuarterRecord] = []
        for simulation, seed in enumerate(seeds):
            rng = np.random.default_rng(seed)
            s = MacroState(**asdict(state))
            latent = self.estimate_latent(s)
            b = bank.copy()
            for quarter in range(1, horizon + 1):
                change = changes[quarter - 1] if quarter <= 8 else changes[-1]
                s, latent, b, metrics = self.step(s, latent, b, change, rng)
                records.append(
                    QuarterRecord(
                        simulation=simulation,
                        quarter=quarter,
                        policy_rate=s.overnight_rate,
                        core_inflation=self.core_inflation(s),
                        gdp_growth=s.gdp_growth,
                        unemployment=s.unemployment,
                        output_gap=latent.output_gap,
                        housing_index=s.housing_index,
                        credit_spread=s.credit_spread,
                        net_income=metrics.net_income,
                        accumulated_deficit=metrics.accumulated_deficit,
                        equity_position=metrics.equity_position,
                        asset_size=metrics.asset_size,
                    )
                )
        return SimulationResult(tuple(records), horizon, len(seeds))
