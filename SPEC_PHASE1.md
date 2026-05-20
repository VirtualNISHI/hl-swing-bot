# Phase 1 SPEC — Rule-Based Swing Signal → Discord (no auto-execute)

**Goal**: Generate BTC swing-trade signals (LONG/SHORT) and publish to Discord. Trader executes manually. Phase 1 is the alpha-validation stage — we measure signal hit-rate and R:R realized vs expected over 30+ live signals before adding any ML or auto-execution.

**Non-goals**: No order placement, no leverage management, no portfolio rebalancing. Anything resembling "auto-trading" belongs in Phase 3.

---

## Strategy in one paragraph

When BTC closes a 1h bar with a **statistically significant move in the direction of the 4h trend**, accompanied by **above-average volume** and **non-extreme funding**, emit a directional signal with a 1.5×ATR stop and 2.5×ATR target. Skip if any guard (cooldown, conflicting trend, exotic funding) trips. The composite score weights are ported from `Btc_alert_bot/detector.py` and re-tuned for the 1h timeframe.

---

## Timeframes

| Purpose | Bar | Rationale |
|---|---|---|
| Primary signal | **1h** | Enough noise filter to avoid scalping costs, enough samples for a 1-week window |
| Trend filter | **4h SMA(50)** | Standard swing-trend reference |
| Volatility scale | **ATR(14) on 1h** | Wilder, ported from Btc_alert_bot |
| Funding context | **HL funding (1h)** | Already collected in `perp_snapshots` |

Holding period: **4h–3 days**. Target signal frequency: **2–5 per week**.

---

## Features (computed each closed 1h bar)

```
ret_1h        = (close - close_lag1)  / close_lag1
ret_4h        = (close - close_lag4)  / close_lag4
ret_24h       = (close - close_lag24) / close_lag24
atr_1h        = wilder_atr(high, low, close, period=14)
atr_pct       = atr_1h / close
move_per_atr  = abs(ret_1h) / atr_pct                       # Btc_alert_bot pattern
robust_z_168  = (close - median_168) / (1.4826 * MAD_168)   # 1-week robust z
vol_z_168     = (volume - mean_168) / std_168
trend_4h      = sign(close - SMA_50(close_4h))              # +1/-1/0
funding_z_24  = z(funding_rate_hourly, 24)                   # over last 24 fundings
oi_chg_24h    = (oi_now - oi_lag24h) / oi_lag24h
```

All computed by `features.py` (port from Btc_alert_bot, adapt to DuckDB-as-source).

---

## Composite score

```
score = 0.30 * move_per_atr          # impulse strength
      + 0.25 * abs(robust_z_168)     # statistical anomaly
      + 0.20 * vol_z_168             # participation
      + 0.15 * abs(ret_4h) / atr_pct # multi-bar follow-through
      + 0.10 * (1 - min(abs(funding_z_24), 3) / 3)  # reward non-extreme funding
```

Weight rationale: same shape as Btc_alert_bot but `oi_drop` swapped for the `funding_z` mean-reversion bonus (HL funding is mean-reverting on 8h cycles; trading *with* extreme funding has historically been negative-expectancy).

---

## Signal rules

A signal fires when **all** are true:

1. `score >= 3.0`
2. `move_per_atr >= 1.0` (move at least 1 ATR in the bar)
3. `vol_z_168 >= 1.0`
4. `sign(ret_1h) == trend_4h` (no counter-trend entries in Phase 1)
5. `abs(funding_z_24) <= 2.5` (no entries against extreme funding)
6. **No cooldown active** (see below)

`direction = "LONG" if ret_1h > 0 else "SHORT"`

### Stop / target

```
stop_distance   = 1.5 * atr_1h
target_distance = 2.5 * atr_1h           # R:R ≈ 1:1.67
entry_price     = close (signal bar)
stop_price      = entry ± stop_distance
target_price    = entry ± target_distance
expires_at      = signal_time + 72h      # time stop
```

### Cooldown

- Same direction after a fired signal: **4 hours**
- Opposite direction (reversal): **1 hour**
- Implemented as a ring-buffer state in `data/state.json` (Btc_alert_bot pattern)

---

## Output

### DuckDB `signals` table

```sql
CREATE TABLE signals (
    signal_id          BIGINT PRIMARY KEY,
    generated_at_ms    BIGINT NOT NULL,
    coin               VARCHAR NOT NULL,
    direction          VARCHAR NOT NULL,   -- LONG / SHORT
    entry_price        DOUBLE NOT NULL,
    stop_price         DOUBLE NOT NULL,
    target_price       DOUBLE NOT NULL,
    expires_at_ms      BIGINT NOT NULL,
    composite_score    DOUBLE NOT NULL,
    features_json      VARCHAR NOT NULL,   -- snapshot of all input features
    status             VARCHAR NOT NULL,   -- NEW / HIT_TP / HIT_SL / EXPIRED / CANCELLED
    closed_at_ms       BIGINT,
    realized_return    DOUBLE
);
```

### Discord embed

```
🟢 LONG BTC  @  77,500  (HL perp)
SL  76,830   (-0.87%, 1.5 ATR)
TP  78,675   (+1.52%, 2.5 ATR)
R:R 1:1.67   ·  expires in 72h

score 3.24 · move/ATR 1.42 · vol_z 1.81
trend_4h ↑  ·  funding_z -0.4 (carry OK)

signal #142 · 2026-05-21 09:00 JST
```

Color: green for LONG, red for SHORT. Chart attachment with `chart.py` (port from Btc_alert_bot) showing the last 48 bars + entry/SL/TP horizontal lines.

---

## Outcome tracking (the validation point)

A background job runs every 5 minutes:

1. For each `signals.status = 'NEW'`:
   - Fetch latest HL mark price
   - If touched `target_price` → status `HIT_TP`, post Discord ✅ "TP hit, +X%"
   - If touched `stop_price` → status `HIT_SL`, post Discord ❌ "SL hit, -Y%"
   - If `now > expires_at_ms` → status `EXPIRED`, close at mark
2. Update `realized_return`

This is what gives us the dataset to evaluate the strategy. **Phase 1 success criterion**: over 30+ signals, expectancy > 0 after 5bps slippage assumption and Hyperliquid fees (taker 0.045%).

---

## Module layout

```
src/hl_swing_bot/
├── features.py       NEW  — port Btc_alert_bot indicators, DuckDB-driven
├── signal.py         NEW  — composite score, entry rules
├── cooldown.py       NEW  — state machine, ports Btc_alert_bot
├── outcome.py        NEW  — fills in TP/SL/expiry status
├── chart.py          NEW  — port Btc_alert_bot mplfinance renderer
├── publisher.py      NEW  — Discord embed formatter for signals
└── strategy_runner.py NEW — top-level orchestrator, runs every 5min
```

`collector.py` from Phase 0 keeps running unchanged. The new `strategy_runner.py` reads from the same DuckDB.

---

## What we are explicitly NOT doing in Phase 1

| Decision | Why deferred |
|---|---|
| No ML model | Need labeled data first; ground truth comes from outcome tracking |
| No counter-trend entries | Adds complexity; mean-reversion alphas are separate research |
| No multiple coins | BTC only; widening universe is a Phase 2 decision |
| No position sizing | No execution → moot. ¥10,000-per-trade rule belongs in Phase 3 |
| No ensemble signals | One simple rule that we can fully understand is the baseline |
| No sibling-project features | They come in Phase 1.5 (see SPEC_PHASE1_5.md) once schema lands |

---

## Open questions to answer before implementation

1. **Time-of-day filter?** HL funding rolls every 1h, but Asia/EU/US sessions have distinct volatility regimes. Maybe restrict signals to 08:00–22:00 UTC.
2. **Score 3.0 threshold validation**: Btc_alert_bot uses 3.0 for 5m spike detection. For 1h swing, the right threshold needs to be backtested against existing Phase 0 data (which we'll have ~1 month worth of by the time we start Phase 1).
3. **Stop loss based on swing low/high instead of ATR?** ATR is mechanical; swing structures are smarter. Keep ATR for v1, revisit after 30 signals.
4. **Should we suppress signals during high-impact macro events?** ForexFactory check exists in Btc_alert_bot/analyzers.py. Easy to port.
