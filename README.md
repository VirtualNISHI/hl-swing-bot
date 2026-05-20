# hl-swing-bot

Hyperliquid BTC swing trading bot — currently **Phase 0: data collection only**.

This phase just accumulates market data into a local DuckDB file so that, in 1–2 months, there is enough history to train an ML model and backtest a strategy. **No trading is performed.**

## What gets collected

| Table | Frequency | Source |
|---|---|---|
| `candles` (OHLCV) | 1m bars, last 120 min per poll | `candleSnapshot` |
| `perp_snapshots` (mark / volume / OI / funding) | One row per poll | `metaAndAssetCtxs` |

All for `BTC` perp by default. Configurable via `.env`.

## Setup

```powershell
# 1. Create venv and install (uv recommended)
uv venv
uv pip install -e .

# 2. Copy env template and edit
copy .env.example .env
# → open .env, paste your Discord webhook URL into DISCORD_WEBHOOK_URL

# 3. Verify Discord webhook
.venv\Scripts\python -m hl_swing_bot.notify "hl-swing-bot setup OK"

# 4. Run one collection cycle to verify
.venv\Scripts\python -m hl_swing_bot.collector --once --verbose
```

Expected output of step 4:

```
... hyperliquid: fetched 1XX candles for BTC
... hyperliquid: fetched ~200 perpetuals
{'candles_upserted': 120, 'snapshots_inserted': 1, 'total_candles_in_db': 120, ...}
```

The DuckDB file appears at `data/market.duckdb`.

## Run continuously

**Recommended: GitHub Actions cron** — see [DEPLOYMENT.md](DEPLOYMENT.md). 5-min schedule, free on public repos, matches the pattern used by sibling projects (`Btc_alert_bot`, `hyperliquid-tracker`).

Local alternatives below.

### Option A: keep a terminal open (simplest)

```powershell
.venv\Scripts\python -m hl_swing_bot.collector --interval 60
```

Polls every 60 seconds. Stop with Ctrl+C.

### Option B: Windows Task Scheduler (recommended for unattended)

1. Open Task Scheduler → Create Task
2. Triggers → New → Repeat every 5 minutes, indefinitely
3. Actions → New → Program: `C:\User\projects\hl-swing-bot\scripts\run_collector.bat`
4. Settings → "Run whether user is logged on or not"

### Option C: WSL2 cron (if you prefer Linux)

```cron
*/5 * * * * cd /mnt/c/User/projects/hl-swing-bot && .venv/bin/python -m hl_swing_bot.collector --once
```

## Inspect collected data

```python
import duckdb
con = duckdb.connect("data/market.duckdb", read_only=True)
con.sql("SELECT COUNT(*) FROM candles").show()
con.sql("SELECT * FROM candles ORDER BY open_time_ms DESC LIMIT 5").show()
con.sql("SELECT * FROM perp_snapshots ORDER BY snapshot_time_ms DESC LIMIT 5").show()
```

## Roadmap

| Phase | Status | Description | Spec |
|---|---|---|---|
| **0** | 🟢 running | Data collection (this) | this README |
| 1 | 📝 specced | Rule-based signal → Discord (manual entry) | [SPEC_PHASE1.md](SPEC_PHASE1.md) |
| 1.5 | 📝 specced | Sibling-project feature integration | [SPEC_PHASE1_5.md](SPEC_PHASE1_5.md) |
| 2 | ⬜ planned | LightGBM model + paper trade | — |
| 3 | ⬜ planned | Auto-execute (¥10,000 start) | — |
| 4 | ⬜ planned | Scale up after demonstrated edge | — |

## Project layout

```
hl-swing-bot/
├── pyproject.toml
├── .env.example          # template — copy to .env
├── .gitignore
├── src/hl_swing_bot/
│   ├── config.py            # pydantic-settings, loads .env
│   ├── hyperliquid_client.py # REST: metaAndAssetCtxs + candleSnapshot
│   ├── discord_client.py    # webhook + retry
│   ├── storage.py           # DuckDB schema + upserts
│   ├── collector.py         # Phase 0 main loop  ← entry point
│   └── notify.py            # CLI to test webhook
├── scripts/
│   ├── run_collector.bat    # Task Scheduler entry
│   └── run_loop.bat         # foreground continuous mode
├── config/                  # reserved for YAML configs in later phases
└── data/                    # DuckDB lives here (gitignored)
```

## Security notes

- `.env` is in `.gitignore` — never commit it
- Use a separate Hyperliquid **API wallet** for trading later. Never put your main wallet's private key in any file
- Discord webhook URLs are secrets too. If one leaks, regenerate via Discord channel settings → Integrations
