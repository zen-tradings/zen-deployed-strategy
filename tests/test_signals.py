"""Signal-shape tests for the deployed strategies."""

from __future__ import annotations

import pandas as pd

from strategies.base import validate_signals
from strategies.daily.rule.ema20_trend import Ema20Trend
from strategies.monthly.rule.equal_weight import EqualWeight
from strategies.weekly.rule.momentum_topn import MomentumTopN


def _check(strategy, weights: pd.Series) -> None:
    validate_signals(strategy, weights)
    assert set(weights.index) <= set(strategy.universe)
    assert (weights >= 0).all() and weights.sum() <= 1.0 + 1e-9


def test_ema20_trend_signal_shape(closes):
    strat = Ema20Trend(symbol="SOXL")
    w = strat.generate_signals(closes)
    _check(strat, w)
    assert w.loc["SOXL"] in (0.0, 1.0)


def test_momentum_topn_signal_shape(closes):
    strat = MomentumTopN(universe=["SPY", "QQQ", "IWM", "TLT"], top_n=2)
    w = strat.generate_signals(closes)
    _check(strat, w)
    assert (w > 0).sum() <= 2


def test_equal_weight_signal_shape(closes):
    strat = EqualWeight(universe=["SPY", "TLT", "GLD"])
    w = strat.generate_signals(closes)
    _check(strat, w)
    assert abs(w.sum() - 1.0) < 1e-9
