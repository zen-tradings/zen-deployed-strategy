"""Shared fixtures: synthetic closes frames matching the handoff contract."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def closes() -> pd.DataFrame:
    """120 business days of synthetic adjusted closes for the test universe."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2026-04-01", periods=120)
    data = {
        sym: 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.02, len(idx)))
        for sym in ["SOXL", "SPY", "QQQ", "IWM", "TLT", "GLD"]
    }
    frame = pd.DataFrame(data, index=idx)
    frame.index.name = "date"
    return frame
