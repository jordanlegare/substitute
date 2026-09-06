from dataclasses import replace

import numpy as np
import pytest

from boc_policy.engine import ResearchPolicyEngine
from boc_policy.models import (
    BankFinancialState,
    MacroState,
    PolicyEvaluation,
    PolicyPath,
    QuarterRecord,
    RiskSummary,
    SimulationResult,
)
from boc_policy.optimize import policy_loss, select_best_feasible
from boc_policy.report import institutional_report
from boc_policy.risk import check_constraints, make_risk_profiles, summarize_risk
from boc_policy.stress import apply_stress, compare_risk_profiles


def _record(
    sim: int,
    quarter: int,
    *,
    core: float = 2.0,
    spread: float = 1.4,
    net_income: float = 0.1,
    equity: float = -8.5,
    output_gap: float = 0.0,
    unemployment: float = 5.8,
    housing: float = 182.0,
    policy_rate: float = 2.25,
) -> QuarterRecord:
    return QuarterRecord(
        simulation=sim,
        quarter=quarter,
        policy_rate=policy_rate,
        core_inflation=core,
        gdp_growth=1.8,
        unemployment=unemployment,
        output_gap=output_gap,
        housing_index=housing,
        credit_spread=spread,
        net_income=net_income,
        accumulated_deficit=equity - 1.372,
        equity_position=equity,
        asset_size=210.0,
    )


def test_core_inflation_uses_documented_component_weights():
    engine = ResearchPolicyEngine(seed=7)
    state = MacroState()
    expected = 0.45 * 2.8 + 0.25 * 1.5 + 0.25 * 3.5 + 0.05 * 1.8
    assert engine.core_inflation(state) == pytest.approx(expected)


def test_policy_path_clamps_rate_and_extends_eighth_move():
    path = PolicyPath(*([-25] * 8))
    assert path.as_list() == [-25] * 8
    assert path.rate_path(2.25, horizon=10) == pytest.approx(
        [2.0, 1.75, 1.5, 1.25, 1.0, 0.75, 0.5, 0.25, 0.0, 0.0]
    )


def test_bank_financial_step_preserves_accounting_identities():
    engine = ResearchPolicyEngine(seed=1)
    bank = BankFinancialState()
    updated, metrics = engine.bank_financial_step(bank, policy_rate=2.25, credit_spread=1.40)

    assert updated.investment_assets == pytest.approx(bank.investment_assets * 0.985)
    assert metrics.net_income == pytest.approx(
        metrics.net_interest_income - metrics.operating_expense
    )
    assert metrics.accumulated_deficit == pytest.approx(
        bank.accumulated_deficit + metrics.net_income
    )
    assert metrics.equity_position == pytest.approx(
        metrics.accumulated_deficit
        + updated.reserves
        + updated.revaluation_reserve
        + updated.actuarial_reserve
    )


def test_step_uses_only_supplied_rng_for_stochastic_innovations():
    engine_a = ResearchPolicyEngine(seed=1)
    engine_b = ResearchPolicyEngine(seed=999)
    state = MacroState()
    latent = engine_a.estimate_latent(state)
    bank = BankFinancialState()

    result_a = engine_a.step(state, latent, bank, 25, np.random.default_rng(1234))
    result_b = engine_b.step(state, latent, bank, 25, np.random.default_rng(1234))

    assert result_a == result_b


def test_simulate_path_is_reproducible_with_explicit_common_random_seeds():
    engine = ResearchPolicyEngine(seed=5)
    seeds = [10, 11, 12, 13]
    path = PolicyPath(0, -25, 0, 0, 0, 0, 0, 0)

    first = engine.simulate_path(MacroState(), BankFinancialState(), path, horizon=6, seeds=seeds)
    second = engine.simulate_path(MacroState(), BankFinancialState(), path, horizon=6, seeds=seeds)

    assert first == second
    assert first.simulations == 4
    assert len(first.records) == 24


def test_risk_summary_and_standard_constraints_are_probability_based():
    records = []
    for sim in range(10):
        for q in range(1, 5):
            records.append(
                _record(
                    sim,
                    q,
                    core=4.5 if sim == 0 and q == 4 else 2.0,
                    spread=3.2 if sim == 1 and q == 4 else 1.4,
                    net_income=-0.6 if sim == 2 and q == 1 else 0.1,
                    equity=-12.2 if sim == 3 and q == 4 else -8.5,
                )
            )
    result = SimulationResult(records=tuple(records), horizon=4, simulations=10)
    summary = summarize_risk(result)

    assert summary.probability_quarterly_loss == pytest.approx(1 / 40)
    assert summary.probability_material_loss == pytest.approx(1 / 40)
    assert summary.probability_extreme_deficiency == pytest.approx(1 / 40)
    assert summary.probability_inflation_above_4 == pytest.approx(0.1)
    assert summary.probability_credit_spread_above_3 == pytest.approx(0.1)
    assert summary.worst_four_quarter_loss == pytest.approx(0.3)
    assert check_constraints(summary, make_risk_profiles()["standard"]) == ()


def test_policy_loss_is_independent_of_bank_accounting_results():
    path = PolicyPath()
    macro = tuple(_record(0, q) for q in range(1, 5))
    altered_finance = tuple(
        replace(record, net_income=-5.0, accumulated_deficit=-30.0, equity_position=-28.0)
        for record in macro
    )

    base_loss = policy_loss(SimulationResult(macro, 4, 1), path)
    altered_loss = policy_loss(SimulationResult(altered_finance, 4, 1), path)
    assert altered_loss == pytest.approx(base_loss)


def test_mandate_first_selection_rejects_lower_loss_infeasible_path():
    risk_ok = RiskSummary(
        probability_quarterly_loss=0.1,
        probability_material_loss=0.02,
        probability_extreme_deficiency=0.01,
        worst_four_quarter_loss=0.4,
        terminal_equity_p10=-8.0,
        probability_inflation_above_4=0.05,
        probability_credit_spread_above_3=0.04,
    )
    risk_bad = replace(risk_ok, terminal_equity_p10=-12.0)
    feasible = PolicyEvaluation(PolicyPath(), 2.0, risk_ok, (), True)
    infeasible = PolicyEvaluation(
        PolicyPath(-25, 0, 0, 0, 0, 0, 0, 0),
        0.5,
        risk_bad,
        ("terminal_equity_p10",),
        False,
    )

    assert select_best_feasible([infeasible, feasible]) == feasible
    assert select_best_feasible([infeasible]) is None


def test_stress_scenarios_are_explicit_and_non_mutating():
    state = MacroState()
    stressed = apply_stress(state, "inflation_shock")

    assert stressed is not state
    assert stressed.services_inflation > state.services_inflation
    assert stressed.goods_inflation > state.goods_inflation
    assert state.services_inflation == 2.8


def test_risk_profile_comparison_reuses_one_simulation_distribution():
    records = tuple(_record(sim, q) for sim in range(3) for q in range(1, 5))
    result = SimulationResult(records, 4, 3)
    comparison = compare_risk_profiles(result)

    assert set(comparison) == {"conservative", "standard", "mandate_first"}
    assert all(entry["feasible"] for entry in comparison.values())


def test_institutional_report_states_research_and_accounting_boundaries():
    risk = RiskSummary(0.1, 0.02, 0.01, 0.4, -8.0, 0.05, 0.04)
    evaluation = PolicyEvaluation(PolicyPath(), 1.25, risk, (), True)
    report = institutional_report(evaluation, make_risk_profiles()["standard"])

    lowered = report.lower()
    assert "not an official bank of canada model" in lowered
    assert "not the federal fiscal deficit" in lowered
    assert "institutional-risk constraint" in lowered
    assert "mandate" in lowered


def test_generate_policy_paths_is_deterministic_and_prefers_smaller_moves():
    from boc_policy.optimize import generate_policy_paths

    paths = generate_policy_paths(max_candidates=5)
    assert len(paths) == 5
    assert paths[0] == PolicyPath()
    assert paths == generate_policy_paths(max_candidates=5)


def test_optimizer_uses_same_simulation_seeds_for_every_candidate():
    from boc_policy.optimize import optimize_policy_path

    class TrackingEngine(ResearchPolicyEngine):
        def __init__(self):
            super().__init__(seed=123)
            self.seen = []

        def simulate_path(self, state, bank, path, *, horizon=16, simulations=None, seeds=None):
            self.seen.append(tuple(seeds))
            records = tuple(_record(sim, q) for sim in range(len(seeds)) for q in range(1, horizon + 1))
            return SimulationResult(records, horizon, len(seeds))

    engine = TrackingEngine()
    candidates = (PolicyPath(), PolicyPath(-25, 0, 0, 0, 0, 0, 0, 0))
    result = optimize_policy_path(
        engine,
        MacroState(),
        BankFinancialState(),
        make_risk_profiles()["standard"],
        candidates=candidates,
        horizon=4,
        simulations=3,
    )

    assert result.best is not None
    assert len(engine.seen) == 2
    assert engine.seen[0] == engine.seen[1] == result.seeds


def test_stress_test_policy_runs_all_requested_scenarios_with_shared_seeds():
    from boc_policy.stress import stress_test_policy

    engine = ResearchPolicyEngine(seed=9)
    result = stress_test_policy(
        engine,
        MacroState(),
        BankFinancialState(),
        PolicyPath(),
        make_risk_profiles()["mandate_first"],
        scenarios=("baseline", "inflation_shock"),
        horizon=3,
        simulations=4,
    )

    assert set(result) == {"baseline", "inflation_shock"}
    assert all("evaluation" in entry and "risk_profiles" in entry for entry in result.values())


def test_cli_json_output_is_machine_readable(capsys):
    import json
    from boc_policy.cli import main

    exit_code = main(
        [
            "--profile",
            "mandate_first",
            "--simulations",
            "2",
            "--horizon",
            "2",
            "--max-candidates",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code in {0, 2}
    assert payload["profile"] == "mandate_first"
    assert payload["simulations"] == 2
    assert payload["horizon"] == 2
    assert "best" in payload


def test_plotting_module_import_does_not_require_optional_dependencies():
    import boc_policy.plotting as plotting

    assert callable(plotting.plot_fan_chart)


def test_engine_logger_uses_documented_name_level_and_format():
    import logging
    from boc_policy.engine import logger

    assert logger.name == "BoCInstitutionalEngine"
    assert logger.level == logging.INFO
    assert logger.handlers
    assert "%(asctime)s" in logger.handlers[0].formatter._fmt
    assert "%(levelname)s" in logger.handlers[0].formatter._fmt
    assert "%(name)s" in logger.handlers[0].formatter._fmt
