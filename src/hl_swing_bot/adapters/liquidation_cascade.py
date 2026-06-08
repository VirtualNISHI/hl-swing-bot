"""Adapter: Liquidation_cascade bias score -> feature store.

Source: a JSONL time series (`bias_log.jsonl`) appended by the
Liquidation_cascade project (one record per build). Each record:

    {"schema":1, "ts_utc":"2026-06-08T12:05:00+00:00", "as_of":"2026-06-08",
     "price":63500.0, "score":-8, "side":"long", "state":"監視",
     "components":{"funding":..,"oi":..,"skew":..,"smart":..},
     "available":{"funding":true,"oi":false,"skew":true,"smart":true},
     "gate":{"open":false,"trigger_px":null,"dist":null,"notional":0}, ...}

We map each record onto the hourly grid (bucket ts_utc to its hour) and emit:

  - liquidation_cascade_bias_1h     : signed bias score [-100..+100]
                                       (+ = shorts crowded / upside-squeeze / LONG fuel,
                                        - = longs crowded / downside cascade)
  - liquidation_cascade_gate_1h     : 1.0 if cascade gate open (within 2% of a dense
                                       cluster), else 0.0  -> risk veto signal
  - liquidation_cascade_oi_fresh_1h : 1.0 if the OI (C2) term was live this obs, else 0.0
                                       -> freshness flag; bias is less complete when 0

The source is read-only; the adapter never imports Liquidation_cascade code.
If multiple records fall in the same hour, the LAST (newest ts_utc) wins.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

SOURCE = "liquidation_cascade"
COIN = "BTC"
HOUR_MS = 60 * 60 * 1000

# Default local path (both projects live under C:\User\projects on the user's PC).
DEFAULT_LOCAL_PATH = Path("C:/User/projects/Liquidation_cascade/out/bias_log.jsonl")
# Raw URL fallback once the JSONL is committed to the public repo (cloud runs).
DEFAULT_RAW_URL = (
    "https://raw.githubusercontent.com/VirtualNISHI/"
    "liquidation-cascade-monitor/main/out/bias_log.jsonl"
)


def _parse_ts_ms(ts_utc: str) -> int | None:
    """ISO-8601 -> epoch ms. Tolerates trailing 'Z'."""
    from datetime import datetime
    try:
        s = ts_utc.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except Exception:
        return None


def _bucket_hour_ms(ts_ms: int) -> int:
    return ts_ms - (ts_ms % HOUR_MS)


def _iter_records(text: str) -> Iterable[dict]:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            log.warning("liquidation_cascade: skipping malformed JSONL line")


def read_source(*, local_path: Path | None = None, url: str | None = None) -> str:
    """Return the raw JSONL text. Prefer a local file if it exists, else fetch URL.

    Returns "" if the remote file does not exist yet (HTTP 404) — the upstream
    JSONL is only created on the first slot-gate crawl, so an empty result is a
    normal "no data yet" state, not an error.
    """
    p = local_path or DEFAULT_LOCAL_PATH
    if p.exists():
        return p.read_text(encoding="utf-8")
    src = url or DEFAULT_RAW_URL
    log.info("liquidation_cascade: local file absent, fetching %s", src)
    try:
        with urllib.request.urlopen(src, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.info("liquidation_cascade: remote JSONL not present yet (404) — no data")
            return ""
        raise


def build_feature_rows(text: str, *, since_ms: int = 0) -> list[tuple]:
    """Parse JSONL into feature rows newer than ``since_ms``.

    Returns list of (coin, feature_time_ms, feature_name, feature_value).
    Hourly-deduplicated: the newest record per hour wins for each feature.
    """
    # hour_ms -> (ts_ms, {feature_name: value})
    by_hour: dict[int, tuple[int, dict[str, float]]] = {}
    for rec in _iter_records(text):
        ts_ms = _parse_ts_ms(rec.get("ts_utc", ""))
        if ts_ms is None:
            continue
        hour_ms = _bucket_hour_ms(ts_ms)
        if hour_ms <= since_ms:
            continue
        score = rec.get("score")
        if score is None:
            continue
        gate = rec.get("gate") or {}
        avail = rec.get("available") or {}
        feats = {
            "liquidation_cascade_bias_1h": float(score),
            "liquidation_cascade_gate_1h": 1.0 if gate.get("open") else 0.0,
            "liquidation_cascade_oi_fresh_1h": 1.0 if avail.get("oi") else 0.0,
        }
        prev = by_hour.get(hour_ms)
        if prev is None or ts_ms >= prev[0]:
            by_hour[hour_ms] = (ts_ms, feats)

    rows: list[tuple] = []
    for hour_ms, (_ts, feats) in sorted(by_hour.items()):
        for name, val in feats.items():
            rows.append((COIN, hour_ms, name, val))
    return rows


def ingest(storage, *, local_path: Path | None = None, url: str | None = None,
           ingested_at_ms: int) -> dict:
    """Forward-only ingest into the feature store. Returns stats."""
    since_ms = storage.latest_feature_time_ms(SOURCE) or 0
    text = read_source(local_path=local_path, url=url)
    rows = build_feature_rows(text, since_ms=since_ms)
    n = storage.upsert_features(rows, source=SOURCE, ingested_at_ms=ingested_at_ms)
    return {
        "source": SOURCE,
        "since_ms": since_ms,
        "rows_upserted": n,
        "hours_added": n // 3 if n else 0,  # 3 features per hour
    }
