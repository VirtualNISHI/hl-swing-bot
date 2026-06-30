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

---

## Multi-regime walk-forward — 2026-06-10 (THE decisive test)

Fetched the **full available HL 1h history: 5,002 bars = 208 days (2025-11-13 → 2026-06-09)**.
(HL `candleSnapshot` caps at ~5000 bars — no deeper history exists on the venue.) Ran the
EXISTING frozen params (score≥3.0, move≥1.0) — no tuning. This is 11× the prior 19-day window
and spans real uptrends, downtrends, and chop. Script: `scripts/walkforward.py`
(run with `PYTHON_JIT=0` — CPython 3.13 JIT crashes on the O(n²) hot loop).

**Headline answers:**
1. **Does LONG ever fire? → YES (38 LONG / 49 SHORT, 87 signals).** The strategy is NOT
   short-only by construction; the 19-day sample was just a downtrend. Good — that uncertainty
   is resolved.
2. **As built, there is NO edge after realistic costs.** Gross +0.16%/trade → **net ≈ −0.03%**
   at 0.19% round-trip (0.09% fees + 0.10% slippage), −0.14% at 0.30% RT. 40% hit-rate. The
   famous "+0.76%, 67%" was ONE lucky crash; over 7 months it's a coin flip.

**Per-regime (net of 0.19% round-trip) — the critical finding:**

| regime | n | L/S | gross | **net** |
|---|---|---|---|---|
| uptrend | 17 | 12/5 | −0.64% | **−0.83%** ❌ loses |
| downtrend (short) | 23 | 3/20 | +0.66% | **+0.47%** ✅ only edge |
| chop | 39 | 19/20 | +0.10% | **−0.09%** ❌ bleeds |
| **ALL** | 87 | 38/49 | +0.16% | **−0.03%** |

**Episode-level (72h same-dir merged = honest n): 87 raw → 33 independent episodes,
45% win-rate, +0.12% gross → ≈negative net.** No demonstrated edge.

**Interpretation:** The TA composite's only profitable cell is **short-side during
downtrends** (+0.47% net). It actively LOSES in uptrends (−0.83%, where the LONG side fires)
and bleeds in chop (−0.09%). So the bot is really a *short-cascade detector with a losing
long side and a losing chop habit bolted on*. The symmetric "swing both ways" thesis is
**falsified** for the current TA-only LONG branch.

**Kill-switch status:** NOT triggered (LONG fires; ≥3 regime cells; gross expectancy not <0).
But it is clearly "no edge as built" — marginal/breakeven, negative after honest costs.

**Implication for profitability (two paths):**
- **(A) Specialize → short-only downtrend bot.** Trade ONLY when trend_4h is down. Keeps the
  +0.47%-net cell, deletes the −0.83% uptrend bleed and −0.09% chop. Simplest, data-honest.
- **(B) Fix the LONG side with the liquidation bias** (squeeze detection) so longs stop losing
  — higher upside, unproven, needs the bias Spearman test first.
The data favors (A) now, (B) as the R&D track to earn back the long side.

### Path A IMPLEMENTED + validated (short-only, `ENABLE_LONG=False`)

Re-ran the 208d walk-forward with `short_only=True` (drops the losing LONG branch):

| mode | n | hit | gross | **net (0.19% RT)** | maxDD |
|---|---|---|---|---|---|
| both-ways | 87 | 40% | +0.16% | **−0.03%** | 16.3% |
| **SHORT-only** | 49 | 45% | +0.28% | **+0.09%** | **9.8%** |

Dropping longs flips net expectancy **positive** (+0.09%/trade, ≈+3.9% compounded over 7mo)
and **halves drawdown** (16.3%→9.8%). Thin but real, and structurally motivated (cascade
asymmetry). **Now live in paper as short-only.** Suppressed would-be LONGs are logged for
out-of-sample confirmation + Path-B. Caveats: still in-sample selection; +0.09% is marginal;
maxDD 9.8% still >8% graduation gate (→ needs the fractional-risk sizer). Forward paper +
the kill-switch remain the real test.

### Path A sizing added (fractional-risk + cluster cap) — DD now passes the gate

Added fixed-fractional-RISK sizing (`RISK_FRAC=0.005`, each stop-out loses exactly 0.5% of
equity regardless of the 4.6× atr_pct swing) + an aggregate `CLUSTER_RISK_CAP=1.5%` (max ~3
simultaneous shorts). Re-simulated the 208d short-only equity path with proper R-multiples:

| sizing | trades | final eq | **maxDD** | avg net R |
|---|---|---|---|---|
| naive all-in (prior) | 49 | +3.9% | 9.8% | — |
| **0.5%-risk + cluster cap** | 49 | +0.7% | **4.7%** ✅ | +0.03 |

**maxDD 4.7% now passes the <8% graduation gate.** Risk is properly controlled. BUT the
edge is genuinely thin — avg net R = +0.03, +0.7% compounded over 7 months. So: *not losing,
controlled risk, but not yet meaningfully profitable.* Real upside must come from Path B
(rebuild a profitable LONG via the bias squeeze signal) and/or sharpening short entries.
The cluster cap didn't bind on this sample (cooldown spacing kept <3 open) — safety net.

### Path B prep (liquidation-bias long rebuild)
`compute_features()` now reads `liq_bias` (forward-filled from the store) into every feature
dict, so each emitted signal records the bias at signal time. Not yet used in the score —
that waits on the Spearman(bias, forward-return) test once enough forward bias accumulates.

## Profit-logic lab — 2026-06-10 (6 empirical lenses + adversarial verification)

Six lenses each wrote/ran scratch scripts against the 208d history (scripts preserved in
`scratch/`). Every claimed improvement was then **adversarially re-derived by an independent
verifier** (exact reproduction required, split-half, n≥15/half, ±25% parameter nudges).
Baseline to beat: short-only NET +0.09%/trade, 49 trades, maxDD(sized) 4.7%.

### ✅ CONFIRMED (adopt)

| Improvement | net/trade | h1 / h2 | n | evidence |
|---|---|---|---|---|
| **Slope gate** — 4h SMA50 must be *declining* (SMA50 now < SMA50 10 4h-bars ago), on top of price<SMA | **+0.32%** | +0.27 / +0.36 | 37 | exact repro; lookback-insensitive (5–12 identical trades); **cross-asset: ETH kept +0.328 / removed −0.178, SOL kept +0.296 / removed −0.556**; in-loop = post-hoc identical |
| **Red-4h streak ≥2** — require 2+ consecutive red 4h bars at entry | **+0.36%** (in-loop) | +0.37 / +0.35 | 36 | monotone in threshold (≥1 +0.13, ≥3 +0.68); survives 0.30% cost; removed trades lose in BOTH halves |
| **BTC+ETH expansion** — identical frozen signal on ETH, global 1.5% cluster cap | **+0.153%** pooled | +0.20 / +0.10 | ~105 | byte-identical repro; SOL REJECTED (H2 sign flip); breadth on a correlated edge (40/49 co-fire within 6h), ~2.2× trades |

⚠️ Slope gate and red-streak are both downtrend-confirmation filters tested separately on the
same 49 trades — **overlap unmeasured. Run the joint backtest before stacking.**

### 🟡 UNCERTAIN (log-only, pre-registered re-checks; do NOT gate yet)

- **Exit BE@1.25ATR + TP 2.0** (headline +0.28): improvement concentrated in 3 trades
  (bootstrap p=0.135); what DOES replicate is **drawdown halving** (h2 2.62→1.35%). Re-derive
  the BE×TP grid on the slope-filtered trade set, then adopt primarily for DD.
- **funding_apr ≥ 8% gate** (+0.49, n=25): H2 n=8, each half rests on ONE squeeze episode,
  permutation p=0.11. 19/25 trades fire at HL's 10.95% APR floor (degenerate plateau).
- **funding_z_168 > 0.5 gate** (+0.78, n=20): permutation p=0.013 on BTC but **fails split-half
  on ETH and SOL** (Spearman ~0.06 there vs +0.31 BTC). Provisional; re-check after 20 paper signals.

### ❌ REJECTED (never re-litigate)

ATR floor/ceiling (deletes winners incl. +5.13% capitulation monsters) · score bands (sign
flips) · session/weekday filters (fragile/n<10) · trails 1.0/1.5 ATR (choke winners) · BE@0.75
(h2 neg) · partial TP (dominated) · time-stops alone · TP 3.5 · funding sign/momentum filters ·
|funding_z_24| gate as-is (24h window measures the wrong thing) · SOL standalone · 3-coin
portfolio (H2 neg) · vol-regime halves · depth≥3ATR · daily Coinalyze liq filters (fail H2).

### Annualized projection (0.5% risk sizing) — honest

- Baseline: ~86 t/yr × +0.032R ≈ **+1.4%/yr**, maxDD 4.7%
- Slope gate BTC-only: 65 t/yr × +0.217R ≈ **+7%/yr**, maxDD 2.9%
- Slope + ETH: ~144 t/yr ≈ **+12–15%/yr point estimate**, maxDD ~5–6%
- **Bluntly**: per-trade t-stats 1.0–1.4, one regime cycle, filters overlap. Realistic
  **+4–8%/yr**; the DD reduction is more trustworthy than the return number.

### Data acquisition (pre-registered decision tests committed BEFORE collection)

| Dataset | Method | Test that gates adoption |
|---|---|---|
| ETH/SOL funding (full window) | HL fundingHistory (fetched, in scratch/) | apr≥8 gate iff split-half + on ETH, n≥15/half |
| Coinalyze 1h liq/OI | **start hourly poller NOW** (key in Perp-oi-chart/.env); 1h history only goes back ~65d — every week of delay is lost data | oi_chg_24h gate iff Spearman≥+0.2 both halves; liq_6h_z>2 veto iff ρ≤−0.25 both halves after ≥50 signals |
| Binance taker imbalance | klines field 9, free, **backfills full 208d** | sell_share_6h Spearman≥+0.2 both halves (afternoon of work) |
| Binance 3y 1h klines | /api/v3/klines paginated | slope+streak must beat no-gate in ≥4 of 6 half-year segments |
| 5m candles (49 trade windows) | HL candleSnapshot interval=5m | replaces conservative intrabar assumptions in exit eval |
| LC bias / Nansen positioning | keep accumulating (4h cadence) | bias≤−30 gate iff Spearman≤−0.25 + subset dominance, ≥30 candidates |

### Implementation order (next 2 weeks)

1. Slope gate (features/signal/backtest in lockstep)
2. Fix `Storage.recent_funding_rates` (dedupe by hour — currently returns snapshots not hours) + backfill ≥169h funding at collector startup + log funding_z_168 on every signal (no gate)
3. Joint backtest slope × red-streak × BE/TP grid on BTC+ETH → adopt extras only on split-half pass
4. BTC+ETH live (coins list, global cluster cap)
5. Coinalyze 1h poller + Binance taker-imbalance backfill + 3y regime check
6. No real money until ≥20 paper signals match backtest behavior

## Slow-bleed research — 2026-07-01 (6 lenses, 100+ configs, Codex+Grok) → STAY DISCIPLINED

Live trigger: BTC bled -10% over 2 weeks as a slow grind, the bot fired 0 trades. Question:
expand to capture slow-bleed downtrends? Tested on **3y Binance BTC/ETH (26,280 1h bars each,
2023-07..2026-06, many regimes)** + HL 208d. Rules of evidence: NET of 0.19% RT; must pass
split-half (first 1.5y vs last 1.5y both +) AND cross-asset (BTC+ETH both +) AND HL hold.

**VERDICT: STAY DISCIPLINED. 0 of 100+ configs passed. No expansion ships.**
- Relax impulse gate (60-cell grid): **0/60** had a positive first half on either asset.
- Continuation / lower-low / SMA-below / pullback-fade (EMA/RSI/Fib, 11 rules) / time-cadence
  participation / longer-hold & trailing exits / regime-switch: **all net-negative on ≥1 asset**,
  all fail split-half. Best "expansion" (drop move+vol gate, keep score≥3): BTC +0.067 but H1 −15.4,
  ETH −0.057 — fails both gates.
- Why slow bleeds resist shorting: punctuated by violent relief rallies that tag the 1.5-ATR stop
  before the target (19–43% win rate the R:R can't survive). When forced to trade pure grinds the
  baseline LOST (BTC 2024-01 −20% grind: 5 trades, −3.21% net).
- Regime-switch proved adaptivity LOSES to purity on BOTH return and DD: routing a slow rule cut
  ETH ann +2.88%→−0.13% and **tripled maxDD (4.2%→13.6%)**.
- HL-208d makes rejected rules look great (it IS the favorable H2 bear regime) → textbook regime
  trap, the strongest evidence FOR discipline.

### ⚠️ CRITICAL side-finding: the shipped edge is itself REGIME-DEPENDENT
The baseline FAILS its own split-half on 3y: **first half (2023-24 chop/range) is net-NEGATIVE on
both BTC and ETH**; the entire SHORT edge lives in the 2025-26 bear. So:
- **The "+12–13%/yr" figure is HL-208d only = a pure bear window. Regime-inflated.**
- Honest full-3y multi-regime expectation at 0.5% risk: **~0%/yr BTC, +2.9%/yr ETH, maxDD 4–7%.**
- Implication: the cascade edge is real but **conditional on a bearish/volatile macro regime**. In
  2023-24-style chop or an uptrend it has no validated short edge — correctly sits out (which is
  why it's flat, not losing, in the current grind).

### Decision & implementation
- **SHIP NOTHING NEW.** Leave signal.py/features.py/backtest.py entry+exit params exactly as-is.
- The missed -10% grind was **correct, validated behavior** — the deliberate cost of not having a
  profitable slow-bleed edge. Prize is large (naive hold +229%/+404%) but harvestability ≈ 0.
- **Paper-only candidates (NOT shipped, must pass split-half+cross-asset+forward-HL first):**
  (1) wider/trailing exit on already-firing entries (TARGET 3-4 ATR + chandelier) — failed split-half
  here, A/B only; (2) a SLOWDOWN size-down/stand-aside flag (ret_30d<-3% & low recent move/ATR &
  4h slope≤-1) used ONLY to suppress over-trading, never to add shorts.
- **Next real research question** (separate study): a regime filter that DISARMS shorts in
  non-bearish macro regimes to avoid the H1-type capital bleed — addresses the regime-dependence,
  not the slow-bleed. Must itself pass split-half.

Codex + Grok independently agreed pre-data: stay a cascade specialist; relaxing gates / time-
participation "turn precision into exposure"; a second low-quality archetype hurts risk-adjusted
return; only exit-extension on existing entries is worth even testing (and it failed here too).

Scripts: scratch/ (analyze_all.py, relax_gate.py, fast_engine.py, grid.py, lens_*.py; outputs in
analyze_out.txt, lens_final.json). No repo source modified.

## Joint backtest + implementation — 2026-06-10 (SHIPPED)

Ran the pre-registered joint matrix (slope × streak × BE/TP exit) on BTC + ETH
(scratch/joint_backtest2.py, results in scratch/joint_results.txt):

| variant | BTC NET (h1/h2) | ETH NET (h1/h2) | decision |
|---|---|---|---|
| slope only | +0.318 (+0.27/+0.36) n=37 | +0.328 (+0.51/+0.21) n=45 | shipped |
| **slope+streak2** | **+0.758 (+1.12/+0.53) n=26** | **+0.877 (+1.15/+0.67) n=26** | **SHIPPED** |
| slope+BE1.25/TP2.0 | +0.454 (h2 +0.17 ⚠) | +0.448 (h2 +0.07 ⚠) | rejected |
| slope+streak+BE/TP | +0.428 — *worse than streak alone* | +0.951 (h1-loaded +2.06/+0.14) | rejected |

**Exit variant interaction confirmed the verifier's warning**: BE+TP2.0 was tuned on the
unfiltered trade mix and HURTS the streak-filtered cascades (fixed TP2.5 captures more of
the move; BE clips winners that retrace before continuing). Exits stay 1.5/2.5 ATR + 72h.

**Live config after this change** (all in lockstep across features/signal/backtest):
- SHORT-only, score≥3.0, move/ATR≥1.0, vol_z≥1.0
- 4h SMA50 trend gate **+ slope gate** (SMA50 declining vs 10 4h-bars ago)
- **red_4h_streak ≥ 2** (consecutive red 4h bars incl. partial bucket)
- |funding_z_24| ≤ 2.5 (now computed from REAL hourly funding — see below)
- R:R 1.5/2.5 ATR, 72h TTL, cooldown 4h/1h, 0.5% risk, cluster cap 1.5% **GLOBAL across coins**
- Universe: **BTC + ETH** (HL_COINS env; SOL rejected)

**Infrastructure shipped same day:**
- `funding_rates` table + `fetch_funding_history` pagination + collector backfill
  (200h on first run, incremental after). **Fixed latent bug**: `recent_funding_rates`
  returned the last n SNAPSHOTS (5-min cadence ⇒ n=24 covered ~2 hours, not 24) — now
  reads settled hourly rates, falls back to hour-deduped snapshots.
- `funding_z_168` computed and LOGGED on every signal (mean/pstdev convention), not gated.
- `backtest.py` gained slope_gate/red_streak_min/be_trigger_atr/target_atr_mult params +
  HIT_BE status; defaults mirror live (slope ON, streak 2).
- **Coinalyze adapter** (`adapters/coinalyze.py`): 1h long/short liquidations + OI for
  BTC+ETH into the feature store. Backfilled 9,360 rows (~65d, the full upstream retention).
  Runs in features.yml every 2h with COINALYZE_API_KEY secret. Pre-registered tests in the
  adapter docstring gate any future use as entry features.

Projection for the shipped config (point estimate, one regime cycle, n=26/coin —
LOW CONFIDENCE): ~45 trades/yr/coin × ~+0.4R × 0.5% ≈ +9%/yr/coin before correlation;
realistically mid-single-digits %/yr with maxDD ~3%. The paper track record decides.

## Quant panel review — 2026-06-10 (Codex + Grok + 6-lens panel)

Three independent reviews converged: **as built, this is a coin-flip after costs.** The
edge (if any) is in forced-flow microstructure (liquidations, funding, positioning),
NOT in the price/TA composite score. Real bugs found by reading the code:

1. **`signal.py` composite score scale bug** — `abs(f.get("move_per_atr_z",0.0) or
   f["move_per_atr"])`: when the z-score is exactly 0.0 it fell back to the raw ratio
   (different scale) in the 0.30-weight lead term. **FIXED 2026-06-10** (+ same in
   `backtest.py`). Didn't change the crash trades (large z there) but corrupted scores
   in neutral regimes.
2. **`realized_return` booked zero costs** — paper P&L was gross. **FIXED 2026-06-10**:
   now net of round-trip fees+slippage (`COST_RT_PCT=0.19%`). Funding-over-hold still
   TODO (can be material on 72h holds).
3. **3 of 5 score terms are collinear** (move_per_atr / robust_z_168 / ret_4h all = "price
   moved far from weekly median"). ~0.70 weight on one factor. → redesign (not yet done).
4. **`vol_z` double-counted** (score term + gate) and computed as robust-z not std-z →
   near-constant offset. → redesign.
5. **`funding_bonus` is perverse** — rewards *non-extreme* funding, direction-blind;
   penalizes the crash-shorts that actually fire. → redesign.
6. **liquidation bias is unwired** — ingested to the feature store but `compute_features()`
   never reads it back, so `signal.py` can't see it. This is the #1 opportunity (only
   directional, causal, orthogonal feature). → wire as signed term (after offline test).

Honest cost re-accounting of the existing 6 trades (still n≈1 regime): survive even
heavy slippage (+0.76% → +0.56% → +0.26% at 5/15/30 bps-per-side). They survive because
crash-onset moves are large — NOT evidence of generalizable edge.

## ⛔ PRE-REGISTERED KILL-SWITCH (committed 2026-06-10, do not move the goalposts)

The SPEC's "30+ signals, expectancy>0" criterion is **unfalsifiable-by-construction** —
clustered crash-shorts can tick that box while telling us nothing about LONG/chop. Replace
it with a regime-stratified bar. **Abandon the Phase-1 rule-based approach by 2026-09-10
(90 days) if ANY of:**

- (a) **zero LONG signals** ever fired across paper + offline walk-forward, OR
- (b) **fewer than 3 temporally-independent regime-events** (signals within 72h / same
  direction collapse into ONE event), OR
- (c) **pooled NET expectancy < 0** after fees + funding×hold-hours + realistic slippage,
  across those independent events, OR
- (d) the liquidation `bias_1h` shows **|Spearman| < 0.05** with forward 4h/24h return
  outside the June 1-3 crash window.

**Graduate paper → ¥10k real ONLY when ALL of:** ≥3 distinct regime cells (up/down/chop)
each with ≥8 independent episodes; ≥1 profitable LONG episode; pooled net expectancy >0
after full costs; backtested max DD <8% of equity at 0.5%-per-trade risk. Realistically
4–6 months, not 30 raw trades.

**No LightGBM** until ≥200 independent labeled signals across ≥2 regimes. Sooner = memorizing
one waterfall.

**The single biggest self-deception:** we grade every change against one crash. Every
proposed feature (bias, cost guard, sizer) was *favorable* in June 1-3, so the in-sample
backtest will always "improve." The one experiment that exposes it: **offline anchored
walk-forward over 12–18 months of 1h BTC with FROZEN params**, reporting per-regime-cell
and per-episode (not per-trade) net expectancy, and **whether the LONG branch fires at all**
in known uptrends. That is the next high-value task.
