"""Resolve Alpaca credentials for a strategy from env vars (never from the repo).

``config/accounts.yaml`` maps strategy name -> account alias; the server's
``/etc/zen-strategy/alpaca.env`` (loaded via systemd ``EnvironmentFile``)
provides ``<ALIAS>_KEY`` / ``<ALIAS>_SECRET``. Fail-closed: missing mapping or
missing env vars raise before any order could be attempted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


class CredentialsError(RuntimeError):
    """Raised when a strategy's account credentials cannot be resolved."""


@dataclass(frozen=True)
class AlpacaAccount:
    alias: str
    key: str
    secret: str
    base_url: str


def load_account_map(path: Path | str = "config/accounts.yaml") -> dict[str, str]:
    """Load the non-secret strategy -> account alias mapping."""
    with open(path) as fh:
        return dict(yaml.safe_load(fh))


def resolve_account(strategy_name: str, account_map: dict[str, str] | None = None) -> AlpacaAccount:
    """Resolve credentials for ``strategy_name`` from the environment.

    Raises:
        CredentialsError: unmapped strategy, or key/secret missing from env.
    """
    account_map = account_map or load_account_map()
    alias = account_map.get(strategy_name)
    if not alias:
        raise CredentialsError(f"no account mapped for strategy {strategy_name!r}")
    key = os.environ.get(f"{alias}_KEY", "")
    secret = os.environ.get(f"{alias}_SECRET", "")
    if not key or not secret:
        raise CredentialsError(f"{alias}_KEY / {alias}_SECRET not set in environment")
    return AlpacaAccount(
        alias=alias,
        key=key,
        secret=secret,
        base_url=os.environ.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets"),
    )
