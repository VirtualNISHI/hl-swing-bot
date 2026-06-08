# Backtest Notes — 2026-06-08

First real backtest, run on 455 hourly bars (2026-05-20 → 06-08, 19 days).

## Headline numbers (baseline: score≥3.0, move/ATR≥1.0, vol_z≥1.0)

| metric | value |
|---|---|
| signals | 6 |
| signals/week | 2.55 (in SPEC target band 2–5) |
| TP / SL / expired | 4 / 2 / 0 |
| hit rate | 67% |
| expectancy (post-5bps slippage) | +0.76% / trade |
| median | +1.48% |
| best / worst | +2.58% / −1.60% |

**Taken at face value this looks great. It is not. Read on.**

## ⚠️ The result is one regime, not a validation

All 6 signals fired in a **3-day window: June 1–3**, during the early phase of a
BTC waterfall (73k → 64k). The other 16 of 19 days produced **zero signals**.

```
06-01 14:00  SHORT 71,700 → TP  +1.46%
06-02 13:00  SHORT 68,975 → TP  +1.69%
06-02 23:00  SHORT 66,345 → SL  −1.48%
06-03 04:00  SHORT 65,812 → SL  −1.50%
06-03 16:00  SHORT 66,055 → TP  +2.30%
06-03 23:00  SHORT 64,884 → TP  +2.68%
```

- **0 LONG signals, ever.** The entire dataset is a downtrend (77k → 63k, −18%).
  The long side of the strategy is completely **untested**.
- The positive expectancy is conditional on catching the onset of **one** crash.
  This is n=1 regime, not n=6 independent trades.

## Why signals stopped after June 3 (even though 06-04→06-07 crashed harder)

ATR expanded through the crash, and `move/ATR` collapsed as a result:

| day | atr_pct | move/ATR (sampled) |
|---|---|---|
| 06-01 | 0.37% | ~0.8 → fires |
| 06-03 | 0.98% | ~0.25 |
| 06-06 | 1.70% | ~0.21 → silent |

**Structural finding: this strategy is a volatility-expansion-ONSET detector, not a
trend rider.** It fires when vol starts expanding (while ATR is still catching up),
then self-silences once high vol becomes the 168-bar norm. Because stops/targets
scale with ATR (1.5×/2.5×), late entries would carry huge stops anyway — so the
silence is arguably correct behavior, but it means the bot will be quiet for long
stretches and only speak at regime changes.

## The `vol_z` gate is effectively inert (for now)

Sweeping vol_z ∈ {0.5, 1.0} changes **nothing** across every other parameter combo.
In the only regime that fired (a high-vol crash), volume was always elevated, so the
gate never bound. It is not dead code — it would matter in calmer regimes — but it
currently provides zero discrimination. Do not tune it on this data.

## Parameter sweep — the plateau is robust

| score | move | n | hit% | exp% |
|---|---|---|---|---|
| 2.0 | 1.0 | 13 | 54% | +0.32 |
| 2.5 | 1.0 | 9 | 67% | +0.77 |
| 3.0 | 1.0 | 6 | 67% | +0.76 |
| 3.5 | 1.0 | 6 | 67% | +0.80 |

score 2.5–3.5 is a stable plateau (not a knife-edge optimum) — good. score 2.0 clearly
degrades. **Keep score≥3.0.** But note all of this is measured inside the same crash.

## Conclusions

1. **The strategy is unfalsified, not validated.** It behaved sensibly in one downtrend.
   We have no evidence about uptrends, chop, or the long side.
2. **Do not tune parameters on this data.** 6 trades in one regime will overfit instantly.
   The score≥3.0 / move≥1.0 defaults are fine; leave them.
3. **The user's decision to postpone live trading is correct.** Launching now would be
   trading a strategy validated on exactly one crash.

## Next steps (priority order)

- [ ] **Keep collecting.** We need at least one sustained uptrend in the dataset to get
      any LONG signals and confirm the trend filter works symmetrically.
- [ ] **Add regime-discriminating features** (Phase 1.5) so the model isn't relying on
      price/vol alone — options skew, liquidation cascades, basis. (Survey in progress.)
- [ ] Re-run this backtest monthly; watch for the first LONG signals appearing.
- [ ] Consider logging *would-be* signals (paper-trail) even below threshold, so we
      accumulate labeled near-misses for Phase 2 ML.
