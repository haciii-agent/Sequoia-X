import base64
import hashlib
import hmac
import sqlite3
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import requests

DB_PATH = Path("data/sequoia_v2.db")
WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=3eb30f8d052e349dabf404d46d173ce3725a01434a21f4754c7ccc1bd1da8b80"
SECRET = "SECc00e1486253015c8048903db9dbdb4c3e8b1a331212bd2859c232ff16e059e33"
MARKER = Path("data/.sync_completed_2026_06_17.marker")


def sign_url(url: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    return f"{url}&timestamp={timestamp}&sign={sign}"


def main() -> None:
    target_date = (date.today() - timedelta(days=1)).isoformat()
    marker = MARKER.with_name(f".sync_completed_{target_date.replace('-', '_')}.marker")
    if marker.exists():
        print("")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_symbols = cur.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
    target_symbols = cur.execute(
        "SELECT COUNT(*) FROM (SELECT symbol, MAX(date) AS max_date FROM stock_daily GROUP BY symbol) WHERE max_date >= ?",
        (target_date,),
    ).fetchone()[0]
    conn.close()

    if total_symbols == 0 or target_symbols < total_symbols:
        print("")
        return

    text = "\n".join([
        "## Sequoia-X 同步完成",
        f"- 目标日期：{target_date}",
        f"- 已达目标股票：{target_symbols}/{total_symbols}",
        "- 状态：全部股票都已补到昨天或更新",
    ])

    resp = requests.post(
        sign_url(WEBHOOK, SECRET),
        json={
            "msgtype": "markdown",
            "markdown": {"title": "Sequoia-X 同步完成", "text": text},
        },
        timeout=15,
    )
    marker.write_text("done\n", encoding="utf-8")
    print(text)
    print(f"dingtalk_status={resp.status_code}")
    try:
        print(resp.text[:500])
    except Exception:
        pass


if __name__ == "__main__":
    main()
