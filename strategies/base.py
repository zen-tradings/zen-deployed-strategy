"""Minimal Strategy interface shared by all frequencies.

A strategy is a pure function of the closes frame: it receives the contract
DataFrame (completed sessions only, no NaNs) and returns target weights.
Risk controls, scheduling, and output are the runner's job — not the strategy's.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

import pandas as pd

Frequency = Literal["daily", "weekly", "monthly"]


@runtime_checkable
class Strategy(Protocol):
    """Contract every deployed strategy must satisfy."""

    name: str
    frequency: Frequency
    universe: list[str]

    def generate_signals(self, closes: pd.DataFrame) -> pd.Series:
        """Return target weights indexed by symbol.

        Args:
            closes: adjusted daily closes (contract frame), columns ⊇ universe.

        Returns:
            pd.Series of target portfolio weights in [0, 1], index = symbols
            from ``universe``. Weights may sum to < 1 (remainder = cash).
        """
        ...


def validate_signals(strategy: Strategy, weights: pd.Series) -> pd.Series:
    """Fail-closed sanity check on a strategy's raw output."""
    if weights.isna().any():
        raise ValueError(f"{strategy.name}: NaN weights")
    unknown = set(weights.index) - set(strategy.universe)
    if unknown:
        raise ValueError(f"{strategy.name}: weights for symbols outside universe: {unknown}")
    if (weights < 0).any() or weights.sum() > 1.0 + 1e-9:
        raise ValueError(f"{strategy.name}: weights out of bounds (long-only, sum <= 1)")
    return weights
