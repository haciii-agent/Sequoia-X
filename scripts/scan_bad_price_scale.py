import csv
import sqlite3
from pathlib import Path

DB = 'data/sequoia_v2.db'
OUT = Path('data/bad_price_scale_scan.csv')


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    symbols = [r[0] for r in cur.execute('SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol')]
    rows_out = []

    for symbol in symbols:
        rows = cur.execute(
            'SELECT date, close FROM stock_daily WHERE symbol=? ORDER BY date DESC LIMIT 20',
            (symbol,),
        ).fetchall()
        if len(rows) < 4:
            continue

        recent = rows[:3]
        old = rows[3:10]
        recent_closes = [r[1] for r in recent if r[1] not in (None, 0)]
        old_closes = [r[1] for r in old if r[1] not in (None, 0)]
        if not recent_closes or not old_closes:
            continue

        recent_med = sorted(recent_closes)[len(recent_closes)//2]
        old_med = sorted(old_closes)[len(old_closes)//2]
        ratio = max(recent_med, old_med) / min(recent_med, old_med)

        if ratio >= 3:
            rows_out.append({
                'symbol': symbol,
                'recent_dates': '|'.join(r[0] for r in recent),
                'recent_closes': '|'.join(str(r[1]) for r in recent),
                'old_dates': '|'.join(r[0] for r in old[:3]),
                'old_closes': '|'.join(str(r[1]) for r in old[:3]),
                'recent_median_close': recent_med,
                'old_median_close': old_med,
                'scale_ratio': round(ratio, 4),
                'total_rows': cur.execute('SELECT COUNT(*) FROM stock_daily WHERE symbol=?', (symbol,)).fetchone()[0],
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()) if rows_out else [
            'symbol','recent_dates','recent_closes','old_dates','old_closes','recent_median_close','old_median_close','scale_ratio','total_rows'
        ])
        writer.writeheader()
        writer.writerows(sorted(rows_out, key=lambda x: (-x['scale_ratio'], x['symbol'])))

    print('bad_symbols=', len(rows_out))
    print('output=', OUT.as_posix())
    for row in sorted(rows_out, key=lambda x: (-x['scale_ratio'], x['symbol']))[:20]:
        print(row)


if __name__ == '__main__':
    main()
