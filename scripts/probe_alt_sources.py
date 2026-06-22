import json
from pathlib import Path

import requests

OUT = Path('data/source_probe_results.json')


def probe_requests(name: str, url: str, headers=None, timeout=15):
    result = {'name': name, 'url': url}
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        result['status_code'] = r.status_code
        result['ok'] = r.ok
        result['text_head'] = r.text[:1000]
    except Exception as e:
        result['error'] = repr(e)
    return result


def probe_akshare_hist():
    result = {'name': 'akshare_stock_hist'}
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol='000001', period='daily', start_date='20260323', end_date='20260618', adjust='')
        result['rows'] = len(df)
        result['tail'] = df.tail(3).to_dict(orient='records')
    except Exception as e:
        result['error'] = repr(e)
    return result


def main() -> None:
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = [
        probe_akshare_hist(),
        probe_requests(
            'eastmoney_push2_requests',
            'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.000001&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=0&beg=20260323&end=20260618',
            headers=headers,
        ),
        probe_requests(
            'sina_quote_requests',
            'https://hq.sinajs.cn/list=sz000001',
            headers=headers,
        ),
    ]

    for item in results:
        print('===', item['name'], '===')
        print(json.dumps(item, ensure_ascii=False, indent=2)[:2000])
        print()

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved=', OUT.as_posix())


if __name__ == '__main__':
    main()
