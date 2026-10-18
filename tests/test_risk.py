"""Risk-pipeline tests: caps, vol scaling, drawdown guard."""

from __future__ import annotations

import pandas as pd

from deployment.risk import RiskLimits, apply_risk, cap_positions, drawdown_guard, vol_scale


def test_position_cap():
    limits = RiskLimits(max_position_weight=0.5)
    w = cap_positions(pd.Series({"SOXL": 1.0}), limits)
    assert w["SOXL"] == 0.5


def test_vol_scale_only_derisks(closes):
    limits = RiskLimits(target_annual_vol=0.05)  # low target forces scaling down
    w = vol_scale(pd.Series({"SOXL": 1.0}), closes, limits)
    assert 0.0 < w["SOXL"] < 1.0

    relaxed = RiskLimits(target_annual_vol=10.0)  # never scales up
    w2 = vol_scale(pd.Series({"SPY": 0.5}), closes, relaxed)
    assert w2["SPY"] == 0.5


def test_drawdown_guard_flattens():
    limits = RiskLimits(max_drawdown=0.2)
    equity = pd.Series([100.0, 110.0, 80.0])  # -27% from peak
    w = drawdown_guard(pd.Series({"SPY": 0.6}), equity, limits)
    assert (w == 0).all()


def test_apply_risk_pipeline(closes):
    final = apply_risk(pd.Series({"SOXL": 1.0}), closes)
    assert final["SOXL"] <= RiskLimits().max_position_weight + 1e-9
