# zen-deployed-strategy — Design Plan

A deployed strategy system with two main parts:

1. **Data layer** — read market data from the data server (our massive data client is already deployed there).
2. **Strategy layer** — run and execute different kinds of strategies, monitor their performance, and replace/update strategies over time.

Supporting both: a **backtest gate** — every strategy (new or updated) must pass backtesting before it is deployed.

---

## 1. Architecture Overview

```
┌─────────────────────┐
│   Data Server        │   massive data client (zen-massive-data-access,
│   (Massive.com API)  │   Massive.com / ex-Polygon.io, Advanced plan)
└─────────┬───────────┘
          │  adjusted daily closes, NBBO quotes, session calendar
          ▼
┌─────────────────────┐      ┌──────────────────────┐
│   Data Access Layer  │◄────►│  Local Cache          │
│   (consumer client)  │      │  (parquet / SQLite)   │
└─────────┬───────────┘      └──────────────────────┘
          ▼
┌───────────────────────────────────────────────┐
│   Strategy Runner                              │
│   ┌──────────────────┐  ┌──────────────────┐  │
│   │ Rule-based        │  │ ML-based          │  │
│   │ (e.g. soxl_ema20) │  │ (e.g. RecurrentPPO│  │
│   │                   │  │  rebalancer)      │  │
│   └──────────────────┘  └──────────────────┘  │
└─────────┬─────────────────────────┬───────────┘
          ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐
│  Execution           │   │  Performance Monitor │
│  (Alpaca, paper)     │   │  + journaling        │
└─────────────────────┘   └─────────┬───────────┘
                                    ▼
                          ┌─────────────────────┐
                          │  Strategy Lifecycle  │
                          │  replace / update /  │
                          │  retire decisions    │
                          └─────────┬───────────┘
                                    ▼
                          ┌─────────────────────┐
                          │  Backtest Gate       │
                          │  (must pass before   │
                          │   deploy)            │
                          └─────────────────────┘
```

Key boundary: **Massive is data-only; Alpaca keeps brokerage** (account, positions, orders).

---

## 2. Part 1 — Data Access

### 2.1 Source
- Data server hosts the massive data client (`zen-massive-data-access`), a separate deployable service acting as a **distributor to N strategy consumers** across servers/accounts.
- Backed by Massive.com API (`https://api.massive.com`, Bearer auth via `MASSIVE_API_KEY`).

### 2.2 Data contract (what strategies consume)
- **Adjusted daily closes DataFrame**: tz-naive midnight session index, exact symbol columns, completed sessions only, *no partial today bar*, fail-closed on gaps.
- **Latest NBBO quotes** for order pricing.
- **NYSE session calendar** (including early closes/holidays) for scheduling.

### 2.3 Data transport decision: pull-based HTTP, no streaming (for now)

**Decision**: use plain request/response (HTTP API on the data server wrapping `massive_access`) — **no Kafka or other streaming layer**.

Rationale:
- Daily cadence is pull-shaped: each strategy wakes on a systemd timer, requests completed sessions through yesterday, validates, trades. Request/response matches this exactly.
- The fail-closed contract (no partial bar, no gaps, staleness check) is a validation on a snapshot — much simpler with pull than reasoning about consumer lag/offsets/replays on a stream.
- Small N of consumers, a few dozen requests/day: a Kafka/Redpanda/NATS cluster is unjustified operational overhead.
- NBBO quotes are needed once at order-planning time — a single REST call suffices.

Proposed endpoints: `/closes?symbols=...&through=...`, `/nbbo/{symbol}`, `/calendar`, `/latest-session` (readiness check instead of polling).

**Revisit streaming only if** we move to intraday/real-time strategies (tick or minute-bar streams via Massive websockets), many consumers needing the same live feed (duplicate pulls become rate-limited/costly), or an event-sourced audit trail across machines. If that happens, prefer NATS JetStream or Redpanda over vanilla Kafka (lighter to operate at our scale).

### 2.4 Consumer-side responsibilities
- Thin client that fetches from the data server, validates the contract (shape, gaps, staleness), and fails closed on any violation.
- Local parquet/SQLite cache to survive transient data-server outages and avoid redundant pulls.
- Staleness check: refuse to trade if the latest completed session is older than expected per the session calendar.

---

## 3. Part 2 — Strategy Running & Execution

### 3.1 Strategy types
| Type | Examples | Inputs | Decision style |
|---|---|---|---|
| **Rule-based** | `soxl_ema20` (EMA-20 crossover) | daily closes | deterministic signals |
| **ML-based** | RecurrentPPO rebalancer, rank-* variants | daily closes, features | model inference → target weights |

Both implement one common interface:

```python
class Strategy(Protocol):
    name: str
    universe: list[str]
    def target_positions(self, data: MarketData, portfolio: Portfolio) -> TargetWeights: ...
```

### 3.2 Execution
- Alpaca **paper accounts** (plan-only by default; explicit flag required to submit).
- Whole-share **DAY limit orders**, priced off latest NBBO.
- Each strategy runs as an isolated systemd unit (pattern already used: `rebalance@baseline`, `rebalance@rank-*`, rule-based units), one unit per strategy instance / account.
- SQLite journaling of every run: inputs snapshot hash, signals, intended orders, submitted orders, fills.

### 3.3 Scheduling
- Daily cadence driven by the NYSE session calendar (skip holidays, respect early closes).
- Runner order per session: fetch data → validate → compute targets → diff vs. current positions → plan orders → (optionally) submit → journal.

---

## 4. Strategy Lifecycle — Monitor, Replace, Update

### 4.1 Performance monitoring
- Compute per-strategy metrics from journal + account data: cumulative return, Sharpe, max drawdown, turnover, hit rate, slippage vs. plan, benchmark-relative return.
- Rolling windows (e.g. 20/60/120 sessions) so decisions use recent evidence, not just lifetime stats.
- Persist metrics to SQLite; optional daily summary report.

### 4.2 Replace / update rules
- **Review triggers** (any of):
  - drawdown beyond threshold (e.g. > X% from peak),
  - rolling Sharpe below floor for N sessions,
  - underperforms benchmark/baseline by Y% over the window,
  - data/execution anomalies (repeated failed runs, excessive slippage).
- **Actions**:
  - *Rule-based*: tune parameters (e.g. EMA window, bands) → re-backtest → redeploy; or retire.
  - *ML-based*: retrain/fine-tune model on extended data → re-backtest → redeploy; or roll back to previous model checkpoint.
  - *Replace*: promote a candidate strategy from the research pipeline that beat the incumbent in backtest + paper trial.
- Every change is versioned (strategy name + version in journal), with the previous version retained for rollback.

### 4.3 Promotion pipeline
```
research idea → backtest gate → paper deployment (trial) → monitored period → promote / retire
```

---

## 5. Backtest Gate (before any deploy)

### 5.1 Requirements
- Same code path as live: the backtester calls the **same** `Strategy.target_positions` interface and the **same** data contract (adjusted daily closes from the massive client), so backtest ≈ deployed behavior.
- Realistic frictions: commission-free but model slippage/limit-fill behavior consistent with DAY limit orders; whole shares only.
- Point-in-time discipline: only completed sessions visible at decision time; no lookahead (matches the "no partial today bar" contract).

### 5.2 Acceptance criteria (per strategy, before deploy)
- Out-of-sample period required (train/validation split for ML; parameter-selection split for rule-based).
- Must meet minimum bar vs. baseline (equal-weight baseline is the reference), e.g.:
  - positive OOS return and Sharpe above threshold,
  - max drawdown within limit,
  - turnover within cost-feasible range.
- Backtest report stored (config, data range, metrics, equity curve) and referenced in the deploy record.

### 5.3 Workflow
1. Candidate strategy (new, tuned, or retrained) is defined with a config file.
2. Run backtest against the gate criteria.
3. If pass → deploy to a paper account as a new systemd unit (or replace existing unit's version).
4. If fail → record result, iterate or discard.

---

## 6. Repository Layout (proposed)

```
zen-deployed-strategy/
├── plan.md                  # this document
├── pyproject.toml
├── src/deployed_strategy/
│   ├── data/                # data-server client wrapper, contract validation, cache
│   ├── strategies/
│   │   ├── base.py          # Strategy protocol
│   │   ├── rule_based/      # soxl_ema20, ...
│   │   └── ml_based/        # ppo_rebalance, ...
│   ├── execution/           # Alpaca adapter, order planning, limits, submit
│   ├── backtest/            # engine, fills model, metrics, gate criteria
│   ├── monitor/             # performance metrics, review triggers, reports
│   ├── lifecycle/           # versioning, promote/retire/rollback
│   └── journal/             # SQLite schema + writers
├── configs/                 # per-strategy configs (universe, params, account)
├── deployment/              # systemd unit templates, deploy scripts
└── tests/
```

---

## 7. Milestones

- **Phase 0 — Scaffold**: repo layout, pyproject (uv + Python 3.12, ruff, pytest), Strategy protocol, config schema.
- **Phase 1 — Data layer**: data-server client wrapper, contract validation, cache, staleness checks.
- **Phase 2 — Backtest engine**: point-in-time engine, fills model, metrics, gate criteria + report.
- **Phase 3 — Execution runner**: order planning/diffing, Alpaca paper adapter (plan-only default), journaling, systemd units.
- **Phase 4 — Strategies**: port rule-based (`soxl_ema20`) and ML-based (PPO rebalancer) behind the common interface; pass backtest gate.
- **Phase 5 — Monitoring & lifecycle**: metrics jobs, review triggers, versioned replace/update/rollback, promotion pipeline.

---

## 8. Conventions & Constraints

- Paper trading only until explicitly changed; plan-only is the default mode.
- Fail-closed everywhere: bad/stale/gapped data ⇒ no trade.
- All deploy decisions must reference a passing backtest report.
- Secrets via env vars (`MASSIVE_API_KEY`, Alpaca keys); never committed.
- Dev loop: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`, then `ruff check .` and `pytest -q`.
