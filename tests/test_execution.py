"""Order-planning tests (pure function — no API calls)."""

from __future__ import annotations

import pytest

from deployment.execution import ExecutionError, plan_orders


def test_buy_from_flat():
    orders = plan_orders({"SPY": 0.5}, equity=10_000, prices={"SPY": 500.0}, positions={})
    assert len(orders) == 1
    o = orders[0]
    assert (o.side, o.qty, o.symbol) == ("buy", 10, "SPY")
    assert o.limit_price == pytest.approx(501.0, abs=0.01)  # +20 bps buffer


def test_sell_down_to_target():
    orders = plan_orders({"SPY": 0.0}, equity=10_000, prices={"SPY": 500.0},
                         positions={"SPY": 10})
    assert orders[0].side == "sell" and orders[0].qty == 10
    assert orders[0].limit_price == pytest.approx(499.0, abs=0.01)  # -20 bps buffer


def test_no_order_when_at_target():
    orders = plan_orders({"SPY": 0.5}, equity=10_000, prices={"SPY": 500.0},
                         positions={"SPY": 10})
    assert orders == []


def test_whole_shares_floor():
    # 0.5 * 10_000 / 333 = 15.01... -> 15 shares
    orders = plan_orders({"QQQ": 0.5}, equity=10_000, prices={"QQQ": 333.0}, positions={})
    assert orders[0].qty == 15


def test_untouched_symbols_outside_weights():
    orders = plan_orders({"SPY": 0.0}, equity=10_000, prices={"SPY": 500.0},
                         positions={"SPY": 0, "TLT": 100})
    assert orders == []  # TLT held but not managed by this strategy


def test_bad_price_fails_closed():
    with pytest.raises(ExecutionError):
        plan_orders({"SPY": 0.5}, equity=10_000, prices={"SPY": 0.0}, positions={})
