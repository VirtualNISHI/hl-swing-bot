import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import csv, math, json, os
from hl_swing_bot.backtest import HourlyBar, run_backtest, _compute_features_at

FEE = 0.19  # round-trip net cost in pct

def cached_baseline(name, bars):
    """Run shipped-config backtest once; cache signals to JSON keyed by name."""
    cf = f'scratch/baseline_sigs_{name}.json'
    if os.path.exists(cf):
        with open(cf) as f:
            print(f'[cache hit] {cf}', flush=True)
            return json.load(f)
    print(f'[running run_backtest for {name} ... ~6min]', flush=True)
    res = run_backtest(bars, short_only=True)
    sigs = res['signals']
    with open(cf, 'w') as f:
        json.dump(sigs, f)
    print(f'[cached {len(sigs)} sigs -> {cf}]', flush=True)
    return sigs

def load(path):
    bars = []
    taker = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append(HourlyBar(int(row['open_time_ms']), float(row['open']), float(row['high']),
                                   float(row['low']), float(row['close']), float(row['volume']), int(row['trades'])))
            taker.append(float(row.get('taker_buy_base', 0.0)) if 'taker_buy_base' in row else 0.0)
    return bars, taker

def precompute_features(bars):
    feats = [None]*len(bars)
    for i in range(len(bars)):
        try:
            feats[i] = _compute_features_at(bars, i)
        except Exception:
            feats[i] = None
    return feats

def find_downtrend_months(bars, window_h=720, thresh=-8.0):
    """Sliding 30d (720h) windows; mark windows whose return < thresh. Then merge overlapping into episodes."""
    n = len(bars)
    closes = [b.close for b in bars]
    flagged = [False]*n  # flag END index of any 720h window with ret< thresh
    starts = []
    for end in range(window_h, n):
        start = end - window_h
        ret = (closes[end]/closes[start]-1.0)*100.0
        if ret < thresh:
            flagged[end] = True
    return flagged

def find_episodes(bars, drop_thresh=-8.0, min_len_h=240):
    """Identify downtrend EPISODES via peak-to-trough decomposition.
    Walk closes; an episode = from a local peak to the subsequent trough where
    peak->trough drawdown <= drop_thresh and duration >= min_len_h.
    Greedy: find global structure of significant declines."""
    closes = [b.close for b in bars]
    n = len(closes)
    episodes = []
    i = 0
    while i < n-1:
        # find peak start: local max scanning forward while we can still drop
        peak_idx = i
        peak_val = closes[i]
        # extend peak to the running max until a meaningful drop begins
        # We define: from current i, look for the trough that gives the deepest drawdown
        # within a forward search; then if drawdown<=thresh, record episode.
        # Track running min after peak
        trough_idx = i
        trough_val = closes[i]
        # we scan forward, updating peak if new high before any drop, else track min
        j = i
        cur_peak = closes[i]; cur_peak_idx = i
        cur_min = closes[i]; cur_min_idx = i
        best_dd = 0.0; best_peak_idx=i; best_trough_idx=i
        # Use a simple approach: scan forward up to when price recovers above peak (end of episode)
        while j < n:
            c = closes[j]
            if c > cur_peak and j == cur_min_idx:  # new peak only if no drop yet
                cur_peak = c; cur_peak_idx = j; cur_min = c; cur_min_idx = j
            else:
                if c < cur_min:
                    cur_min = c; cur_min_idx = j
                dd = (cur_min/cur_peak-1.0)*100.0
                if dd < best_dd:
                    best_dd = dd; best_peak_idx = cur_peak_idx; best_trough_idx = cur_min_idx
                # episode ends when price recovers to >= peak (full retrace) -> reset
                if c >= cur_peak:
                    break
            j += 1
        # record if significant
        if best_dd <= drop_thresh and (best_trough_idx-best_peak_idx) >= min_len_h:
            episodes.append((best_peak_idx, best_trough_idx, best_dd))
            i = best_trough_idx + 1
        else:
            i = j if j > i else i+1
    return episodes

def episode_classify(bars, feats, p, t):
    """max 1h |ret|/atr inside episode; also collect move_per_atr, vol_z dist."""
    max_mpa = 0.0
    mpas = []; volzs = []
    for k in range(p+1, t+1):
        f = feats[k]
        if f is None: continue
        mpa = abs(f.get('move_per_atr', 0.0))
        mpas.append(mpa); volzs.append(f.get('vol_z_168', 0.0))
        if mpa > max_mpa: max_mpa = mpa
    return max_mpa, mpas, volzs

def pctile(xs, q):
    if not xs: return float('nan')
    s = sorted(xs); idx = q*(len(s)-1)
    lo = int(math.floor(idx)); hi=int(math.ceil(idx))
    if lo==hi: return s[lo]
    return s[lo]+(s[hi]-s[lo])*(idx-lo)

def main(name, key, path):
    print(f'[loading {name}]', flush=True)
    bars, taker = load(path)
    print(f'[precomputing features {name}]', flush=True)
    feats = precompute_features(bars)
    n = len(bars)
    years = (bars[-1].hour_ms - bars[0].hour_ms)/1000/3600/24/365.25

    # --- BASELINE shipped bot ---
    sigs = cached_baseline(key, bars)
    nets = [s['realized_pct']-FEE for s in sigs if s.get('realized_pct') is not None]
    tot_net = sum(nets)
    mid_ms = (bars[0].hour_ms + bars[-1].hour_ms)//2
    nets_h1 = [s['realized_pct']-FEE for s in sigs if s.get('realized_pct') is not None and s['ms'] < mid_ms]
    nets_h2 = [s['realized_pct']-FEE for s in sigs if s.get('realized_pct') is not None and s['ms'] >= mid_ms]
    print(f"  split-half baseline: H1 n={len(nets_h1)} net={sum(nets_h1):.2f}% | H2 n={len(nets_h2)} net={sum(nets_h2):.2f}%", flush=True)
    print(f"\n===== {name} =====")
    print(f"bars={n} years={years:.2f}")
    print(f"[BASELINE shipped] trades={len(nets)} net_total={tot_net:.2f}% net/trade={tot_net/max(1,len(nets)):.3f}% trades/yr={len(nets)/years:.1f}")
    wins = sum(1 for x in nets if x>0)
    print(f"  winrate={wins/max(1,len(nets))*100:.1f}% avg_win={sum(x for x in nets if x>0)/max(1,wins):.2f}% avg_loss={sum(x for x in nets if x<=0)/max(1,len(nets)-wins):.2f}%")

    # --- DOWNTREND EPISODES ---
    eps = find_episodes(bars, drop_thresh=-8.0, min_len_h=240)
    print(f"[EPISODES] count={len(eps)} (peak->trough dd<=-8%, dur>=240h/10d)")

    # map signal entry idx -> in episode?
    sig_idx = {}
    for s in sigs:
        if s.get('realized_pct') is not None:
            sig_idx[s['idx']] = s['realized_pct']-FEE

    total_ep_hours = 0
    slow_hours = 0; fast_hours = 0
    slow_capturable = 0.0; fast_capturable = 0.0
    slow_eps=0; fast_eps=0
    ep_rows=[]
    in_ep_trades=0; in_ep_net=0.0
    all_mpa_in=[]; all_volz_in=[]
    SLOW_MAX_MPA = 3.0  # threshold: episodes whose max 1h move/atr < 3 = slow grind
    for (p,t,dd) in eps:
        dur = t-p
        total_ep_hours += dur
        max_mpa, mpas, volzs = episode_classify(bars, feats, p, t)
        all_mpa_in += mpas; all_volz_in += volzs
        # naive short hold: entry close[p], exit close[t]
        gross_hold = (bars[p].close/bars[t].close-1.0)*100.0  # short gain = entry/exit -1
        net_hold = gross_hold - FEE
        # trades fired inside episode
        et=0; en=0.0
        for k in range(p, t+1):
            if k in sig_idx:
                et+=1; en+=sig_idx[k]
        in_ep_trades+=et; in_ep_net+=en
        is_slow = max_mpa < SLOW_MAX_MPA
        if is_slow:
            slow_eps+=1; slow_hours+=dur; slow_capturable += -gross_hold  # capturable downside move magnitude
        else:
            fast_eps+=1; fast_hours+=dur; fast_capturable += -gross_hold
        ep_rows.append((p,t,dd,dur,max_mpa,gross_hold,net_hold,et,en,'SLOW' if is_slow else 'FAST'))

    print(f"[EPISODE COVERAGE] total_episode_hours={total_ep_hours} ({total_ep_hours/n*100:.1f}% of all bars)")
    print(f"  trades fired INSIDE episodes={in_ep_trades} net={in_ep_net:.2f}% (vs {len(nets)} total trades)")
    print(f"  SLOW eps={slow_eps} hours={slow_hours} ({slow_hours/max(1,total_ep_hours)*100:.0f}% of ep-hours)  capturable_downmove_sum={slow_capturable:.1f}%")
    print(f"  FAST eps={fast_eps} hours={fast_hours} ({fast_hours/max(1,total_ep_hours)*100:.0f}% of ep-hours)  capturable_downmove_sum={fast_capturable:.1f}%")
    tot_cap = slow_capturable+fast_capturable
    print(f"  capturable move: SLOW={slow_capturable/max(0.01,tot_cap)*100:.0f}% FAST={fast_capturable/max(0.01,tot_cap)*100:.0f}%")

    # naive buy-hold-short benchmark across all episodes
    gross_all = sum(r[5] for r in ep_rows)  # note gross_hold positive=short profit
    net_all = sum(r[6] for r in ep_rows)
    print(f"[NAIVE SHORT-HOLD per episode] sum_gross={gross_all:.1f}% sum_net={net_all:.1f}% (entry peak, exit trough, one short per ep)")

    # WHY no fire: distribution of move_per_atr and vol_z during episodes
    print(f"[WHY NO FIRE - feature dist inside episodes]")
    print(f"  move_per_atr |.|: p50={pctile([abs(x) for x in all_mpa_in],.5):.2f} p90={pctile([abs(x) for x in all_mpa_in],.9):.2f} p99={pctile([abs(x) for x in all_mpa_in],.99):.2f} max={max([abs(x) for x in all_mpa_in],default=0):.2f}")
    frac_mpa_ge1 = sum(1 for x in all_mpa_in if abs(x)>=1.0)/max(1,len(all_mpa_in))
    print(f"  frac bars with |move_per_atr|>=1.0 (entry gate): {frac_mpa_ge1*100:.1f}%")
    print(f"  vol_z_168: p50={pctile(all_volz_in,.5):.2f} p90={pctile(all_volz_in,.9):.2f} p99={pctile(all_volz_in,.99):.2f}")
    frac_volz_ge1 = sum(1 for x in all_volz_in if x>=1.0)/max(1,len(all_volz_in))
    print(f"  frac bars with vol_z>=1.0 (entry gate): {frac_volz_ge1*100:.1f}%")

    # per-episode table (top 15 by magnitude)
    print(f"[TOP EPISODES] peak_ms..trough_ms dd% durH maxMPA shortHold% trades net% class")
    for r in sorted(ep_rows, key=lambda x:x[2])[:15]:
        p,t,dd,dur,mmpa,gh,nh,et,en,cls = r
        from datetime import datetime, timezone
        ps = datetime.fromtimestamp(bars[p].hour_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        ts = datetime.fromtimestamp(bars[t].hour_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')
        print(f"  {ps}..{ts} dd={dd:6.1f}% dur={dur:4d}h maxMPA={mmpa:4.1f} shortHold={gh:6.1f}% tr={et} net={en:6.2f}% {cls}")

    return dict(name=name, years=years, baseline_trades=len(nets), baseline_net=tot_net,
                eps=len(eps), slow_eps=slow_eps, fast_eps=fast_eps,
                slow_cap=slow_capturable, fast_cap=fast_capturable,
                in_ep_trades=in_ep_trades, in_ep_net=in_ep_net, naive_net=net_all)

if __name__=='__main__':
    r1=main('BTC 3y', 'btc', 'scratch/binance_btc_3y.csv')
    r2=main('ETH 3y', 'eth', 'scratch/binance_eth_3y.csv')
