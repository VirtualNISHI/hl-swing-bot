# Phase 1.5 SPEC — Sibling-Project Feature Integration

**Goal**: Pull derived features from existing crypto-data projects into `hl-swing-bot`'s DuckDB so the Phase 2 ML model can consume them as a single tall feature table. Loose coupling: sibling projects keep running unchanged; we just read their outputs.

**When**: After Phase 1 has fired 10+ signals and we want to start measuring whether cross-project features (skew, liquidation cascades, taker imbalance) materially improve hit-rate. Ideally start writing the adapters in parallel with Phase 1 outcome accumulation.

---

## Core principle: read, don't refactor

Each sibling project produces an output (JSON / SQLite / Parquet). We write a **read-only adapter** in `hl-swing-bot/src/hl_swing_bot/adapters/` that:

1. Opens the sibling's output file
2. Translates rows to a common `features` schema (tall format)
3. Upserts into `hl-swing-bot/data/market.duckdb`

Sibling projects continue to run on their own schedule. We never reach into their code.

---

## Common feature schema (tall, append-only)

```sql
CREATE TABLE IF NOT EXISTS features (
    feature_time_ms   BIGINT NOT NULL,    -- when the feature represents (not when collected)
    coin              VARCHAR NOT NULL,   -- BTC / ETH / ...
    feature_name      VARCHAR NOT NULL,   -- canonical name, see registry below
    feature_value     DOUBLE  NOT NULL,
    source            VARCHAR NOT NULL,   -- sibling project name
    ingested_at_ms    BIGINT NOT NULL,
    PRIMARY KEY (coin, feature_time_ms, feature_name)
);

CREATE INDEX IF NOT EXISTS idx_features_name_time
    ON features (feature_name, feature_time_ms);
```

**Why tall, not wide**:
- New features need no `ALTER TABLE` (sibling projects come and go)
- Different cadences (daily / 15m / event-driven) coexist cleanly
- The Phase 2 ML feature builder pivots to wide on demand with one SQL query

---

## Feature name registry

| `feature_name` | Unit | Source project | Cadence | Notes |
|---|---|---|---|---|
| `rr_25d_d1` | vol points | riskreversal-delta | daily | 25Δ risk reversal, BTC, 30d term |
| `iv_atm_d1` | vol % | riskreversal-delta | daily | ATM IV |
| `dvol_d1` | vol % | riskreversal-delta | daily | Deribit DVOL |
| `buysell_ratio_15m` | unitless | buysell | 15m | Σbuy / Σsell across spot venues |
| `taker_buy_share_15m` | 0..1 | buysell | 15m | buy / (buy + sell), aggregated |
| `liq_long_usd_1h` | USD | liquidation | hourly | Σ long-side liq notional, last 60min |
| `liq_short_usd_1h` | USD | liquidation | hourly | Σ short-side liq notional |
| `liq_cascade_flag_1h` | 0/1 | liquidation | hourly | 1 if total > $50M threshold |
| `gex_zero_strike_weekly` | USD | option_discord/06 | weekly | Strike where gamma crosses zero |
| `cme_deribit_iv_spread_d1` | vol points | option_discord/04 | daily | CME BVX – Deribit DVOL |
| `funding_z_24` | z-score | (hl-swing-bot self) | hourly | Already computed in features.py |
| `perp_oi_chg_24h` | fraction | (hl-swing-bot self) | hourly | Already collected |

(Names use snake_case + a cadence suffix like `_d1`/`_15m`/`_1h` so the schema is self-documenting.)

---

## Adapter interface

```python
# src/hl_swing_bot/adapters/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator
from dataclasses import dataclass

@dataclass
class FeatureRow:
    feature_time_ms: int
    coin: str
    feature_name: str
    feature_value: float

class Adapter(ABC):
    source: str  # short id, e.g. "riskreversal-delta"

    @abstractmethod
    def fetch_new(self, since_ms: int) -> Iterator[FeatureRow]:
        """Yield FeatureRow objects strictly newer than ``since_ms``.
        Adapter is responsible for incremental reads."""
```

Each adapter implements `fetch_new` against the sibling's storage format. The orchestrator (`adapters/runner.py`) calls each adapter every N minutes and upserts.

---

## Concrete adapters

### `riskreversal_delta.py`

```python
# Reads C:\User\projects\riskreversal-delta\data\history.json
# Schema: { "2026-05-06": {"rr_25": -2.18, "iv_atm": 37.6, "dvol": 39.51, ...}, ... }
# Maps: rr_25 -> rr_25d_d1, iv_atm -> iv_atm_d1, dvol -> dvol_d1
# Cadence: read every 1h, but it only updates daily.
```

### `buysell.py`

```python
# Reads C:\User\projects\buysell\data\trade_cache.json
# Schema: {"sources": {"binance_spot": {"buckets": {"1778413500": {"buy_q":..,"sell_q":..}, ...}}}}
# Aggregates buckets across all sources, computes buysell_ratio and taker_buy_share
# Cadence: 15m. Bucket timestamps are epoch seconds (15min boundaries).
```

### `liquidation.py`

```python
# Reads C:\User\projects\liquidation\data\events.sqlite3 (read_only)
# Computes hourly aggregates (long_usd, short_usd, total, cascade_flag)
# Cadence: every 5min, computes the trailing 60min window
```

### `option_discord_*.py` (lazy — implement when needed)

Each task subdirectory has its own SQLite. Skip until Phase 1 outcomes suggest options features are needed.

---

## Orchestrator

```python
# src/hl_swing_bot/adapters/runner.py
def run_all_adapters() -> dict[str, int]:
    settings = load_settings()
    adapters = [
        RiskReversalDeltaAdapter(Path("C:/User/projects/riskreversal-delta/data/history.json")),
        BuySellAdapter(Path("C:/User/projects/buysell/data/trade_cache.json")),
        LiquidationAdapter(Path("C:/User/projects/liquidation/data/events.sqlite3")),
    ]
    counts = {}
    with Storage(settings.duckdb_path) as store:
        for a in adapters:
            last = store.latest_feature_time_ms(a.source)
            rows = list(a.fetch_new(since_ms=last or 0))
            store.upsert_features(rows, source=a.source)
            counts[a.source] = len(rows)
    return counts
```

Invoked from a new entry point `hl-features` (added to `pyproject.toml` `[project.scripts]`), scheduled separately from the price collector (every 15 min is fine).

---

## Storage extensions (additive)

Add to `storage.py`:

```python
SCHEMA_FEATURES = """
CREATE TABLE IF NOT EXISTS features (
    feature_time_ms   BIGINT  NOT NULL,
    coin              VARCHAR NOT NULL,
    feature_name      VARCHAR NOT NULL,
    feature_value     DOUBLE  NOT NULL,
    source            VARCHAR NOT NULL,
    ingested_at_ms    BIGINT  NOT NULL,
    PRIMARY KEY (coin, feature_time_ms, feature_name)
);
"""

def upsert_features(self, rows, *, source: str) -> int: ...
def latest_feature_time_ms(self, source: str) -> int | None: ...
def pivot_features(self, names: list[str], since_ms: int) -> "polars.DataFrame":
    """Wide view for ML feature builder; joins on (coin, feature_time_ms)."""
```

`pivot_features` is the key bridge between this Phase 1.5 store and the Phase 2 ML training pipeline.

---

## Path coupling: how to keep this honest

Adapter constructors take an explicit `Path` to the sibling's output file. **No magic discovery.** If a sibling project moves or is renamed, the adapter fails loudly. List of paths lives in `config.py` (env-var override per source):

```python
sibling_paths: dict[str, Path] = Field(
    default_factory=lambda: {
        "riskreversal-delta": Path("C:/User/projects/riskreversal-delta/data/history.json"),
        "buysell":            Path("C:/User/projects/buysell/data/trade_cache.json"),
        "liquidation":        Path("C:/User/projects/liquidation/data/events.sqlite3"),
    }
)
```

---

## Sequence to add a new sibling adapter

1. Inspect the sibling's output file — schema, cadence, timestamp format
2. Add `feature_name` entries to the registry above
3. Write `adapters/<name>.py` implementing `Adapter.fetch_new`
4. Add to the adapter list in `runner.py`
5. Add path to `Settings.sibling_paths`
6. Run `hl-features --once` and inspect `features` table

Per-adapter effort estimate: **30–90 min** (most time is in reading the sibling's data layout, not coding the adapter).

---

## Open questions

1. **What if a sibling project never persists to disk** (compute-and-notify only)? → Either modify it to dump JSON, or duplicate its compute logic inside the adapter. Decision per project; bias toward modifying the sibling lightly (`--export` flag) over duplicating logic.
2. **Timestamp alignment**: features come at daily/15m/1h cadences. The ML feature builder does *forward-fill within window* (e.g., the daily `rr_25d_d1` value at the time of a 1h bar is the most recent date ≤ that bar). Implemented in `pivot_features`.
3. **Backfill vs forward-only**: adapters only fetch new rows by default. Each adapter should also provide `fetch_all()` for one-time backfill. Use sparingly — daily files re-parse fast, but SQLite scans don't.
4. **Lookup performance**: with ~10 features × 24 bars/day × 365 days = ~88k rows/year per coin, DuckDB handles this trivially. No partitioning needed.

---

## Deliverables

- [ ] `storage.py` extended with `features` table + `upsert_features` + `latest_feature_time_ms` + `pivot_features`
- [ ] `adapters/base.py` interface
- [ ] `adapters/riskreversal_delta.py` (concrete #1)
- [ ] `adapters/buysell.py` (concrete #2)
- [ ] `adapters/liquidation.py` (concrete #3)
- [ ] `adapters/runner.py` orchestrator
- [ ] `hl-features` CLI script in pyproject.toml
- [ ] `scripts/run_features.bat` for Task Scheduler (every 15min)
- [ ] README section documenting the feature registry

Estimated effort: **6–8 hours** end-to-end, parallelizable with Phase 1 implementation.
