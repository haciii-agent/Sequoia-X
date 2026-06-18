import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import requests

DB_PATH = Path("data/sequoia_v2.db")
STATE_PATH = Path("data/sequoia_v2.sync_state.json")


def sign_url(url: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    return f"{url}&timestamp={timestamp}&sign={sign}"


def get_dingtalk_config() -> tuple[str, str]:
    webhook = os.getenv("DINGTALK_WEBHOOK", "").strip()
    secret = os.getenv("DINGTALK_SECRET", "").strip()
    if not webhook or not secret:
        raise ValueError("缺少钉钉配置：请在 .env 中设置 DINGTALK_WEBHOOK 和 DINGTALK_SECRET")
    return webhook, secret


def main() -> None:
    webhook, secret = get_dingtalk_config()
    target_date = (date.today() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    latest = cur.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    total_symbols = cur.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
    target_symbols = cur.execute(
        "SELECT COUNT(*) FROM (SELECT symbol, MAX(date) AS max_date FROM stock_daily GROUP BY symbol) WHERE max_date >= ?",
        (target_date,),
    ).fetchone()[0]
    stale_symbols = total_symbols - target_symbols
    top_dates = cur.execute(
        """
        SELECT max_date, COUNT(*) FROM (
            SELECT symbol, MAX(date) AS max_date FROM stock_daily GROUP BY symbol
        ) GROUP BY max_date ORDER BY max_date DESC LIMIT 8
        """
    ).fetchall()
    conn.close()

    remaining_chunks = None
    remaining_chunk_symbols = None
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            chunks = state.get("chunks", [])
            remaining_chunks = len(chunks)
            remaining_chunk_symbols = sum(len(chunk) for chunk in chunks)
        except Exception:
            remaining_chunks = None
            remaining_chunk_symbols = None

    pct = (target_symbols / total_symbols * 100) if total_symbols else 0.0
    lines = [
        "## Sequoia-X 同步进度",
        f"- 目标日期：{target_date}",
        f"- 全库最新日期：{latest}",
        f"- 已达目标股票：{target_symbols}/{total_symbols} ({pct:.1f}%)",
        f"- 未达目标股票：{stale_symbols}",
    ]
    if remaining_chunks is not None:
        lines.append(f"- 断点剩余分块：{remaining_chunks}")
    if remaining_chunk_symbols is not None:
        lines.append(f"- 断点剩余股票：{remaining_chunk_symbols}")
    lines.append("")
    lines.append("### 最新日期分布")
    for trade_date, count in top_dates:
        lines.append(f"- {trade_date}: {count} 只")

    title = f"同步进度 {target_symbols}/{total_symbols}"
    text = "\n".join(lines)

    response = requests.post(
        sign_url(webhook, secret),
        json={
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        },
        timeout=15,
    )
    print(text)
    print(f"dingtalk_status={response.status_code}")
    try:
        print(response.text[:500])
    except Exception:
        pass


if __name__ == "__main__":
    main()
