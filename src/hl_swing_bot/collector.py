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
    stats: dict[str, int] = {"candles_upserted": 0, "snapshots_inserted": 0,
                             "funding_upserted": 0}

    with open_client() as hl, Storage(settings.duckdb_path) as store:
        now_ms = int(time.time() * 1000)
        # One metaAndAssetCtxs call serves every coin's snapshot.
        perps = {p.coin: p for p in hl.fetch_all_perps()}

        for coin in settings.hl_coins:
            latest_ms = store.latest_candle_time_ms(coin, settings.hl_candle_interval)
            if latest_ms is None:
                start_ms = now_ms - settings.hl_lookback_minutes * 60_000
            else:
                start_ms = latest_ms - 10 * 60_000  # 10-min overlap for re-forming bar

            candles = hl.fetch_candles(
                coin,
                interval=settings.hl_candle_interval,
                start_ms=start_ms,
                end_ms=now_ms,
            )
            stats["candles_upserted"] += store.upsert_candles(candles)

            # Settled hourly funding: backfill 200h on first run (funding_z_168
            # needs 169), then append incrementally from the last stored hour.
            last_funding = store.latest_funding_hour_ms(coin)
            if last_funding is None or store.funding_rate_count(coin) < 169:
                funding_start = now_ms - 200 * 3_600_000
            else:
                funding_start = last_funding + 1
            if now_ms - funding_start >= 3_600_000:
                frows = hl.fetch_funding_history(
                    coin, start_ms=funding_start, end_ms=now_ms
                )
                stats["funding_upserted"] += store.upsert_funding_rates(coin, frows)

            perp = perps.get(coin)
            if perp is not None:
                store.insert_perp_snapshot(perp, snapshot_time_ms=now_ms)
                stats["snapshots_inserted"] += 1

            stats[f"candles_{coin}"] = store.candle_count(
                coin, settings.hl_candle_interval
            )

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
