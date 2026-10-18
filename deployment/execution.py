"""Alpaca paper execution adapter: signal JSON -> whole-share DAY limit orders.

Plan-only by default — orders are computed and logged but NOT submitted unless
``--submit`` is passed explicitly. One signal file maps to one Alpaca account
via ``config/accounts.yaml`` + server-side env credentials.

Usage::

    python -m deployment.execution --signal /var/lib/strategy-signals/2026-10-16_ema20_trend_soxl.json
    python -m deployment.execution --signal ... --submit   # actually place orders

Order logic:
- target dollar value per symbol = account equity * weight
- delta vs current position -> whole shares (floor), skip dust (< 1 share)
- DAY limit orders: buy at last price * (1 + buffer), sell at * (1 - buffer)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from deployment.accounts import AlpacaAccount, resolve_account
from deployment.ops.log import setup_logging

log = logging.getLogger("deployment.execution")

LIMIT_BUFFER = 0.002  # 20 bps through the last price so DAY limits fill


class ExecutionError(RuntimeError):
    """Raised on Alpaca API failures or malformed signals (fail-closed)."""


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str          # "buy" | "sell"
    qty: int           # whole shares
    limit_price: float


class AlpacaClient:
    """Minimal authenticated Alpaca REST client (paper accounts)."""

    def __init__(self, account: AlpacaAccount, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=account.base_url,
            headers={
                "APCA-API-KEY-ID": account.key,
                "APCA-API-SECRET-KEY": account.secret,
            },
            timeout=timeout,
        )

    def _get(self, path: str) -> Any:
        resp = self._http.get(path)
        if resp.status_code != 200:
            raise ExecutionError(f"GET {path}: HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def equity(self) -> float:
        return float(self._get("/v2/account")["equity"])

    def positions(self) -> dict[str, int]:
        """Current whole-share position per symbol (fractional truncated)."""
        return {p["symbol"]: int(float(p["qty"])) for p in self._get("/v2/positions")}

    def last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Latest trade price per symbol (Alpaca market-data endpoint)."""
        out: dict[str, float] = {}
        for sym in symbols:
            resp = self._http.get(
                f"https://data.alpaca.markets/v2/stocks/{sym}/trades/latest"
            )
            if resp.status_code != 200:
                raise ExecutionError(f"last price {sym}: HTTP {resp.status_code}")
            out[sym] = float(resp.json()["trade"]["p"])
        return out

    def submit(self, order: Order) -> str:
        resp = self._http.post(
            "/v2/orders",
            json={
                "symbol": order.symbol,
                "qty": str(order.qty),
                "side": order.side,
                "type": "limit",
                "limit_price": str(order.limit_price),
                "time_in_force": "day",
            },
        )
        if resp.status_code not in (200, 201):
            raise ExecutionError(f"submit {order}: HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()["id"]

    def close(self) -> None:
        self._http.close()


def plan_orders(
    weights: dict[str, float],
    equity: float,
    prices: dict[str, float],
    positions: dict[str, int],
) -> list[Order]:
    """Compute whole-share DAY limit orders moving positions toward targets.

    Pure function — unit-testable without any API. Symbols held but absent
    from ``weights`` are left untouched (a strategy only manages its universe).
    """
    orders: list[Order] = []
    for sym, weight in sorted(weights.items()):
        price = prices[sym]
        if price <= 0:
            raise ExecutionError(f"{sym}: non-positive price {price}")
        target_qty = math.floor(equity * weight / price)
        delta = target_qty - positions.get(sym, 0)
        if delta == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        buffer = LIMIT_BUFFER if delta > 0 else -LIMIT_BUFFER
        orders.append(
            Order(
                symbol=sym,
                side=side,
                qty=abs(delta),
                limit_price=round(price * (1 + buffer), 2),
            )
        )
    return orders


def execute_signal(signal_path: Path | str, submit: bool = False) -> list[Order]:
    """Load one signal file, plan orders against its mapped account, and
    (only with ``submit=True``) place them. Returns the planned orders."""
    payload = json.loads(Path(signal_path).read_text())
    strategy, weights = payload["strategy"], payload["weights"]

    account = resolve_account(strategy)  # fail-closed if unmapped / no creds
    client = AlpacaClient(account)
    try:
        equity = client.equity()
        positions = client.positions()
        prices = client.last_prices(list(weights))
        orders = plan_orders(weights, equity, prices, positions)

        mode = "SUBMIT" if submit else "PLAN-ONLY"
        log.info("%s %s: equity=%.2f orders=%s", mode, strategy,
                 equity, [asdict(o) for o in orders] or "none")
        if submit:
            for order in orders:
                order_id = client.submit(order)
                log.info("%s: submitted %s %d %s @ %.2f id=%s", strategy,
                         order.side, order.qty, order.symbol, order.limit_price, order_id)
        return orders
    finally:
        client.close()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Execute one signal file on its Alpaca account.")
    parser.add_argument("--signal", required=True, help="path to a signal JSON file")
    parser.add_argument("--submit", action="store_true",
                        help="actually place orders (default: plan-only)")
    args = parser.parse_args()
    execute_signal(args.signal, submit=args.submit)


if __name__ == "__main__":
    main()
