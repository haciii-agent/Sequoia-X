import sqlite3
from collections import Counter
from pathlib import Path

DB = Path('data/sequoia_v2.db')


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    latest_dates = [r[0] for r in cur.execute('SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 60').fetchall()]
    if not latest_dates:
        print('数据库为空')
        return

    latest_3 = latest_dates[:3]
    latest_60 = latest_dates
    ph3 = ','.join('?' for _ in latest_3)
    ph60 = ','.join('?' for _ in latest_60)

    all_symbols = [r[0] for r in cur.execute('SELECT DISTINCT symbol FROM stock_daily').fetchall()]
    total = len(all_symbols)

    cov3 = dict(cur.execute(f'''SELECT symbol, COUNT(DISTINCT date) FROM stock_daily WHERE date IN ({ph3}) GROUP BY symbol''', latest_3).fetchall())
    cov60 = dict(cur.execute(f'''SELECT symbol, COUNT(DISTINCT date) FROM stock_daily WHERE date IN ({ph60}) GROUP BY symbol''', latest_60).fetchall())

    full3 = sum(1 for s in all_symbols if cov3.get(s, 0) == len(latest_3))
    full60 = sum(1 for s in all_symbols if cov60.get(s, 0) == len(latest_60))

    dist60 = Counter()
    for s in all_symbols:
        c = cov60.get(s, 0)
        if c == 60:
            dist60['full_60'] += 1
        elif c >= 55:
            dist60['minor_gap_55_59'] += 1
        elif c >= 20:
            dist60['medium_gap_20_54'] += 1
        elif c >= 1:
            dist60['severe_gap_1_19'] += 1
        else:
            dist60['zero_in_window'] += 1

    print('=== Sequoia-X 数据健康检查 ===')
    print(f'总股票数: {total}')
    print(f'最近3个交易日完整覆盖: {full3}/{total} ({full3/total*100:.1f}%)')
    print(f'最近60个交易日完整覆盖: {full60}/{total} ({full60/total*100:.1f}%)')
    print(f'最新60日分布: {dict(dist60)}')
    print(f'最新日期窗口: {min(latest_60)} ~ {max(latest_60)}')


if __name__ == '__main__':
    main()
