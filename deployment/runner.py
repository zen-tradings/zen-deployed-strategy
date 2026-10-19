"""Strategy runner: load latest data -> run strategies -> risk -> emit signals.

One invocation per frequency (driven by systemd timer / cron)::

    python -m deployment.runner --frequency daily

Fail-closed: any data-contract violation or signal-validation failure aborts
the run for that strategy; nothing partial is emitted.

Signals are written as JSON to ``<SIGNALS_DIR>/<date>_<strategy>.json``:
    {"strategy": ..., "as_of": ..., "generated_at": ..., "weights": {sym: w}}
Downstream execution (brokerage adapters) consumes these files.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime

import pandas as pd

from data.config import Settings, load_universes
from data.load import DataContractError, load_closes
from deployment.ops.log import setup_logging
from deployment.risk import RiskLimits, apply_risk
from strategies.base import Frequency, Strategy, validate_signals
from strategies.daily.rule.ema20_trend import Ema20Trend
from strategies.monthly.rule.equal_weight import EqualWeight
from strategies.weekly.rule.momentum_topn import MomentumTopN

log = logging.getLogger("deployment.runner")


def registry(universes: dict[str, list[str]]) -> list[Strategy]:
    """All deployed strategies. Adding/replacing a strategy is a reviewed code
    change here, backed by validation in the research repo."""
    return [
        Ema20Trend(symbol="SOXL"),
        MomentumTopN(universe=universes["weekly"]),
        EqualWeight(universe=universes["monthly"]),
    ]


def period_key(frequency: Frequency, as_of: date) -> str:
    """Rebalance period an ``as_of`` session belongs to (one signal per period)."""
    if frequency == "weekly":
        year, week, _ = as_of.isocalendar()
        return f"{year}-W{week:02d}"
    if frequency == "monthly":
        return f"{as_of.year}-{as_of.month:02d}"
    return as_of.isoformat()


def already_emitted(settings: Settings, strategy: Strategy, as_of: date) -> str | None:
    """Return the existing signal filename for this strategy's period, if any.

    Weekly/monthly timers may fire more than once per period (holidays,
    ``Persistent=true`` catch-up, monthly days 1-3); only the first emission
    in a period counts so execution never rebalances twice.
    """
    if strategy.frequency == "daily" or not settings.signals_dir.exists():
        return None
    key = period_key(strategy.frequency, as_of)
    for path in sorted(settings.signals_dir.glob(f"*_{strategy.name}.json")):
        try:
            existing = date.fromisoformat(path.name.split("_", 1)[0])
        except ValueError:
            continue
        if period_key(strategy.frequency, existing) == key and existing != as_of:
            return path.name
    return None


def emit(settings: Settings, strategy: Strategy, weights: pd.Series, as_of: str) -> None:
    """Atomically write the post-risk weights as a dated JSON signal file.

    Written to a temp file then ``os.replace``d so execution never reads a
    partially written signal.
    """
    settings.signals_dir.mkdir(parents=True, exist_ok=True)
    path = settings.signals_dir / f"{as_of}_{strategy.name}.json"
    payload = {
        "strategy": strategy.name,
        "frequency": strategy.frequency,
        "as_of": as_of,
        "generated_at": datetime.now(UTC).isoformat(),
        "weights": {k: round(float(v), 6) for k, v in weights.items()},
    }
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)
    log.info("%s: wrote %s weights=%s", strategy.name, path.name, payload["weights"])


def run_frequency(frequency: Frequency, limits: RiskLimits | None = None) -> int:
    """Run all strategies of ``frequency``. Returns the number of failures."""
    settings = Settings()
    universes = load_universes()
    failures = 0
    for strategy in registry(universes):
        if strategy.frequency != frequency:
            continue
        try:
            closes = load_closes(settings, strategy.universe)
            raw = validate_signals(strategy, strategy.generate_signals(closes))
            final = apply_risk(raw, closes, limits)
            as_of = closes.index[-1].date()
            existing = already_emitted(settings, strategy, as_of)
            if existing:
                log.info("%s: signal already emitted this %s period (%s) — skipping",
                         strategy.name, strategy.frequency, existing)
                continue
            emit(settings, strategy, final, as_of=as_of.isoformat())
        except (DataContractError, ValueError) as exc:
            failures += 1
            log.error("%s: FAILED CLOSED — no signal emitted: %s", strategy.name, exc)
    return failures


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run deployed strategies for one frequency.")
    parser.add_argument("--frequency", choices=["daily", "weekly", "monthly"], required=True)
    args = parser.parse_args()
    failures = run_frequency(args.frequency)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
