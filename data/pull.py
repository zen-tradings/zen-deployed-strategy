"""After-close data pull CLI (runs on the data server).

Thin wrapper around ``massive_access`` (zen-massive-data-access): pulls daily
adjusted closes for the union of all universes and writes the parquet handoff
via ``write_closes`` (atomic temp-file + rename):

    <DATA_DIR>/closes_YYYYMMDD.parquet
    <DATA_DIR>/closes_latest.parquet

All contract enforcement (adjusted bars, completed sessions only, SPY-calendar
gap detection, fail-closed on missing data) lives in ``massive_access`` — this
module adds nothing but universe resolution and the output location.

Usage (after market close, via systemd timer or cron)::

    MASSIVE_API_KEY=... STRATEGY_DATA_DIR=/var/lib/strategy-data \
        python -m data.pull --lookback-days 400
"""

from __future__ import annotations

import argparse
import logging

from massive_access import MassiveClient, build_closes, write_closes

from data.config import Settings, all_symbols, load_universes

log = logging.getLogger("data.pull")


def pull(lookback_days: int = 400) -> None:
    """Pull, build, and write the daily closes parquet. Fail-closed: any
    contract violation inside ``massive_access`` raises and nothing is written."""
    settings = Settings()
    symbols = all_symbols(load_universes())

    with MassiveClient() as client:  # reads MASSIVE_API_KEY from the environment
        closes = build_closes(client, symbols, lookback_days=lookback_days)

    path = write_closes(closes, settings.data_dir)
    log.info("wrote %s (%d sessions x %d symbols)", path, len(closes), len(closes.columns))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Pull daily adjusted closes to parquet.")
    parser.add_argument("--lookback-days", type=int, default=400)
    args = parser.parse_args()
    pull(lookback_days=args.lookback_days)


if __name__ == "__main__":
    main()
