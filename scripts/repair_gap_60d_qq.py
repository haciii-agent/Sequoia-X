import json
import sqlite3
import time

import requests

DB = 'data/sequoia_v2.db'
SYMBOLS_JSON = 'data/gap_60d_symbols.json'
USER_AGENT = {'User-Agent': 'Mozilla/5.0'}


def market_prefix(symbol: str) -> str:
    if symbol.startswith(('6', '9')):
        return 'sh'
    return 'sz'


def fetch_qq_day(symbol: str, start_date: str, end_date: str):
    secid = f"{market_prefix(symbol)}{symbol}"
    url = (
        'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
        f'?param={secid},day,{start_date},{end_date},120'
    )
    r = requests.get(url, headers=USER_AGENT, timeout=20)
    r.raise_for_status()
    data = r.json().get('data', {}).get(secid, {})
    rows = data.get('day', [])
    return rows


def write_rows(conn: sqlite3.Connection, symbol: str, rows):
    written = 0
    for row in rows:
        try:
            trade_date = row[0]
            open_price = float(row[1])
            close_price = float(row[2])
            high_price = float(row[3])
            low_price = float(row[4])
            volume = float(row[5]) * 100.0
        except Exception:
            continue
        if close_price <= 0:
            continue
        conn.execute(
            '''
            INSERT OR REPLACE INTO stock_daily
            (symbol, date, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT turnover FROM stock_daily WHERE symbol=? AND date=?), 0.0))
            ''',
            (symbol, trade_date, open_price, high_price, low_price, close_price, volume, symbol, trade_date),
        )
        written += 1
    return written


def main():
    with open(SYMBOLS_JSON, 'r', encoding='utf-8') as f:
        symbols = json.load(f)

    conn = sqlite3.connect(DB, timeout=60)
    conn.execute('PRAGMA busy_timeout=60000')
    conn.execute('PRAGMA journal_mode=WAL')

    target_dates = [r[0] for r in conn.execute('SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 60').fetchall()]
    start_date = min(target_dates)
    end_date = max(target_dates)

    total_written = 0
    success = 0
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        try:
            rows = fetch_qq_day(symbol, start_date, end_date)
            if rows:
                total_written += write_rows(conn, symbol, rows)
                success += 1
            if i % 50 == 0:
                conn.commit()
                print(f'processed={i}/{len(symbols)} success={success} failed={failed} written={total_written}', flush=True)
            time.sleep(0.2)
        except Exception as e:
            failed += 1
            print(f'FAIL {symbol}: {e}', flush=True)
            time.sleep(0.5)

    conn.commit()
    conn.close()
    print({'processed': len(symbols), 'success': success, 'failed': failed, 'written': total_written})


if __name__ == '__main__':
    main()
