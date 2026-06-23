import json
import sqlite3
import time
from pathlib import Path

import requests

DB = 'data/sequoia_v2.db'
SYMBOLS_JSON = 'data/gap_60d_symbols.json'
STATE_JSON = Path('data/gap_60d_sync_state.json')
USER_AGENT = {'User-Agent': 'Mozilla/5.0'}
MAX_RUNTIME_SECONDS = 150
BATCH_SIZE = 400
REQUEST_SLEEP_SECONDS = 0.05
FAIL_SLEEP_SECONDS = 0.2
MAX_DB_RETRIES = 5
DB_RETRY_SLEEP_SECONDS = 0.5


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
    response = requests.get(url, headers=USER_AGENT, timeout=20)
    response.raise_for_status()
    data = response.json().get('data', {}).get(secid, {})
    return data.get('day', [])


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
        for attempt in range(MAX_DB_RETRIES):
            try:
                conn.execute(
                    '''
                    INSERT OR REPLACE INTO stock_daily
                    (symbol, date, open, high, low, close, volume, turnover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT turnover FROM stock_daily WHERE symbol=? AND date=?), 0.0))
                    ''',
                    (symbol, trade_date, open_price, high_price, low_price, close_price, volume, symbol, trade_date),
                )
                written += 1
                break
            except sqlite3.OperationalError as error:
                if 'database is locked' not in str(error).lower() or attempt == MAX_DB_RETRIES - 1:
                    raise
                time.sleep(DB_RETRY_SLEEP_SECONDS * (attempt + 1))
    return written


def load_state(total_symbols: int) -> dict:
    if not STATE_JSON.exists():
        return {'cursor': 0, 'completed_cycles': 0, 'last_total_symbols': total_symbols}
    try:
        state = json.loads(STATE_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {'cursor': 0, 'completed_cycles': 0, 'last_total_symbols': total_symbols}
    if state.get('last_total_symbols') != total_symbols:
        state['cursor'] = 0
        state['last_total_symbols'] = total_symbols
    state.setdefault('completed_cycles', 0)
    return state


def save_state(state: dict) -> None:
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    start_ts = time.time()
    with open(SYMBOLS_JSON, 'r', encoding='utf-8') as f:
        symbols = json.load(f)

    state = load_state(len(symbols))
    cursor = int(state.get('cursor', 0)) % len(symbols)

    conn = sqlite3.connect(DB, timeout=60)
    conn.execute('PRAGMA busy_timeout=60000')
    conn.execute('PRAGMA journal_mode=WAL')

    target_dates = [r[0] for r in conn.execute('SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 60').fetchall()]
    if not target_dates:
        raise RuntimeError('stock_daily has no dates; cannot determine repair window')
    start_date = min(target_dates)
    end_date = max(target_dates)

    total_written = 0
    success = 0
    failed = 0
    processed = 0

    while processed < len(symbols) and processed < BATCH_SIZE:
        if time.time() - start_ts >= MAX_RUNTIME_SECONDS:
            break
        index = (cursor + processed) % len(symbols)
        symbol = symbols[index]
        try:
            rows = fetch_qq_day(symbol, start_date, end_date)
            if rows:
                total_written += write_rows(conn, symbol, rows)
                success += 1
            time.sleep(REQUEST_SLEEP_SECONDS)
        except Exception as error:
            failed += 1
            print(f'FAIL {symbol}: {error}', flush=True)
            time.sleep(FAIL_SLEEP_SECONDS)
        processed += 1
        if processed % 50 == 0:
            conn.commit()
            print(
                f'processed={processed} batch_limit={BATCH_SIZE} cursor={cursor} '
                f'success={success} failed={failed} written={total_written}',
                flush=True,
            )

    conn.commit()
    conn.close()

    next_cursor = (cursor + processed) % len(symbols)
    cycle_completed = cursor + processed >= len(symbols)
    if cycle_completed:
        state['completed_cycles'] = int(state.get('completed_cycles', 0)) + 1
    state.update(
        {
            'cursor': next_cursor,
            'last_total_symbols': len(symbols),
            'last_run_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'last_processed': processed,
            'last_success': success,
            'last_failed': failed,
            'last_written': total_written,
            'last_window_start': start_date,
            'last_window_end': end_date,
            'last_cycle_completed': cycle_completed,
        }
    )
    save_state(state)

    print(
        json.dumps(
            {
                'processed': processed,
                'success': success,
                'failed': failed,
                'written': total_written,
                'next_cursor': next_cursor,
                'completed_cycles': state.get('completed_cycles', 0),
                'cycle_completed': cycle_completed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == '__main__':
    main()
