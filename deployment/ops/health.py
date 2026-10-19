"""Health check: is the handoff fresh, and did today's runners emit signals?

Run by ``zen-health.timer`` after the pull and runners (or manually)::

    python -m deployment.ops.health

Prints a JSON snapshot and exits non-zero when unhealthy, so systemd's
``OnFailure=`` alerting fires:
- ``closes_latest.parquet`` missing or unreadable
- latest session older than ``max_staleness_days``
- no signal file for the latest session (the daily runners emit every session)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd

from data.config import Settings


def health(settings: Settings | None = None, today: date | None = None) -> dict:
    """Return a JSON-safe health snapshot with an overall ``ok`` flag."""
    settings = settings or Settings()
    today = today or datetime.now(UTC).date()
    out: dict = {"checked_at": datetime.now(UTC).isoformat(), "problems": []}

    closes = settings.latest_closes_path
    latest_session: date | None = None
    info: dict = {"path": str(closes), "exists": closes.exists()}
    if closes.exists():
        info["modified"] = datetime.fromtimestamp(closes.stat().st_mtime, tz=UTC).isoformat()
        try:
            latest_session = pd.read_parquet(closes).index[-1].date()
        except Exception as exc:  # noqa: BLE001 — any read failure is unhealthy
            out["problems"].append(f"closes unreadable: {exc}")
    else:
        out["problems"].append(f"handoff file missing: {closes}")

    if latest_session is not None:
        age = (today - latest_session).days
        info["latest_session"] = latest_session.isoformat()
        info["age_days"] = age
        if age > settings.max_staleness_days:
            out["problems"].append(
                f"closes stale: {latest_session} is {age}d old (max {settings.max_staleness_days})"
            )
    out["closes_latest"] = info

    sig_dir = settings.signals_dir
    signals = sorted(p.name for p in sig_dir.glob("*.json")) if sig_dir.exists() else []
    todays = (
        [s for s in signals if s.startswith(f"{latest_session.isoformat()}_")]
        if latest_session
        else []
    )
    out["signals"] = {"dir": str(sig_dir), "count": len(signals),
                      "latest": signals[-1] if signals else None,
                      "for_latest_session": todays}
    if latest_session and not todays:
        out["problems"].append(f"no signals emitted for session {latest_session}")

    out["ok"] = not out["problems"]
    return out


def main() -> None:
    report = health()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
