"""Risk controls applied to every strategy's raw weights before emission.

Order of application:
1. per-position cap
2. portfolio vol scaling (target annualized vol)
3. drawdown guard (scale down / flatten when the strategy's own equity curve
   breaches its limit — equity tracking is wired in by the runner)

All controls are simple, interpretable, and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class RiskLimits:
    """Limits applied per strategy run."""

    max_position_weight: float = 0.50
    target_annual_vol: float = 0.20     # scale gross exposure to this portfolio vol
    vol_lookback_sessions: int = 63
    max_drawdown: float = 0.20          # flatten when strategy drawdown exceeds this


def cap_positions(weights: pd.Series, limits: RiskLimits) -> pd.Series:
    """Clip each position to ``max_position_weight`` (excess goes to cash)."""
    return weights.clip(upper=limits.max_position_weight)


def vol_scale(weights: pd.Series, closes: pd.DataFrame, limits: RiskLimits) -> pd.Series:
    """Scale gross exposure down when realized portfolio vol exceeds target.

    Never scales up (leverage) — only de-risks.
    """
    active = weights[weights > 0]
    if active.empty or len(closes) < limits.vol_lookback_sessions + 1:
        return weights
    rets = closes[active.index].pct_change().dropna().tail(limits.vol_lookback_sessions)
    port_vol = float((rets @ (active / active.sum())).std() * np.sqrt(TRADING_DAYS))
    if port_vol <= limits.target_annual_vol or port_vol == 0.0:
        return weights
    return weights * (limits.target_annual_vol / port_vol)


def drawdown_guard(weights: pd.Series, equity: pd.Series | None, limits: RiskLimits) -> pd.Series:
    """Flatten to cash if the strategy's equity drawdown breaches the limit.

    ``equity`` is the strategy's own equity curve (from journaled runs); when
    unavailable (first runs), the guard is a no-op.
    """
    if equity is None or len(equity) < 2:
        return weights
    dd = float(equity.iloc[-1] / equity.cummax().iloc[-1] - 1.0)
    if dd < -limits.max_drawdown:
        return weights * 0.0
    return weights


def apply_risk(
    weights: pd.Series,
    closes: pd.DataFrame,
    limits: RiskLimits | None = None,
    equity: pd.Series | None = None,
) -> pd.Series:
    """Run the full risk pipeline. Output is what gets emitted — nothing else."""
    limits = limits or RiskLimits()
    w = cap_positions(weights, limits)
    w = vol_scale(w, closes, limits)
    w = drawdown_guard(w, equity, limits)
    return w
