from __future__ import annotations

from .models import SimulationResult


def plot_fan_chart(result: SimulationResult, variable: str = "core_inflation"):
    """Plot p10/p25/p50/p75/p90 fan bands; imports optional deps lazily."""
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "fan-chart plotting requires the optional 'boc' extra: pip install -e '.[boc]'"
        ) from exc

    allowed = {
        "policy_rate",
        "core_inflation",
        "gdp_growth",
        "unemployment",
        "output_gap",
        "housing_index",
        "credit_spread",
        "net_income",
        "equity_position",
        "asset_size",
    }
    if variable not in allowed:
        raise ValueError(f"unsupported fan-chart variable: {variable}")
    frame = pd.DataFrame(
        {
            "quarter": [record.quarter for record in result.records],
            variable: [getattr(record, variable) for record in result.records],
        }
    )
    grouped = frame.groupby("quarter")[variable]
    q10, q25, q50, q75, q90 = (grouped.quantile(q) for q in (0.10, 0.25, 0.50, 0.75, 0.90))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.fill_between(q50.index, q10, q90, alpha=0.15)
    ax.fill_between(q50.index, q25, q75, alpha=0.30)
    ax.plot(q50.index, q50, linewidth=2)
    if variable == "core_inflation":
        ax.axhline(2.0, linestyle="--", linewidth=1)
    ax.set_xlabel("Quarter")
    ax.set_ylabel(variable)
    ax.set_title(f"{variable} fan chart")
    fig.tight_layout()
    return fig, ax
