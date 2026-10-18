# zen-deployed-strategy

**Deployment-only** runner for 6–9 daily / weekly / monthly quant strategies.

> **Boundary**: research, backtesting, model training, and notebooks live in a
> **separate research repository**. This repo consumes *finalized, validated*
> strategy logic and runs it in production: load data → run strategies →
> apply risk → emit signals. Data access is delegated to
> [`zen-massive-data-access`](https://github.com/zen-tradings/zen-massive-data-access)
> (Massive.com, ex-Polygon.io) — verified live.

## Architecture

```
Data server                         Strategy server
───────────                        ───────────────
systemd timer 17:10 ET             systemd timer 17:40 ET (per frequency)
python -m data.pull                python -m deployment.runner --frequency daily
  └─ massive_access.build_closes     ├─ data.load.load_closes   (fail-closed checks)
  └─ massive_access.write_closes     ├─ strategy.generate_signals(closes)
       │                             ├─ deployment.risk.apply_risk
       ▼                             └─ emit JSON signal files
  closes_YYYYMMDD.parquet   ──rsync/NFS──►  closes_latest.parquet
```

- **Handoff**: plain parquet files in a dated directory. No Kafka, no streaming,
  no fingerprint/immutable-bundle protocol — daily cadence is pull-shaped.
- **Fail-closed**: missing file, missing symbols, NaN gaps, or stale data
  (> `max_staleness_days`) ⇒ no signal is emitted, exit code 1, error logged.
- **Risk before orders**: per-position cap → vol scaling (de-risk only) →
  drawdown guard, applied to every strategy's raw weights.

## Layout

```
data/            production data layer (pull CLI on data server, loader on strategy server)
strategies/      frequency-first: daily/{rule,light_ml}, weekly/rule, monthly/rule + base.py
deployment/      runner.py, risk.py, scheduler/ (systemd + cron), ops/ (log, health)
config/          universes.yaml — symbol lists per frequency
tests/           deployment path only: data load, signal shape, risk
```

Strategy interface (all a strategy needs):

```python
class Strategy(Protocol):
    name: str
    frequency: Literal["daily", "weekly", "monthly"]
    universe: list[str]
    def generate_signals(self, closes: pd.DataFrame) -> pd.Series: ...  # target weights
```

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"      # installs massive-access from GitHub
.venv/bin/pytest -q
```

Environment:

| Variable | Server | Purpose |
|---|---|---|
| `MASSIVE_API_KEY` | data | Massive.com auth (used by `massive_access`) |
| `STRATEGY_DATA_DIR` | both | parquet handoff directory |
| `STRATEGY_SIGNALS_DIR` | strategy | output signal JSON files |
| `ALPACA_PAPER_N_KEY` / `_SECRET` | strategy | per-account creds (see below) |

### Secrets (Alpaca accounts)

**Keys and secrets are never committed.** The repo holds only the non-secret
mapping `config/accounts.yaml` (strategy → account alias). On the strategy
server, put real credentials in `/etc/zen-strategy/alpaca.env` (mode 600,
owned by the service user), loaded via systemd `EnvironmentFile`. Use
`.env.example` as the template. `deployment/accounts.py` resolves
`<ALIAS>_KEY`/`<ALIAS>_SECRET` at runtime and fails closed if missing.

## End-to-end example

```bash
# 1. Data server (after close): pull union of all universes to parquet
export MASSIVE_API_KEY=... STRATEGY_DATA_DIR=/var/lib/strategy-data
python -m data.pull --lookback-days 400
# → /var/lib/strategy-data/closes_20261016.parquet + closes_latest.parquet

# 2. Ship the directory to the strategy server (rsync/NFS), then:
export STRATEGY_DATA_DIR=/var/lib/strategy-data STRATEGY_SIGNALS_DIR=/var/lib/strategy-signals
python -m deployment.runner --frequency daily
# → loads closes_latest.parquet, fail-closed checks,
#   runs ema20_trend_soxl → raw weights {SOXL: 1.0}
#   applies risk (cap 0.5, vol scaling) → final weights
#   writes /var/lib/strategy-signals/2026-10-16_ema20_trend_soxl.json

# 3. Execute a signal on its mapped Alpaca account (PLAN-ONLY by default)
python -m deployment.execution --signal /var/lib/strategy-signals/2026-10-16_ema20_trend_soxl.json
# → resolves account from config/accounts.yaml + env creds, fetches equity &
#   positions, plans whole-share DAY limit orders (±20 bps buffer), logs them.
# Add --submit to actually place the orders.

# 4. Health check (either server)
python -m deployment.ops.health
```

## Scheduling

systemd units in `deployment/scheduler/` (`data-pull.{service,timer}`,
`strategy-run@.service` + per-frequency timers) or `cron.example`.
Pull at 17:10 ET; runners at 17:40 ET so the handoff has landed.

## Adding / replacing a strategy

1. Validate the strategy in the **research repo** (backtests live there).
2. Port the final logic under `strategies/<frequency>/{rule,light_ml}/`
   implementing `generate_signals`.
3. Register it in `deployment/runner.py::registry` and add a signal-shape test.
4. Light ML is allowed **only as a filter** on rule signals, loading a frozen
   artifact exported by the research repo (see `strategies/daily/light_ml/`).

## Intentionally excluded

- Research notebooks, training pipelines, backtest engines → research repo.
- Intraday data/strategies and streaming infra (Kafka/NATS) → not needed at
  daily cadence; revisit only if intraday ever becomes a requirement.
- Data fingerprinting / immutable-bundle consistency protocols → plain dated
  parquet + atomic rename (from `massive_access.write_closes`) is sufficient.
