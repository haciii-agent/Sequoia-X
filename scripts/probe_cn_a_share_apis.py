import json
from pathlib import Path

import requests

HEADERS = {'User-Agent': 'Mozilla/5.0'}
OUT = Path('data/cn_a_share_api_probe.json')

CANDIDATES = [
    ('eastmoney_push2his', 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.000001&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=0&beg=20260323&end=20260618'),
    ('eastmoney_push2_quote', 'https://push2.eastmoney.com/api/qt/stock/get?secid=0.000001&fields=f57,f58,f43,f44,f45,f46'),
    ('sina_quote', 'https://hq.sinajs.cn/list=sz000001'),
    ('qq_quote', 'https://qt.gtimg.cn/q=sz000001'),
    ('netease_history', 'https://quotes.money.163.com/service/chddata.html?code=1000001&start=20260323&end=20260618&fields=TCLOSE;HIGH;LOW;TOPEN;VOTURNOVER'),
    ('ifeng_quote', 'https://api.finance.ifeng.com/akdaily/?code=sz000001&type=last'),
]


def probe(name, url, proxies):
    item = {'name': name, 'url': url, 'proxy_mode': proxies}
    px = None
    if proxies == 'disabled':
        px = {'http': None, 'https': None}
    elif proxies == 'explicit_7897':
        px = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, proxies=px)
        item['status_code'] = r.status_code
        item['ok'] = r.ok
        item['text_head'] = r.text[:500]
        item['content_type'] = r.headers.get('content-type', '')
    except Exception as e:
        item['error'] = repr(e)
    return item


def main():
    results = []
    for name, url in CANDIDATES:
        for proxy_mode in ['default', 'disabled', 'explicit_7897']:
            res = probe(name, url, proxy_mode)
            results.append(res)
            print('===', name, proxy_mode, '===')
            print(json.dumps(res, ensure_ascii=False, indent=2)[:1000])
            print()
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved=', OUT.as_posix())


if __name__ == '__main__':
    main()
