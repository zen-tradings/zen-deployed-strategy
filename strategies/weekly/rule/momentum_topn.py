"""Weekly cross-sectional momentum (rule-based).

Equal-weight the top-N symbols by trailing return; cash if none are positive.
Validated in the research repo; deployment logic only.
"""

from __future__ import annotations

import pandas as pd


class MomentumTopN:
    """Top-N trailing-return momentum over the weekly universe."""

    frequency = "weekly"

    def __init__(self, universe: list[str], lookback_sessions: int = 60, top_n: int = 2) -> None:
        self.universe = list(universe)
        self.lookback = lookback_sessions
        self.top_n = top_n
        self.name = f"momentum_top{top_n}_{lookback_sessions}d"

    def generate_signals(self, closes: pd.DataFrame) -> pd.Series:
        px = closes[self.universe]
        if len(px) < self.lookback + 1:
            raise ValueError(f"{self.name}: insufficient history ({len(px)} sessions)")
        ret = px.iloc[-1] / px.iloc[-self.lookback - 1] - 1.0
        winners = ret[ret > 0].nlargest(self.top_n)
        weights = pd.Series(0.0, index=self.universe)
        if not winners.empty:
            weights[winners.index] = 1.0 / len(winners)
        return weights
