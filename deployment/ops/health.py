"""Health summary: did today's pull and runs happen, and are signals fresh?

Intended for a cron'd check or manual inspection::

    python -m deployment.ops.health
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from data.config import Settings


def health() -> dict:
    """Return a JSON-safe health snapshot of the handoff and signal files."""
    settings = Settings()
    out: dict = {"checked_at": datetime.now(UTC).isoformat()}

    closes = settings.latest_closes_path
    out["closes_latest"] = {
        "path": str(closes),
        "exists": closes.exists(),
        "modified": datetime.fromtimestamp(closes.stat().st_mtime, tz=UTC).isoformat()
        if closes.exists()
        else None,
    }

    sig_dir = settings.signals_dir
    signals = sorted(sig_dir.glob("*.json")) if sig_dir.exists() else []
    out["signals"] = {"dir": str(sig_dir), "count": len(signals),
                      "latest": signals[-1].name if signals else None}
    return out


if __name__ == "__main__":
    print(json.dumps(health(), indent=2))
