"""Deployment-ops tests: atomic emit, once-per-period guard, health, alert feed."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from data.config import Settings
from deployment import runner
from deployment.ops.health import health
from deployment.runner import already_emitted, emit, period_key
from strategies.daily.rule.ema20_trend import Ema20Trend
from strategies.monthly.rule.equal_weight import EqualWeight
from strategies.weekly.rule.momentum_topn import MomentumTopN


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", signals_dir=tmp_path / "signals")


def _write_closes(settings: Settings, closes: pd.DataFrame) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    closes.to_parquet(settings.latest_closes_path)


def test_emit_is_atomic_and_valid_json(settings):
    strat = Ema20Trend()
    emit(settings, strat, pd.Series({"SOXL": 0.25}), as_of="2026-10-16")
    files = list(settings.signals_dir.iterdir())
    assert [f.name for f in files] == ["2026-10-16_ema20_trend_soxl.json"]  # no tmp left
    assert json.loads(files[0].read_text())["weights"] == {"SOXL": 0.25}


def test_period_keys():
    assert period_key("daily", date(2026, 10, 16)) == "2026-10-16"
    assert period_key("weekly", date(2026, 10, 16)) == period_key("weekly", date(2026, 10, 12))
    assert period_key("monthly", date(2026, 10, 1)) == period_key("monthly", date(2026, 10, 30))


def test_monthly_emits_once_per_month(settings):
    strat = EqualWeight(universe=["SPY", "TLT", "GLD"])
    emit(settings, strat, pd.Series({"SPY": 1 / 3}), as_of="2026-10-01")
    assert already_emitted(settings, strat, date(2026, 10, 2)) == "2026-10-01_equal_weight_monthly.json"
    assert already_emitted(settings, strat, date(2026, 10, 1)) is None  # same-day rerun overwrites
    assert already_emitted(settings, strat, date(2026, 11, 2)) is None


def test_weekly_emits_once_per_week(settings):
    strat = MomentumTopN(universe=["SPY", "QQQ"])
    emit(settings, strat, pd.Series({"SPY": 1.0}), as_of="2026-10-15")  # Thu (Fri holiday)
    assert already_emitted(settings, strat, date(2026, 10, 16)) is not None
    assert already_emitted(settings, strat, date(2026, 10, 23)) is None


def test_daily_never_skipped(settings):
    strat = Ema20Trend()
    emit(settings, strat, pd.Series({"SOXL": 0.0}), as_of="2026-10-15")
    assert already_emitted(settings, strat, date(2026, 10, 16)) is None


def test_runner_skips_second_monthly_run(settings, closes, monkeypatch):
    monkeypatch.setattr(runner, "Settings", lambda: settings)
    _write_closes(settings, closes)
    today = closes.index[-1].date()
    monkeypatch.setattr("data.load.datetime", type("D", (), {
        "now": staticmethod(lambda tz=None: pd.Timestamp(today))}))
    assert runner.run_frequency("monthly") == 0
    # pretend an earlier session in the same month already emitted
    first = settings.signals_dir / f"{today.replace(day=1).isoformat()}_equal_weight_monthly.json"
    (settings.signals_dir / f"{today.isoformat()}_equal_weight_monthly.json").rename(first)
    assert runner.run_frequency("monthly") == 0
    assert [p.name for p in settings.signals_dir.iterdir()] == [first.name]


def test_health_ok_and_failures(settings, closes):
    report = health(settings)
    assert not report["ok"] and "missing" in report["problems"][0]

    _write_closes(settings, closes)
    last = closes.index[-1].date()
    report = health(settings, today=last)
    assert not report["ok"] and "no signals" in report["problems"][0]

    emit(settings, Ema20Trend(), pd.Series({"SOXL": 0.0}), as_of=last.isoformat())
    assert health(settings, today=last)["ok"]

    stale = health(settings, today=date(last.year + 1, 1, 1))
    assert not stale["ok"] and "stale" in stale["problems"][0]


def test_last_prices_uses_iex_feed_by_default(monkeypatch):
    import httpx

    from deployment.accounts import AlpacaAccount
    from deployment.execution import AlpacaClient

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"trade": {"p": 101.5}})

    monkeypatch.delenv("ALPACA_DATA_FEED", raising=False)
    client = AlpacaClient(AlpacaAccount("A", "k", "s", "https://paper-api.alpaca.markets"))
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.last_prices(["SPY"]) == {"SPY": 101.5}
    assert seen["url"] == "https://data.alpaca.markets/v2/stocks/SPY/trades/latest?feed=iex"
