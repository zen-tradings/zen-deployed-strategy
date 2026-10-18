"""Monthly equal-weight rebalance (rule-based baseline).

Rebalances to equal weights across the monthly universe on the first run of
each month. Serves as the interpretable baseline allocation.
"""

from __future__ import annotations

import pandas as pd


class EqualWeight:
    """Equal-weight allocation across the configured monthly universe."""

    frequency = "monthly"

    def __init__(self, universe: list[str]) -> None:
        self.universe = list(universe)
        self.name = "equal_weight_monthly"

    def generate_signals(self, closes: pd.DataFrame) -> pd.Series:
        if closes[self.universe].empty:
            raise ValueError(f"{self.name}: empty closes frame")
        return pd.Series(1.0 / len(self.universe), index=self.universe)
