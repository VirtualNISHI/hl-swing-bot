"""DuckDB storage for candles + funding/OI snapshots.

Schema is intentionally tall (one row per bar per coin) so we can add coins
without altering schema. Primary keys prevent duplicate inserts when polls
overlap.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import duckdb

from .hyperliquid_client import Candle, HyperliquidPerp

log = logging.getLogger(__name__)


SCHEMA_CANDLES = """
CREATE TABLE IF NOT EXISTS candles (
    coin           VARCHAR NOT NULL,
    interval       VARCHAR NOT NULL,
    open_time_ms   BIGINT  NOT NULL,
    close_time_ms  BIGINT  NOT NULL,
    open           DOUBLE  NOT NULL,
    high           DOUBLE  NOT NULL,
    low            DOUBLE  NOT NULL,
    close          DOUBLE  NOT NULL,
    volume         DOUBLE  NOT NULL,
    trades         INTEGER NOT NULL,
    PRIMARY KEY (coin, interval, open_time_ms)
);
"""

SCHEMA_FUNDING = """
CREATE TABLE IF NOT EXISTS perp_snapshots (
    coin                    VARCHAR NOT NULL,
    snapshot_time_ms        BIGINT  NOT NULL,
    mark_price_usd          DOUBLE  NOT NULL,
    prev_day_price_usd      DOUBLE  NOT NULL,
    day_volume_usd          DOUBLE  NOT NULL,
    open_interest_coin      DOUBLE  NOT NULL,
    open_interest_usd       DOUBLE  NOT NULL,
    funding_rate_hourly     DOUBLE  NOT NULL,
    PRIMARY KEY (coin, snapshot_time_ms)
);
"""


class Storage:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn = duckdb.connect(str(db_path))
        self._conn.execute(SCHEMA_CANDLES)
        self._conn.execute(SCHEMA_FUNDING)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert_candles(self, candles: Iterable[Candle]) -> int:
        rows = [
            (
                c.coin,
                c.interval,
                c.open_time_ms,
                c.close_time_ms,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                c.trades,
            )
            for c in candles
        ]
        if not rows:
            return 0
        # INSERT OR IGNORE preserves the earliest row; replace it if the close
        # has changed (the current/forming bar updates on every poll).
        self._conn.executemany(
            """
            INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (coin, interval, open_time_ms) DO UPDATE SET
                close_time_ms = excluded.close_time_ms,
                open  = excluded.open,
                high  = excluded.high,
                low   = excluded.low,
                close = excluded.close,
                volume= excluded.volume,
                trades= excluded.trades
            """,
            rows,
        )
        return len(rows)

    def insert_perp_snapshot(self, perp: HyperliquidPerp, *, snapshot_time_ms: int) -> None:
        self._conn.execute(
            """
            INSERT INTO perp_snapshots VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (coin, snapshot_time_ms) DO NOTHING
            """,
            (
                perp.coin,
                snapshot_time_ms,
                perp.mark_price_usd,
                perp.prev_day_price_usd,
                perp.day_volume_usd,
                perp.open_interest_coin,
                perp.open_interest_usd,
                perp.funding_rate_hourly,
            ),
        )

    def candle_count(self, coin: str, interval: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM candles WHERE coin = ? AND interval = ?",
            (coin, interval),
        ).fetchone()
        return int(row[0]) if row else 0

    def latest_candle_time_ms(self, coin: str, interval: str) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(open_time_ms) FROM candles WHERE coin = ? AND interval = ?",
            (coin, interval),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
