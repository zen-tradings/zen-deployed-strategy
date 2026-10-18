"""Consumer-side loader for the parquet handoff (runs on the strategy server).

Reads ``closes_latest.parquet`` and applies fail-closed validation before any
strategy sees the data: required symbols present, no NaNs, not stale.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from data.config import Settings


class DataContractError(RuntimeError):
    """Raised when the handoff frame violates the production data contract."""


def load_closes(
    settings: Settings,
    required_symbols: list[str],
    today: date | None = None,
) -> pd.DataFrame:
    """Load and validate the latest closes frame for a runner.

    Args:
        settings: resolved environment settings (data dir, staleness limit).
        required_symbols: the running strategy's universe; all must be present.
        today: current UTC date (injectable for tests).

    Returns:
        The closes frame restricted to ``required_symbols``.

    Raises:
        DataContractError: file missing, symbols missing, NaN gaps, or stale.
    """
    today = today or datetime.now(UTC).date()
    path = settings.latest_closes_path
    if not path.exists():
        raise DataContractError(f"handoff file not found: {path}")

    closes = pd.read_parquet(path)

    missing = [s for s in required_symbols if s not in closes.columns]
    if missing:
        raise DataContractError(f"symbols missing from handoff frame: {missing}")
    closes = closes[required_symbols]

    if closes.empty:
        raise DataContractError("handoff frame is empty")
    if closes.isna().any().any():
        gaps = closes.columns[closes.isna().any()].tolist()
        raise DataContractError(f"gaps (NaN) in symbols: {gaps}")

    age_days = (today - closes.index[-1].date()).days
    if age_days > settings.max_staleness_days:
        raise DataContractError(
            f"data stale: latest session {closes.index[-1].date()} is {age_days}d old "
            f"(max {settings.max_staleness_days})"
        )
    return closes
