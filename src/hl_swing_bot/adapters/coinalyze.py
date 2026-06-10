"""Adapter: Coinalyze 1h liquidations + open interest -> feature store.

TIME-CRITICAL collector: Coinalyze keeps only ~65 days of 1h history upstream,
so every week we don't poll is a week of flow history lost forever. This
adapter backfills whatever the API still has, then appends incrementally.

Features emitted (coin = BTC / ETH, aggregated across exchanges, USD):
  - coinalyze_long_liq_1h   : long-side liquidation notional in that hour
  - coinalyze_short_liq_1h  : short-side liquidation notional in that hour
  - coinalyze_oi_usd_1h     : open interest (close of hour, USD)

PRE-REGISTERED decision tests (BACKTEST_NOTES 2026-06-10) — do NOT gate on
these features before they pass:
  - oi_chg_24h promoted to entry gate iff Spearman(oi_chg_24h, realized) >= +0.2
    with the same sign in both halves of the collected span.
  - long_liq_6h_z > 2 adopted as VETO iff rho <= -0.25 in both halves after
    >= 50 overlapping signals (exploratory rho was NEGATIVE: cascade spike may
    mean capitulation already done).

Auth: COINALYZE_API_KEY env var (cloud: GitHub secret; local: falls back to the
sibling project's .env at C:\\User\\projects\\Perp-oi-chart\\.env).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

SOURCE = "coinalyze"
BASE = "https://api.coinalyze.net/v1"
# Aggregated-across-exchanges perp symbols.
SYMBOLS = {"BTC": "BTCUSDT_PERP.A", "ETH": "ETHUSDT_PERP.A"}
HOUR_MS = 3_600_000
MAX_BACKFILL_DAYS = 70  # upstream keeps ~65d of 1h history


def _key() -> str:
    k = os.environ.get("COINALYZE_API_KEY", "").strip()
    if k:
        return k
    sibling = Path("C:/User/projects/Perp-oi-chart/.env")
    if sibling.exists():
        for line in sibling.read_text(encoding="utf-8").splitlines():
            if line.startswith("COINALYZE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("COINALYZE_API_KEY not set (env or Perp-oi-chart/.env)")


def _get(client: httpx.Client, path: str, params: dict) -> list:
    for attempt in range(3):
        r = client.get(f"{BASE}{path}", params=params, headers={"api_key": _key()})
        if r.status_code == 429:
            wait = max(float(r.headers.get("Retry-After", "0") or 0), 5.0 * (attempt + 1))
            log.info("coinalyze 429, waiting %.0fs", wait)
            time.sleep(wait + 0.5)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"coinalyze GET {path}: rate-limited after retries")


def ingest(storage, *, ingested_at_ms: int) -> dict:
    """Fetch 1h liquidation + OI history for each coin since the last stored
    feature hour (or the upstream retention limit), upsert into features."""
    now_s = ingested_at_ms // 1000
    since_floor_s = now_s - MAX_BACKFILL_DAYS * 86_400
    last_ms = storage.latest_feature_time_ms(SOURCE)
    since_s = max(since_floor_s, (last_ms // 1000) + 1) if last_ms else since_floor_s

    rows: list[tuple] = []
    with httpx.Client(timeout=30) as client:
        for coin, symbol in SYMBOLS.items():
            liq = _get(client, "/liquidation-history", {
                "symbols": symbol, "interval": "1hour",
                "from": since_s, "to": now_s, "convert_to_usd": "true",
            })
            for series in liq or []:
                for h in series.get("history", []):
                    t_ms = int(h["t"]) * 1000
                    rows.append((coin, t_ms, "coinalyze_long_liq_1h", float(h.get("l", 0.0))))
                    rows.append((coin, t_ms, "coinalyze_short_liq_1h", float(h.get("s", 0.0))))

            oi = _get(client, "/open-interest-history", {
                "symbols": symbol, "interval": "1hour",
                "from": since_s, "to": now_s, "convert_to_usd": "true",
            })
            for series in oi or []:
                for h in series.get("history", []):
                    t_ms = int(h["t"]) * 1000
                    rows.append((coin, t_ms, "coinalyze_oi_usd_1h", float(h.get("c", 0.0))))

    n = storage.upsert_features(rows, source=SOURCE, ingested_at_ms=ingested_at_ms)
    return {"source": SOURCE, "since_s": since_s, "rows_upserted": n}
