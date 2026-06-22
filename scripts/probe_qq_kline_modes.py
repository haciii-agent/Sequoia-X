import json
import requests

HEADERS = {'User-Agent': 'Mozilla/5.0'}
URLS = [
    ('fq_qfq', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000001,day,2026-03-23,2026-06-18,200,qfq'),
    ('fq_hfq', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000001,day,2026-03-23,2026-06-18,200,hfq'),
    ('fq_none', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000001,day,2026-03-23,2026-06-18,200,'),
    ('kline_plain', 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sz000001,day,2026-03-23,2026-06-18,200'),
    ('kline_short', 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sz000001,day,,,200'),
]

for name, url in URLS:
    print('===', name, '===')
    r = requests.get(url, headers=HEADERS, timeout=20)
    print('status=', r.status_code)
    data = r.json()
    print('keys=', list(data.keys()))
    inner = next(iter(data.get('data', {}).values()), {})
    print('inner_keys=', list(inner.keys()))
    for k, v in inner.items():
        if isinstance(v, list):
            print('series', k, 'len=', len(v), 'head=', v[:2])
    print()
