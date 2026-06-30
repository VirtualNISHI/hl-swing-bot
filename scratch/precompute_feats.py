"""Precompute _compute_features_at for every bar of an asset, once. Cache to pickle.
Usage: python precompute_feats.py <csv> <out.pkl>
"""
import sys, types, csv, pickle, time
sys.modules['duckdb'] = types.ModuleType('duckdb')
from hl_swing_bot.backtest import HourlyBar, _compute_features_at, _composite_score
from hl_swing_bot.features import MIN_BARS


def load_bars(path):
    bars = []
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            bars.append(HourlyBar(
                int(row['open_time_ms']), float(row['open']), float(row['high']),
                float(row['low']), float(row['close']), float(row['volume']),
                int(row['trades']),
            ))
    return bars


def main():
    csv_path, out_path = sys.argv[1], sys.argv[2]
    bars = load_bars(csv_path)
    n = len(bars)
    t0 = time.time()
    feats = [None] * n
    scores = [None] * n
    for i in range(MIN_BARS, n):
        f = _compute_features_at(bars, i)
        feats[i] = f
        if f is not None:
            scores[i] = _composite_score(f)
        if i % 2000 == 0:
            print(f'{i}/{n} {time.time()-t0:.0f}s', flush=True)
    # store bars as plain tuples for the resolver (idx-aligned)
    bar_tuples = [(b.hour_ms, b.open, b.high, b.low, b.close, b.volume, b.trades) for b in bars]
    with open(out_path, 'wb') as fh:
        pickle.dump({'bars': bar_tuples, 'feats': feats, 'scores': scores}, fh)
    print(f'DONE {n} bars -> {out_path} in {time.time()-t0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
