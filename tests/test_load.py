"""Deployment-path tests: parquet handoff loading and fail-closed checks."""

from __future__ import annotations

import pandas as pd
import pytest

from data.config import Settings
from data.load import DataContractError, load_closes


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, signals_dir=tmp_path / "signals")


def _write(tmp_path, frame: pd.DataFrame) -> None:
    frame.to_parquet(tmp_path / "closes_latest.parquet")


def test_load_ok(tmp_path, closes):
    _write(tmp_path, closes)
    today = closes.index[-1].date()
    out = load_closes(_settings(tmp_path), ["SPY", "QQQ"], today=today)
    assert list(out.columns) == ["SPY", "QQQ"]
    assert not out.isna().any().any()


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(DataContractError, match="not found"):
        load_closes(_settings(tmp_path), ["SPY"])


def test_missing_symbol_fails_closed(tmp_path, closes):
    _write(tmp_path, closes)
    with pytest.raises(DataContractError, match="missing"):
        load_closes(_settings(tmp_path), ["SPY", "NOPE"], today=closes.index[-1].date())


def test_nan_gap_fails_closed(tmp_path, closes):
    closes.iloc[5, 0] = float("nan")
    _write(tmp_path, closes)
    with pytest.raises(DataContractError, match="gaps"):
        load_closes(_settings(tmp_path), list(closes.columns), today=closes.index[-1].date())


def test_stale_data_fails_closed(tmp_path, closes):
    _write(tmp_path, closes)
    stale_today = (closes.index[-1] + pd.Timedelta(days=10)).date()
    with pytest.raises(DataContractError, match="stale"):
        load_closes(_settings(tmp_path), ["SPY"], today=stale_today)
