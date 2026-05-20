# Deployment — GitHub Actions cron (every 5 minutes)

This matches the pattern used by `Btc_alert_bot` and `hyperliquid-tracker`. The GitHub Actions runner becomes the canonical source of truth; `data/market.duckdb` is committed back to the repo each run.

## Why GitHub Actions (not local Task Scheduler / AWS)

| Option | Cost | Reliability | Setup time | Fit for Phase 0 |
|---|---|---|---|---|
| **GitHub Actions cron** (this) | free | high (GH SLA) | ~10 min | ✅ |
| Windows Task Scheduler (local) | free | depends on PC uptime | many | ❌ (PC often off) |
| AWS Lightsail VPS + systemd | $3.50/mo | very high | ~1 hr | overkill |
| AWS Lambda + EventBridge | <$1/mo | very high | ~2 hr | needs S3 for DB |

For 5-min cadence with a single small DuckDB file, **GitHub Actions wins** on simplicity. Migrate to a VPS only if you outgrow GH Actions (e.g., move to WebSocket realtime in Phase 2+).

## Prerequisites

- A GitHub account
- `git` installed locally
- The Discord webhook URL (currently in `C:\User\projects\Discord.txt`)
- **You should regenerate the webhook before pushing** — its current value has appeared in conversation logs

## Step-by-step

### 1. Regenerate the Discord webhook

In Discord: channel settings → Integrations → Webhooks → select the existing webhook → **Reset URL**. Copy the new URL.

### 2. Initialize git locally

```powershell
cd C:\User\projects\hl-swing-bot
git init -b main
git add .
git status   # double-check .env is NOT in the list (it must be ignored)
git commit -m "feat: Phase 0 data collector + GitHub Actions workflow"
```

### 3. Create a **private** GitHub repo

Via web UI: https://github.com/new → name: `hl-swing-bot` → **Private** → Create.

Or via gh CLI:

```powershell
gh repo create hl-swing-bot --private --source=. --remote=origin --push
```

(If you use the gh CLI form, skip step 4.)

### 4. Push (if you didn't use gh CLI)

```powershell
git remote add origin https://github.com/<your-username>/hl-swing-bot.git
git push -u origin main
```

### 5. Add the Discord webhook as a repo secret

Via web UI: repo → Settings → Secrets and variables → Actions → **New repository secret**

- Name: `DISCORD_WEBHOOK_URL`
- Value: paste the **new** webhook URL from step 1

Or via gh CLI:

```powershell
gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/..."
```

### 6. Enable the workflow

GitHub disables scheduled workflows by default on new repos (it asks first). Two ways to enable:

- Web UI: repo → Actions tab → "I understand my workflows, go ahead and enable them"
- Or manually trigger once: Actions → "collect" → "Run workflow" → main → Run

After that, the `*/5 * * * *` cron takes over.

### 7. Verify it's running

```powershell
# Watch recent runs
gh run list --workflow=collect.yml --limit 5

# Tail the latest run
gh run watch
```

You should see commits like `chore: collector data update [skip ci]` appearing every 5 minutes.

## Pull data locally to inspect

The GH Actions runner is the source of truth. Whenever you want to look at the data:

```powershell
cd C:\User\projects\hl-swing-bot
git pull --rebase
# now data/market.duckdb has the latest
.venv\Scripts\python -c "import duckdb; con=duckdb.connect('data/market.duckdb', read_only=True); con.sql('SELECT COUNT(*) FROM candles').show()"
```

⚠️ **Don't run the local collector after GH Actions is live.** It will write to your local DuckDB which diverges from the canonical one. If you need local runs (testing), do them on a copy: `cp data/market.duckdb data/dev.duckdb`.

## Cost & limits

- GitHub Actions free tier on private repos: **2,000 min/month**. At ~30s per run × 12 runs/hour × 24h × 30d = ~4,300 min. We exceed the free tier.
- **Make the repo public** to get unlimited Actions minutes (the code has no secrets — `.env` is gitignored; webhook is a GH secret). Most of the user's other projects are likely public for the same reason.
- Alternatively, run every 15 min instead of 5 to stay under 2,000 min: edit cron to `*/15 * * * *`. Still gives ~96 candle observations per day.

## Repo growth

DuckDB binary commit each run grows the repo by roughly:

- ~50 KB/day of new candle rows (compressed)
- BUT each commit is a binary diff and stores the full ~current file ⇒ in practice repo grows ~5 MB/month
- 1 year ≈ ~60 MB. Acceptable. If repo size becomes a concern, periodically squash history or migrate to a hosted DB (Turso free tier, Neon, etc.).

## Troubleshooting

### Workflow runs but commits show no DB change

Likely cause: gap-aware collector got 0 new bars because the previous run already pulled the most recent closed bar. The current/forming bar still gets upserted but its values may be identical to the prior poll. This is normal — only ~1 out of 5 runs adds a meaningful new bar at 5-min cadence on 1m candles. Lower the cadence to `*/1 * * * *` (1 min) if you want every bar's close exactly.

### "Updates were rejected because the remote contains work"

Two runs raced. The workflow's `git push || (git pull --rebase --autostash && git push)` retry should handle it. If you see this repeatedly, set the cron to `*/10 * * * *` so consecutive runs never overlap.

### Discord posts nothing

By design — Phase 0 only notifies on **3 consecutive failures** to avoid noise. Test the webhook by triggering manually with `workflow_dispatch` and watching Actions logs.

### How to remove

```powershell
gh workflow disable collect.yml      # stop the cron
# or to fully tear down:
gh repo delete hl-swing-bot --confirm
```

## Migrating to a VPS later

When Phase 2 (WebSocket realtime) needs sub-minute latency, copy `hyperliquid-tracker/deploy/` systemd timer pattern. AWS Lightsail or Hetzner CX11 ($4-5/mo) are typical targets. The DuckDB file can live in `/srv/hl-swing-bot/data/` and be backed up to S3 daily.
