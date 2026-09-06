from __future__ import annotations

from .models import InstitutionalRiskLimits, PolicyEvaluation


def institutional_report(evaluation: PolicyEvaluation, limits: InstitutionalRiskLimits) -> str:
    status = "FEASIBLE" if evaluation.feasible else "INFEASIBLE"
    path = ", ".join(f"{bp:+d}" for bp in evaluation.path.as_list())
    risk = evaluation.risk
    violations = ", ".join(evaluation.violations) if evaluation.violations else "none"
    return f"""Bank of Canada Research Policy Simulator — Institutional Report

Status: {status} under the {limits.name} institutional-risk envelope
Policy path (quarterly basis-point changes): [{path}]
Mandate loss: {evaluation.policy_loss:.4f}
Constraint violations: {violations}

Risk summary
- P(quarterly accounting loss): {risk.probability_quarterly_loss:.3f}
- P(material quarterly accounting loss): {risk.probability_material_loss:.3f}
- P(extreme accounting deficiency): {risk.probability_extreme_deficiency:.3f}
- Worst rolling four-quarter accounting loss: CAD {risk.worst_four_quarter_loss:.3f} bn
- Terminal equity position, 10th percentile: CAD {risk.terminal_equity_p10:.3f} bn
- P(terminal core inflation > 4%): {risk.probability_inflation_above_4:.3f}
- P(terminal credit spread > 3pp): {risk.probability_credit_spread_above_3:.3f}

Interpretation boundary
This is not an official Bank of Canada model. It is a research-oriented stochastic simulator and does not reproduce the Bank's internal projection, DSGE, accounting, or policy framework. The Bank's accumulated accounting deficit/equity position is not the federal fiscal deficit and does not determine its ability to conduct monetary policy. Bank financial outcomes enter here only as an institutional-risk constraint; among feasible paths, the mandate loss over inflation, labour-market, output and macro-financial outcomes determines the ranking.
"""
