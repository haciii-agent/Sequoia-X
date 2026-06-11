"""
补全北交所 920xxx 股票数据 - 用 curl + proxy + TLS1.2 直连东方财富
"""
import os, sys, sqlite3, time, json, subprocess
from datetime import date

DB_PATH = "data/sequoia_v2.db"
TODAY = date.today().strftime("%Y%m%d")

def get_missing():
    import akshare as ak
    db = sqlite3.connect(DB_PATH)
    existing = set(r[0] for r in db.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall())
    db.close()
    all_syms = sorted(ak.stock_info_a_code_name()["code"].tolist())
    return [s for s in all_syms if s not in existing]

def fetch_bj(symbol):
    """curl+proxy+tls1.2拉取北交所股票"""
    try:
        # 北交所代码走 0. 前缀（东方财富 API）
        url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
               f"secid=0.{symbol}&fields1=f1,f2,f3,f4,f5,f6"
               f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
               f"&klt=101&fqt=1&end={TODAY}&lmt=1000")
        
        r = subprocess.run(
            ["curl", "-s", "--max-time", "10",
             "--tls-max", "1.2",
             "-x", "http://127.0.0.1:7897",
             "-H", "User-Agent: Mozilla/5.0",
             "-H", "Referer: https://quote.eastmoney.com/",
             url],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        
        data = json.loads(r.stdout)
        klines = data.get("data", {}).get("klines", []) if data.get("data") else []
        if not klines:
            return []
        
        out = []
        for kl in klines:
            p = kl.split(",")
            if len(p) < 11: continue
            try:
                out.append((symbol, p[0][:10],
                    float(p[1]), float(p[2]), float(p[3]), float(p[4]),
                    float(p[5])*100, float(p[6])))
            except: continue
        return out
    except:
        return None

def main():
    print("="*60)
    print("🚀 北交所 920xxx 补全（curl+proxy+TLS1.2）")
    print("="*60)
    
    missing = get_missing()
    print(f"\n缺失: {len(missing)} 只 (北交所)\n")
    
    if not missing:
        print("✅ 全部完成！")
        return
    
    saved = 0; failed = 0
    all_rows = []
    t0 = time.time()
    
    for i, sym in enumerate(missing):
        rows = fetch_bj(sym)
        if rows is None or len(rows) == 0:
            failed += 1
            if (i+1) % 50 == 0:
                print(f"  [{i+1}/{len(missing)}] ✅{saved} ❌{failed}  {time.time()-t0:.0f}s")
            continue
        
        all_rows.extend(rows)
        saved += 1
        
        if len(all_rows) >= 5000 or (i+1) % 50 == 0:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for b in range(0, len(all_rows), 5000):
                c.executemany("INSERT OR IGNORE INTO stock_daily VALUES (NULL,?,?,?,?,?,?,?,?)", all_rows[b:b+5000])
            conn.commit()
            conn.close()
            all_rows = []
        
        if (i+1) % 50 == 0:
            print(f"  [{i+1}/{len(missing)}] ✅{saved} ❌{failed}  {time.time()-t0:.0f}s")
    
    if all_rows:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for b in range(0, len(all_rows), 5000):
            c.executemany("INSERT OR IGNORE INTO stock_daily VALUES (NULL,?,?,?,?,?,?,?,?)", all_rows[b:b+5000])
        conn.commit()
        conn.close()
    
    conn = sqlite3.connect(DB_PATH)
    fin = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
    rec = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    min_d = conn.execute("SELECT MIN(date) FROM stock_daily").fetchone()[0]
    max_d = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    conn.close()
    
    print(f"\n✅ {time.time()-t0:.0f}s")    
    print(f"   成功: {saved} | 失败: {failed}")
    print(f"   DB: {fin}/{5527} 只 ({fin/5527*100:.1f}%) | {rec:,} 条")
    print(f"   {min_d} ~ {max_d}")
    print(f"\n{'🎉 全市场数据补全完成！' if fin >= 5500 else f'⚠️ 仍缺 {5527-fin} 只'}")

if __name__ == "__main__":
    main()