"""Configuration for the production data layer.

All settings come from environment variables so the same code runs on the
data server and the strategy server without edits.

Parquet handoff contract (produced by ``massive_access.write_closes``):
    <DATA_DIR>/closes_YYYYMMDD.parquet   dated snapshot
    <DATA_DIR>/closes_latest.parquet     what runners read
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from the environment.

    Attributes:
        data_dir: Parquet handoff directory (``STRATEGY_DATA_DIR``).
        signals_dir: Where runners write signal files (``STRATEGY_SIGNALS_DIR``).
        max_staleness_days: Refuse to run if the latest session in the frame is
            older than this many calendar days (weekend/holiday-safe default).

    Note: ``MASSIVE_API_KEY`` is read directly by ``massive_access.MassiveClient``
    on the data server; the strategy server never needs it.
    """

    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("STRATEGY_DATA_DIR", "./_data"))
    )
    signals_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("STRATEGY_SIGNALS_DIR", "./_signals"))
    )
    max_staleness_days: int = 4

    @property
    def latest_closes_path(self) -> Path:
        return self.data_dir / "closes_latest.parquet"


def load_universes(path: Path | str = "config/universes.yaml") -> dict[str, list[str]]:
    """Load per-frequency symbol lists from ``config/universes.yaml``."""
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    return {freq: list(symbols) for freq, symbols in raw.items()}


def all_symbols(universes: dict[str, list[str]]) -> list[str]:
    """Union of all universe symbols, sorted, for a single shared data pull."""
    return sorted({s for symbols in universes.values() for s in symbols})
