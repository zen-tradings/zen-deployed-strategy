"""EMA-20 trend strategy (daily, rule-based).

Long the target symbol when its close is above the 20-day EMA, otherwise cash.
Validated in the research repo; this file is deployment logic only.
"""

from __future__ import annotations

import pandas as pd


class Ema20Trend:
    """Binary trend filter: 100% target symbol above EMA-20, else 100% cash."""

    frequency = "daily"

    def __init__(self, symbol: str = "SOXL", span: int = 20) -> None:
        self.symbol = symbol
        self.span = span
        self.name = f"ema{span}_trend_{symbol.lower()}"
        self.universe = [symbol]

    def generate_signals(self, closes: pd.DataFrame) -> pd.Series:
        px = closes[self.symbol]
        if len(px) < self.span * 2:
            raise ValueError(f"{self.name}: insufficient history ({len(px)} sessions)")
        ema = px.ewm(span=self.span, adjust=False).mean()
        long = float(px.iloc[-1] > ema.iloc[-1])
        return pd.Series({self.symbol: long})
