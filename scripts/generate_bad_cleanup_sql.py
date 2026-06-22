import csv
import sqlite3
from pathlib import Path

DB = 'data/sequoia_v2.db'
INPUT = Path('data/bad_price_scale_scan.csv')
OUT = Path('data/cleanup_bad_price_scale.sql')


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f'missing {INPUT}')

    statements = []
    with INPUT.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row['symbol']
            recent_dates = row['recent_dates'].split('|')
            for date in recent_dates:
                statements.append(
                    f"DELETE FROM stock_daily WHERE symbol = '{symbol}' AND date = '{date}';"
                )

    OUT.write_text('\n'.join(statements) + '\n', encoding='utf-8')
    print('statements=', len(statements))
    print('output=', OUT.as_posix())
    print('symbols=', len(set(s.split("'")[1] for s in statements)))


if __name__ == '__main__':
    main()
