"""增量同步脚本 — 只同步缺失日期，多线程并发。"""
import baostock as bs
import sqlite3
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

DB_PATH = "data/sequoia_v2.db"
WORKERS = 10  # baostock 并发不宜太高


def fetch_one(code: str, start_date: str, end_date: str) -> list[tuple]:
    """查询单只股票数据。"""
    try:
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        rs = bs.query_history_k_data_plus(
            f"{prefix}.{code}",
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0]:
                rows.append((code, row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
        return rows
    except Exception:
        return []


def main():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()]
    conn.close()

    today = date.today()
    latest_date = date.fromisoformat(latest)

    print(f"数据库最新: {latest}, 共 {len(symbols)} 只股票, 今天: {today}")

    if latest_date >= today:
        print("数据已是最新，无需同步")
        return

    # 从最新日期的下一天到今天
    start_date = (latest_date + timedelta(days=1)).isoformat()
    end_date = today.isoformat()
    print(f"同步范围: {start_date} ~ {end_date}")

    bs.login()
    t0 = time.time()
    all_rows = []
    done = 0
    no_data = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_one, code, start_date, end_date): code for code in symbols}
        for future in as_completed(futures):
            rows = future.result()
            if rows:
                all_rows.extend(rows)
            else:
                no_data += 1
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(symbols)} 查询完成, 有数据={len(all_rows)}条, 无数据={no_data}, {time.time()-t0:.0f}s")
                sys.stdout.flush()

    bs.logout()
    print(f"查询完成: {len(all_rows)} 条, {time.time()-t0:.0f}s")

    if not all_rows:
        print("无新数据（可能是非交易日或 baostock 尚未更新）")
        return

    # 批量写入
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executemany(
        "INSERT OR IGNORE INTO stock_daily (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        all_rows,
    )
    conn.commit()

    new_latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    new_count = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date = ?", (end_date,)).fetchone()[0]
    conn.close()

    print(f"同步完成! 最新: {new_latest}, {end_date}数据: {new_count}只, 总耗时: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
