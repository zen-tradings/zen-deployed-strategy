"""Logging setup for runners: stdout (journald captures it) at INFO."""

from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once per process; systemd/journald handles the rest."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        force=False,
    )
