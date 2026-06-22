import baostock as bs
from pprint import pprint

SAMPLES = [
    '000001',
    '000002',
    '000333',
    '002160',
    '300550',
    '600000',
]

START = '2026-03-23'
END = '2026-06-18'


def to_bs(code: str) -> str:
    if code.startswith(('6', '9')):
        return f'sh.{code}'
    return f'sz.{code}'


def fetch(code: str):
    rs = bs.query_history_k_data_plus(
        to_bs(code),
        'date,open,high,low,close,volume,amount',
        start_date=START,
        end_date=END,
        frequency='d',
        adjustflag='3',
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    return rs.error_code, rs.error_msg, rows


def main():
    lg = bs.login()
    print('login', lg.error_code, lg.error_msg)
    try:
        for code in SAMPLES:
            err_code, err_msg, rows = fetch(code)
            print(f'=== {code} ===')
            print('error=', err_code, err_msg)
            print('count=', len(rows))
            print('head=')
            pprint(rows[:5])
            print('tail=')
            pprint(rows[-5:])
            print()
    finally:
        out = bs.logout()
        print('logout', out.error_code, out.error_msg)


if __name__ == '__main__':
    main()
