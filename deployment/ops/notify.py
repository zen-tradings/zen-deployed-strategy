"""Failure notifier invoked by systemd ``OnFailure=zen-notify@%n.service``.

    python -m deployment.ops.notify data-pull.service

Posts to ``ALERT_WEBHOOK_URL`` (Slack- and Discord-compatible payload) when
set; always logs to stdout/journald. Never raises — alerting must not fail
noisily on top of the original failure.
"""

from __future__ import annotations

import logging
import os
import socket
import sys

import httpx

from deployment.ops.log import setup_logging

log = logging.getLogger("deployment.ops.notify")


def notify(unit: str) -> bool:
    """Send a failure alert for ``unit``. Returns True if a webhook accepted it."""
    msg = (f"[zen-strategy] {unit} FAILED on {socket.gethostname()} — "
           f"check: journalctl -u {unit} -n 100")
    log.error(msg)
    url = os.environ.get("ALERT_WEBHOOK_URL", "")
    if not url:
        return False
    try:
        resp = httpx.post(url, json={"text": msg, "content": msg}, timeout=15)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("alert webhook failed: %s", exc)
        return False


def main() -> None:
    setup_logging()
    notify(sys.argv[1] if len(sys.argv) > 1 else "unknown-unit")


if __name__ == "__main__":
    main()
