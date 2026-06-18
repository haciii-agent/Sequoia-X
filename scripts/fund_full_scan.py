#!/usr/bin/env python3
"""全A股基金稳定收益扫描 - 使用fundapi"""
import json, time, urllib.request
from datetime import datetime

def fetch(ft="gp", pn=500, pi=1):
    url = f"https://fundapi.eastmoney.com/fundtradenew.aspx?ft={ft}&sc=1nzf&st=desc&pi={pi}&pn={pn}&cp=&ct=&cd=&ms=&fr=&plession=&fst=&ftype=&fr1=&fl=0&is498=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=20)
    text = resp.read().decode("utf-8")
    
    if 'datas:[' not in text:
        return [], 0
    
    start = text.index('datas:["') + 8
    end = text.index('"]', start)
    raw = text[start:end]
    items = raw.split('","')
    
    # allRecords
    ar_start = text.index('allRecords:') + 11
    ar_end = text.index(',', ar_start)
    total = int(text[ar_start:ar_end])
    
    funds = []
    for item in items:
        parts = item.split("|")
        if len(parts) < 14:
            continue
        try:
            code = parts[0]
            name = parts[1]
            ret_1w = float(parts[5]) if parts[5] else None
            ret_1m = float(parts[6]) if parts[6] else None
            ret_3m = float(parts[7]) if parts[7] else None
            ret_6m = float(parts[8]) if parts[8] else None
            ret_1y = float(parts[9]) if parts[9] else None
            ret_2y = float(parts[10]) if parts[10] else None
            ret_ytd = float(parts[13]) if parts[13] else None
            
            if ret_1y is not None:
                funds.append({
                    "code": code, "name": name,
                    "ret_1w": ret_1w, "ret_1m": ret_1m, "ret_3m": ret_3m,
                    "ret_6m": ret_6m, "ret_1y": ret_1y, "ret_2y": ret_2y, "ret_ytd": ret_ytd,
                })
        except (ValueError, IndexError):
            continue
    
    return funds, total

def stability(f):
    """稳定分: 收益均值/波动率"""
    rets = [r for r in [f.get("ret_1m"), f.get("ret_3m"), f.get("ret_6m"), f.get("ret_1y")] if r is not None]
    if len(rets) < 3:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean)**2 for r in rets) / len(rets)
    std = var ** 0.5
    if std == 0:
        return round(min(mean, 100), 1)
    # 收益/波动比 (类似夏普)
    ratio = mean / std * 10
    return round(min(ratio, 100), 1)

def main():
    print("=" * 90)
    print("全A股基金稳定收益扫描")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 90)
    
    all_funds = []
    types = [
        ("gp", "股票型", 2000),
        ("hh", "混合型", 5000),
        ("zq", "债券型", 3000),
    ]
    
    for ft, name, limit in types:
        print(f"\n📊 扫描 {name}...")
        page = 1
        count = 0
        while count < limit:
            try:
                funds, total = fetch(ft=ft, pn=500, pi=page)
                if not funds:
                    break
                all_funds.extend(funds)
                count += len(funds)
                print(f"   第{page}页: {len(funds)}只 (累计{count})")
                if len(funds) < 500:
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"   ❌ 页{page}: {e}")
                break
    
    # 去重
    seen = set()
    unique = []
    for f in all_funds:
        if f["code"] not in seen:
            seen.add(f["code"])
            unique.append(f)
    all_funds = unique
    print(f"\n📋 总计 {len(all_funds)} 只基金")
    
    # 过滤: 近1年 > 15%
    good = [f for f in all_funds if f["ret_1y"] and f["ret_1y"] > 15]
    print(f"✅ 近1年>15%: {len(good)} 只")
    
    # 计算稳定分
    for f in good:
        f["stab"] = stability(f)
    good = [f for f in good if f["stab"] is not None]
    good.sort(key=lambda x: x["stab"], reverse=True)
    
    # TOP 30
    print(f"\n{'='*110}")
    print(f"🏆 稳定收益 TOP 30 (扫描 {len(all_funds)} 只, 合格 {len(good)} 只)")
    print(f"{'='*110}")
    print(f"{'#':>3} {'代码':>8} {'名称':<30} {'稳定分':>6} {'近1周':>7} {'近1月':>7} {'近3月':>7} {'近6月':>7} {'近1年':>7} {'近2年':>7}")
    print("-" * 110)
    
    for i, f in enumerate(good[:30], 1):
        r2y = f"{f['ret_2y']:.1f}%" if f.get('ret_2y') else "   N/A"
        print(f"{i:>3} {f['code']:>8} {f['name']:<30} {f['stab']:>6.1f} "
              f"{f.get('ret_1w',0):>6.1f}% {f.get('ret_1m',0):>6.1f}% "
              f"{f.get('ret_3m',0):>6.1f}% {f.get('ret_6m',0):>6.1f}% "
              f"{f['ret_1y']:>6.1f}% {r2y:>7}")
    
    # 分段: 高/中/稳
    tier_high = sorted([f for f in good if f["ret_1y"] > 50], key=lambda x: x["stab"], reverse=True)
    tier_mid = sorted([f for f in good if 30 < f["ret_1y"] <= 50], key=lambda x: x["stab"], reverse=True)
    tier_low = sorted([f for f in good if 15 < f["ret_1y"] <= 30], key=lambda x: x["stab"], reverse=True)
    
    print(f"\n📊 分段统计:")
    print(f"   高收益(>50%): {len(tier_high)}只 | 中收益(30-50%): {len(tier_mid)}只 | 稳健(15-30%): {len(tier_low)}只")
    
    # 每段TOP5
    for label, tier in [("高收益TOP5", tier_high), ("中收益TOP5", tier_mid), ("稳健TOP5", tier_low)]:
        if not tier:
            continue
        print(f"\n   {label}:")
        for f in tier[:5]:
            r2y = f"{f['ret_2y']:.1f}%" if f.get('ret_2y') else "N/A"
            print(f"     {f['code']} {f['name']:<28} 稳定分{f['stab']:.1f} 近1月{f.get('ret_1m',0):.1f}% 近1年{f['ret_1y']:.1f}% 近2年{r2y}")
    
    # 推荐组合
    print(f"\n{'='*90}")
    print("🎯 推荐组合 (全市场扫描版)")
    print(f"{'='*90}")
    
    picks = []
    if tier_low:
        picks.append(("底仓", 35, tier_low[0]))
    if tier_mid:
        picks.append(("核心", 25, tier_mid[0]))
    if tier_high:
        picks.append(("弹性", 20, tier_high[0]))
    if tier_low and len(tier_low) > 1:
        picks.append(("防守", 15, tier_low[1]))
    elif tier_mid and len(tier_mid) > 1:
        picks.append(("防守", 15, tier_mid[1]))
    if tier_high and len(tier_high) > 1:
        picks.append(("卫星", 5, tier_high[1]))
    
    for role, pct, f in picks:
        w = 1000 * pct // 100
        r2y = f"{f['ret_2y']:.1f}%" if f.get('ret_2y') else "N/A"
        print(f"  {role} {pct}% | {f['code']} {f['name']:<30} | 每周{w}元 | 稳定分{f['stab']:.1f} | 近1年{f['ret_1y']:.1f}% | 近2年{r2y}")
    
    # 保存
    out = {
        "scan_time": datetime.now().isoformat(),
        "total": len(all_funds), "qualified": len(good),
        "top30": [{"rank": i+1, "code": f["code"], "name": f["name"], "stab": f["stab"],
                    "ret_1m": f.get("ret_1m"), "ret_3m": f.get("ret_3m"),
                    "ret_6m": f.get("ret_6m"), "ret_1y": f["ret_1y"], "ret_2y": f.get("ret_2y")}
                   for i, f in enumerate(good[:30])],
        "picks": [{"role": r, "pct": p, "code": f["code"], "name": f["name"], "stab": f["stab"],
                    "ret_1y": f["ret_1y"], "ret_2y": f.get("ret_2y")}
                   for r, p, f in picks],
    }
    with open("D:/hermes/seq-tmp/data/fund_full_scan.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\n💾 保存: data/fund_full_scan.json")

if __name__ == "__main__":
    main()
