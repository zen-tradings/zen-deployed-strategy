# Install — single droplet (`zen-trading-strategy-layer`, Ubuntu 24.04)

One host runs both roles: the **data pull** and the **strategy runners** share
`/var/lib/strategy-data`, so no rsync/NFS is needed. Everything runs as the
unprivileged `zen` user under systemd; secrets live only in `/etc/zen-strategy/`.

| Unit | When (ET) | Does |
|---|---|---|
| `data-pull.timer` | Mon–Fri 17:10 | Massive → `closes_latest.parquet` |
| `strategy-run@daily.timer` | Mon–Fri 17:40 | daily signals |
| `strategy-run@weekly.timer` | Fri 17:45 | weekly signals (once per ISO week) |
| `strategy-run@monthly.timer` | days 1–3, 17:50 | monthly signals (once per month) |
| `zen-health.timer` | Mon–Fri 18:15 | fails if data stale / no signals today |
| `zen-notify@.service` | on any failure | webhook alert + journald |

Order **execution is manual** (plan-only by default) — see step 7.

## 1. Base packages + service user

```bash
sudo apt-get update && sudo apt-get install -y git python3.12 python3.12-venv curl
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
sudo useradd --system --create-home --home-dir /var/lib/zen --shell /usr/sbin/nologin zen
timedatectl   # any host TZ is fine — timers pin America/New_York explicitly
```

## 2. Code + venv in /opt

```bash
sudo git clone https://github.com/zen-tradings/zen-deployed-strategy.git /opt/zen-deployed-strategy
sudo chown -R zen:zen /opt/zen-deployed-strategy
cd /opt/zen-deployed-strategy
# Use the SYSTEM interpreter: a uv-managed Python under a home dir would be
# hidden from the units by ProtectHome=true.
sudo -u zen uv venv --python /usr/bin/python3.12 .venv
sudo -u zen uv pip install --python .venv/bin/python -e ".[dev]"
sudo -u zen .venv/bin/pytest -q
```

## 3. Secrets (`/etc/zen-strategy`, never in git)

Use `.env.example` as the template; split it into the four files below.

```bash
sudo install -d -m 750 -o root -g zen /etc/zen-strategy
for f in data runner alpaca alerts; do
  sudo install -m 640 -o root -g zen /dev/null /etc/zen-strategy/$f.env
done
sudo chmod 600 /etc/zen-strategy/alpaca.env && sudo chown zen:zen /etc/zen-strategy/alpaca.env
sudoedit /etc/zen-strategy/data.env     # MASSIVE_API_KEY, STRATEGY_DATA_DIR=/var/lib/strategy-data
sudoedit /etc/zen-strategy/runner.env   # STRATEGY_DATA_DIR, STRATEGY_SIGNALS_DIR=/var/lib/strategy-signals
sudoedit /etc/zen-strategy/alpaca.env   # ALPACA_PAPER_N_KEY/_SECRET, ALPACA_DATA_FEED=iex
sudoedit /etc/zen-strategy/alerts.env   # ALERT_WEBHOOK_URL (optional; Slack/Discord)
```

The runner units deliberately do **not** load `alpaca.env` — only manual
execution needs broker credentials.

## 4. Install + verify units

```bash
sudo cp deployment/scheduler/*.service deployment/scheduler/*.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/data-pull.service \
  /etc/systemd/system/strategy-run@daily.service /etc/systemd/system/zen-health.service \
  /etc/systemd/system/zen-notify@x.service      # must print nothing
for t in data-pull strategy-run@daily strategy-run@weekly strategy-run@monthly zen-health; do
  systemd-analyze calendar "$(grep ^OnCalendar /etc/systemd/system/$t.timer | cut -d= -f2)"
done
sudo systemctl daemon-reload
```

## 5. First manual run (before enabling timers)

```bash
sudo systemctl start data-pull.service           && journalctl -u data-pull -n 30 --no-pager
sudo systemctl start strategy-run@daily.service  && journalctl -u strategy-run@daily -n 30 --no-pager
sudo systemctl start zen-health.service          && journalctl -u zen-health -n 40 --no-pager
ls -l /var/lib/strategy-data /var/lib/strategy-signals
sudo systemctl start zen-notify@test.service     # confirms the alert webhook works
```

## 6. Enable the schedule

```bash
sudo systemctl enable --now data-pull.timer strategy-run@daily.timer \
  strategy-run@weekly.timer strategy-run@monthly.timer zen-health.timer
systemctl list-timers 'data-pull*' 'strategy-run*' 'zen-health*'
```

## 7. Execution (manual, plan-only first)

```bash
cd /opt/zen-deployed-strategy
SIG=$(ls -t /var/lib/strategy-signals/*.json | head -1)
sudo -u zen bash -c "set -a; . /etc/zen-strategy/alpaca.env; .venv/bin/python -m deployment.execution --signal $SIG"
# after several clean plan-only days, add --submit
```

Signals land after the close (17:40+ ET), so DAY limit orders queue for the
next session at last price ±20 bps — an opening gap beyond that won't fill.

## Upgrades

```bash
cd /opt/zen-deployed-strategy && sudo -u zen git pull --ff-only
sudo -u zen uv pip install --python .venv/bin/python -e ".[dev]" && sudo -u zen .venv/bin/pytest -q
sudo cp deployment/scheduler/*.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload
```

## Known gaps

- `drawdown_guard` is a no-op until a per-strategy equity curve is wired in.
- Execution is not scheduled; there is no position reconciliation journal yet.
