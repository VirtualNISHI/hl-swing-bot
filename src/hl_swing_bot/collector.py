"""Phase 0 collector: pull candles + funding/OI snapshot, store to DuckDB.

Intended to be invoked every 1–5 minutes (Task Scheduler / cron). Each run
fetches the last ``hl_lookback_minutes`` of candles so overlaps are tolerated.
"""
from __future__ import annotations

import argparse
import logging
import time

from .config import load_settings
from .discord_client import DiscordClient
from .hyperliquid_client import open_client
from .storage import Storage

log = logging.getLogger(__name__)


def collect_once() -> dict[str, int]:
    """One poll cycle. Returns small stats dict.

    Gap-aware: if the DB has prior candles, fetch from the most recent stored
    bar minus a 10-minute overlap, so PC sleeps or scheduler skips don't leave
    holes (Hyperliquid candleSnapshot caps ~5000 bars per call ≈ 3.5 days at 1m).
    """
    settings = load_settings()
    stats: dict[str, int] = {"candles_upserted": 0, "snapshots_inserted": 0}

    with open_client() as hl, Storage(settings.duckdb_path) as store:
        latest_ms = store.latest_candle_time_ms(
            settings.hl_coin, settings.hl_candle_interval
        )
        now_ms = int(time.time() * 1000)
        if latest_ms is None:
            start_ms = now_ms - settings.hl_lookback_minutes * 60_000
        else:
            start_ms = latest_ms - 10 * 60_000  # 10-min overlap for re-forming bar

        candles = hl.fetch_candles(
            settings.hl_coin,
            interval=settings.hl_candle_interval,
            start_ms=start_ms,
            end_ms=now_ms,
        )
        stats["candles_upserted"] = store.upsert_candles(candles)
        stats["fetch_window_minutes"] = (now_ms - start_ms) // 60_000

        perp = hl.fetch_perp(settings.hl_coin)
        if perp is not None:
            store.insert_perp_snapshot(perp, snapshot_time_ms=int(time.time() * 1000))
            stats["snapshots_inserted"] = 1

        stats["total_candles_in_db"] = store.candle_count(
            settings.hl_coin, settings.hl_candle_interval
        )
        latest = store.latest_candle_time_ms(settings.hl_coin, settings.hl_candle_interval)
        if latest is not None:
            stats["latest_candle_time_ms"] = latest

    return stats


def loop(interval_seconds: int) -> None:
    """Run ``collect_once`` forever, alerting Discord on persistent failures."""
    settings = load_settings()
    notifier = DiscordClient(settings.discord_webhook_url)
    consecutive_failures = 0
    log.info("collector loop started (every %ds)", interval_seconds)
    try:
        while True:
            start = time.monotonic()
            try:
                stats = collect_once()
                log.info("collected: %s", stats)
                if consecutive_failures >= 3:
                    notifier.send(content=f"✅ collector recovered: {stats}")
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                log.exception("collect_once failed (consecutive=%d)", consecutive_failures)
                if consecutive_failures == 3:
                    try:
                        notifier.send(
                            content=f"⚠️ hl-swing-bot collector: 3 consecutive failures."
                        )
                    except Exception:
                        log.exception("failed to send Discord alert")
            elapsed = time.monotonic() - start
            sleep_for = max(1.0, interval_seconds - elapsed)
            time.sleep(sleep_for)
    finally:
        notifier.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperliquid Phase 0 data collector")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll and exit (for cron/Task Scheduler)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between polls when running in loop mode (default: 60)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # httpx/httpcore log full URLs at INFO; raise to WARNING so the Discord
    # webhook URL never lands in stdout, log files, or process output.
    for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.once:
        stats = collect_once()
        print(stats)
    else:
        loop(args.interval)


if __name__ == "__main__":
    main()
