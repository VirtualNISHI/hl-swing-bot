"""Phase 1 strategy runner.

Every run:
1. Open outcomes for any signals against latest mark price.
2. Try to fire a new signal from the most recent CLOSED 1h bar.
3. Publish to Discord.

Designed to be invoked hourly (5 min past the hour) by GitHub Actions but
safe to run more often — feature evaluation is on the closed bar, so re-runs
within an hour see the same inputs and skip due to cooldown / no-fire.
"""
from __future__ import annotations

import argparse
import logging
import time

from .config import load_settings
from .discord_client import DiscordClient
from .hyperliquid_client import open_client
from .publisher import publish_outcome, publish_signal
from .signal import evaluate_and_emit, update_outcomes
from .storage import Storage

log = logging.getLogger(__name__)


def run_once(*, dry_run: bool = False) -> dict:
    settings = load_settings()
    now_ms = int(time.time() * 1000)
    stats: dict = {"outcomes": 0, "signals_fired": [], "open_after": 0}

    with Storage(settings.duckdb_path) as store, \
         DiscordClient(settings.discord_webhook_url, dry_run=dry_run) as discord, \
         open_client() as hl:

        # One metaAndAssetCtxs call covers every coin's mark price.
        perps = {p.coin: p for p in hl.fetch_all_perps()}

        for coin in settings.hl_coins:
            perp = perps.get(coin)
            if perp is None:
                log.warning("no perp data for %s; skipping", coin)
                continue
            store.insert_perp_snapshot(perp, snapshot_time_ms=now_ms)
            mark_price = perp.mark_price_usd
            stats[f"mark_{coin}"] = mark_price

            # 1. Outcomes for open signals on this coin.
            notifications = update_outcomes(
                store, coin, mark_price=mark_price, now_ms=now_ms, dry_run=dry_run,
            )
            for notif in notifications:
                publish_outcome(discord, notif)
            stats["outcomes"] += len(notifications)

            # 2. New signal? (cluster cap inside evaluate_and_emit is global,
            #    so coin order matters only when both fire simultaneously —
            #    BTC first by list order.)
            new_sig = evaluate_and_emit(store, coin, now_ms=now_ms, dry_run=dry_run)
            if new_sig is not None:
                publish_signal(discord, new_sig)
                stats["signals_fired"].append(
                    {"coin": coin, "signal_id": new_sig["signal_id"],
                     "direction": new_sig["direction"],
                     "score": round(new_sig["composite_score"], 2)}
                )

        stats["open_after"] = store.open_signal_count_all()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="hl-swing-bot Phase 1 strategy runner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute, log, and would-publish without writing or sending")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stats = run_once(dry_run=args.dry_run)
    print(stats)


if __name__ == "__main__":
    main()
