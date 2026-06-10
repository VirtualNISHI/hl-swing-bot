"""Forward-only feature ingestion runner.

Runs each enabled sibling adapter and upserts new feature rows into the DuckDB
feature store. Scheduled separately from the price collector (e.g. hourly).
"""
from __future__ import annotations

import argparse
import logging
import time

from ..config import load_settings
from ..storage import Storage
from . import coinalyze, liquidation_cascade

log = logging.getLogger(__name__)

# Registry of adapters. Each is a module exposing ingest(storage, *, ingested_at_ms).
ADAPTERS = {
    "liquidation_cascade": liquidation_cascade,
    "coinalyze": coinalyze,
}


def run_all(*, ingested_at_ms: int | None = None) -> dict:
    settings = load_settings()
    ts = ingested_at_ms or int(time.time() * 1000)
    results: dict[str, dict] = {}
    with Storage(settings.duckdb_path) as store:
        for name, mod in ADAPTERS.items():
            try:
                results[name] = mod.ingest(store, ingested_at_ms=ts)
            except Exception as e:
                log.exception("adapter %s failed", name)
                results[name] = {"source": name, "error": str(e)}
        results["_feature_total"] = store.feature_count()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="hl-swing-bot feature ingestion")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print(run_all())


if __name__ == "__main__":
    main()
