from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from typing import Sequence

from .engine import ResearchPolicyEngine
from .models import BankFinancialState, MacroState
from .optimize import optimize_policy_path
from .report import institutional_report
from .risk import make_risk_profiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boc-policy-research",
        description="Research-only stochastic Bank of Canada policy-path simulator.",
    )
    parser.add_argument("--profile", choices=tuple(make_risk_profiles()), default="standard")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--simulations", type=int, default=120)
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--max-candidates", type=int, default=729)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def _evaluation_payload(evaluation):
    if evaluation is None:
        return None
    return {
        "path_bp": evaluation.path.as_list(),
        "policy_loss": evaluation.policy_loss,
        "feasible": evaluation.feasible,
        "violations": list(evaluation.violations),
        "risk": asdict(evaluation.risk),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.simulations < 1 or args.horizon < 1 or args.max_candidates < 1:
        raise SystemExit("simulations, horizon and max-candidates must be >= 1")

    profiles = make_risk_profiles()
    profile = profiles[args.profile]
    engine = ResearchPolicyEngine(seed=args.seed)
    result = optimize_policy_path(
        engine,
        MacroState(),
        BankFinancialState(),
        profile,
        horizon=args.horizon,
        simulations=args.simulations,
        max_candidates=args.max_candidates,
    )
    if args.json_output:
        payload = {
            "research_only": True,
            "profile": profile.name,
            "seed": args.seed,
            "simulations": args.simulations,
            "horizon": args.horizon,
            "candidate_count": len(result.evaluations),
            "best": _evaluation_payload(result.best),
        }
        if result.best is None and result.evaluations:
            closest = min(
                result.evaluations,
                key=lambda ev: (len(ev.violations), ev.policy_loss, tuple(ev.path.as_list())),
            )
            payload["closest_infeasible"] = _evaluation_payload(closest)
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif result.best is not None:
        print(institutional_report(result.best, profile))
    else:
        print(
            f"No feasible policy path found under the {profile.name} institutional-risk envelope. "
            "No mandate ranking is selected from infeasible paths."
        )
    return 0 if result.best is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
