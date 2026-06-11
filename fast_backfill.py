"""
快速回填 v13 - baostock 分批回填 + 自动重试
每次登录拉 500 只，登出，分批次完成
"""
import os, sys, sqlite3, time
from datetime import date

DB_PATH = "data/sequoia_v2.db"
TODAY = date.today().strftime("%Y-%m-%d")
BATCH_SIZE = 500  # 每批500只

def get_all_symbols():
    import akshare as ak
    df = ak.stock_info_a_code_name()
    return sorted(df["code"].tolist())

def to_bs(s):
    if s.startswith("920") or s.startswith(("4", "8")):
        return f"bj.{s}"
    elif s.startswith(("6", "9")):
        return f"sh.{s}"
    return f"sz.{s}"

def get_existing():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
    conn.close()
    return set(r[0] for r in rows)

def process_batch(symbols, batch_label):
    """登录一次，拉一批，登出一次"""
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        print(f"  登录失败: {lg.error_msg}")
        return 0
    
    all_rows = []
    t0 = time.time()
    
    for i, sym in enumerate(symbols):
        try:
            bs_code = to_bs(sym)
            rs = bs.query_history_k_data_plus(
                bs_code, "date,open,high,low,close,volume,amount",
                start_date="2024-01-01", end_date=TODAY,
                frequency="d", adjustflag="1")
            if rs.error_code == "0":
                rows = []
                while rs.next():
                    row = rs.get_row_data()
                    if row[1] == "None": continue
                    rows.append(row)
                for r in rows:
                    all_rows.append((sym, r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                        float(r[5]) if r[5] != "None" else 0,
                        float(r[6]) if r[6] != "None" else 0))
        except:
            pass
        
        if (i+1) % 100 == 0:
            print(f"  {batch_label} [{i+1}/{len(symbols)}] {len(all_rows)}条K线 {time.time()-t0:.0f}s")
    
    bs.logout()
    
    if all_rows:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for b in range(0, len(all_rows), 5000):
            c.executemany("INSERT OR IGNORE INTO stock_daily VALUES (NULL,?,?,?,?,?,?,?,?)", all_rows[b:b+5000])
        conn.commit()
        conn.close()
    
    return len(set(r[0] for r in all_rows))

def main():
    print("="*60)
    print("🚀 v13 baostock分批回填")
    print("="*60)
    
    all_syms = get_all_symbols()
    existing = get_existing()
    missing = [s for s in all_syms if s not in existing]
    
    total_before = len(existing)
    total = len(all_syms)
    
    print(f"\n已有: {total_before} | 缺失: {len(missing)} | 总数: {total}")
    
    if not missing:
        print("✅ 全部完成！")
        return
    
    # 分批处理
    batches = [missing[i:i+BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    print(f"  共 {len(batches)} 批，每批 {BATCH_SIZE} 只\n")
    
    total_added = 0
    t_start = time.time()
    
    for bi, batch in enumerate(batches):
        saved = process_batch(batch, f"[{bi+1}/{len(batches)}]")
        total_added += saved
        current = get_existing()
        elapsed = time.time() - t_start
        print(f"  ✅ 批次{bi+1}: +{saved} 只 (累计 +{len(current)-total_before}) {elapsed:.0f}s")
    
    final = get_existing()
    elapsed = time.time() - t_start
    
    conn = sqlite3.connect(DB_PATH)
    rec = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    min_d = conn.execute("SELECT MIN(date) FROM stock_daily").fetchone()[0]
    max_d = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"✅ 全部完成! {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"   数据库: {len(final)}/{total} 只 | {rec:,} 条")
    print(f"   日期: {min_d} ~ {max_d}")
    
    if len(final) >= total:
        print("\n🎉 全市场数据补全完成！")
    else:
        print(f"\n⚠️ 仍缺 {total - len(final)} 只，再次运行继续补")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()