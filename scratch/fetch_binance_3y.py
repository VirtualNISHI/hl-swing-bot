import httpx, csv, time, datetime

def fetch(symbol, out_path, years=3):
    now = int(time.time() * 1000)
    start = now - years * 365 * 86_400_000
    rows = {}
    cursor = start
    with httpx.Client(timeout=30) as c:
        for _ in range(2000):
            r = c.get('https://api.binance.com/api/v3/klines',
                      params={'symbol': symbol, 'interval': '1h',
                              'startTime': cursor, 'limit': 1000})
            r.raise_for_status()
            data = r.json()
            if not data:
                break
            for k in data:
                # 0 openT,1 o,2 h,3 l,4 c,5 vol,8 trades,9 takerBuyBase
                rows[int(k[0])] = (float(k[1]), float(k[2]), float(k[3]),
                                   float(k[4]), float(k[5]), int(k[8]), float(k[9]))
            last = data[-1][0]
            if last >= now or len(data) < 1000:
                break
            cursor = last + 1
            time.sleep(0.15)
    items = sorted(rows.items())
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['open_time_ms', 'open', 'high', 'low', 'close', 'volume', 'trades', 'taker_buy_base'])
        for t, v in items:
            w.writerow([t, *v])
    t0 = datetime.datetime.utcfromtimestamp(items[0][0] / 1000)
    t1 = datetime.datetime.utcfromtimestamp(items[-1][0] / 1000)
    print(f'{symbol}: {len(items)} bars  {t0:%Y-%m-%d} -> {t1:%Y-%m-%d}  ({(items[-1][0]-items[0][0])/86400000:.0f}d)')

fetch('BTCUSDT', 'scratch/binance_btc_3y.csv')
fetch('ETHUSDT', 'scratch/binance_eth_3y.csv')
