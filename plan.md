# zen-deployed-strategy — Deployment Plan

A **deployment-only** quantitative strategy project for 6–9 live/paper strategies.

**Scope boundary**: research, backtesting frameworks, model training, and exploratory
notebooks live in a **separate research repository**. This repo only consumes
finalized, already-validated strategy logic and runs it in production:
load data → run strategies → apply risk controls → emit signals/orders.

---

## 1. Constraints & Context

- Frequencies: **daily / multi-day, weekly, monthly** only — no intraday.
- Data: Massive.com (ex-Polygon.io) Advanced plan; **daily adjusted bars are sufficient**.
- Environment: volatile markets → prefer simple, robust, interpretable rules;
  **light ML only as an optional filter**, never as the primary signal.
- Data pull and strategy execution may run on **separate servers**; handoff is
  simple **parquet files in a dated directory** (rsync/NFS/scp — no streaming,
  no fingerprint system, no immutable-bundle protocol).
- Python 3.12 + pandas; scheduling via **systemd timers or cron**.

## 2. Architecture

```
┌──────────────────────┐   after-close cron/timer
│ Data server           │   data/pull.py → parquet
│ (Massive client)      │   DATA_DIR/closes/YYYY-MM-DD.parquet (+ latest.parquet)
└──────────┬───────────┘
           │  simple file handoff (dated parquet directory)
           ▼
┌──────────────────────┐   per-frequency timer
│ Strategy server       │   deployment/runner.py --frequency daily|weekly|monthly
│                       │   load latest parquet → fail-closed checks →
│                       │   generate_signals(closes) → risk → emit signals/orders
└──────────────────────┘
```

## 3. Repository Layout

```
project/
├── data/                          # production data-access layer
│   ├── pull.py                    # CLI wrapping massive_access (build_closes/write_closes)
│   ├── load.py                    # consumer-side loader + fail-closed validation
│   └── config.py
├── strategies/                    # only deployment-ready strategy implementations
│   ├── daily/                     # 3–5 strategies
│   │   ├── rule/
│   │   └── light_ml/              # optional filters only
│   ├── weekly/                    # 2–3 strategies
│   │   └── rule/
│   ├── monthly/                   # 1–2 strategies
│   │   └── rule/
│   └── base.py                    # minimal Strategy interface
├── deployment/
│   ├── runner.py                  # load latest data → run strategy → emit signals/orders
│   ├── risk.py                    # position limits, vol scaling, drawdown guards
│   ├── scheduler/                 # systemd timer / cron examples
│   └── ops/                       # logging, fail-closed checks, health
├── config/
│   └── universes.yaml             # symbol lists per frequency
├── tests/                         # focused on deployment path (data load, signal shape, risk)
└── README.md                      # deployment architecture + runbook
```

Top-level organization is **frequency-first** (daily/weekly/monthly); rule vs
light-ML is only a sub-folder within each frequency.

## 4. Key Design Decisions

1. **Strategy interface is minimal**: a strategy only needs
   `generate_signals(closes: pd.DataFrame) -> pd.Series` (target weights,
   index = symbols). Everything else (data, risk, scheduling, output) is shared
   infrastructure.
2. **Reuse, don't reimplement**: data access depends on the live-verified
   `massive-access` package (zen-massive-data-access) — contract enforcement
   (adjusted bars, completed sessions, SPY-calendar gap detection, atomic
   parquet writes) lives there.
3. **Fail-closed everywhere**: incomplete current session excluded at pull time;
   runner refuses to emit signals if data is stale, has gaps, or misses symbols.
4. **Risk before orders**: `deployment/risk.py` (per-position cap, portfolio
   vol scaling, drawdown guard) is applied to every strategy's raw weights
   before anything is emitted.
5. **Simple handoff**: dated parquet (`closes_YYYYMMDD.parquet`) plus
   `closes_latest.parquet` as the consumer contract. No Kafka/streaming
   (daily cadence is pull-shaped).
6. **Light ML = filter only**: an optional post-filter on rule signals (e.g.
   regime/vol classifier loaded from a frozen artifact). Training happens in the
   research repo; this repo only loads artifacts and applies them.

## 5. Intentionally Excluded

- Research notebooks, training pipelines, backtest engines (research repo).
- Intraday data/strategies and streaming infrastructure (Kafka/NATS).
- Data fingerprinting / immutable-bundle consistency protocols.
- Strategy auto-promotion logic — replacing/updating a strategy is a code change
  that was validated in the research repo first.

## 6. Milestones

- **Phase 0** — scaffold: layout, pyproject, Strategy interface, universes.yaml. ✅
- **Phase 1** — data layer: pull CLI delegating to `massive-access`, consumer loader with fail-closed checks. ✅ (live-verified against Massive)
- **Phase 2** — runner + risk + ops: fail-closed checks, logging, signal output. ✅ (scaffolded with tests)
- **Phase 3** — strategies: port remaining validated implementations to reach 3–5 daily, 2–3 weekly, 1–2 monthly.
- **Phase 4** — scheduling & ops hardening: install systemd timers on both servers, health checks, runbook.
