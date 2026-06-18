"""全市场基金深度筛选 - 多因子评分模型。"""
import akshare as ak
import pandas as pd
import numpy as np
import warnings
import json
import requests
from datetime import date

warnings.filterwarnings('ignore')

print("=" * 60)
print("全市场基金深度筛选")
print("=" * 60)

# ============================================================
# 第1步：拉取全市场基金数据
# ============================================================
print("\n[1/5] 拉取全市场基金排行...")
df = ak.fund_open_fund_rank_em(symbol='全部')
print(f"  获取到 {len(df)} 只基金")

# 清洗
num_cols = ['单位净值', '累计净值', '日增长率', '近1周', '近1月', '近3月', '近6月', '近1年', '近2年', '近3年', '今年来']
for col in num_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

# ============================================================
# 第2步：初步筛选（排除不合格的）
# ============================================================
print("\n[2/5] 初步筛选...")

# 排除条件
df = df[df['近1年'].notna()]          # 必须有近1年数据
df = df[df['近6月'].notna()]          # 必须有近6月数据
df = df[df['近1月'].notna()]          # 必须有近1月数据
df = df[df['今年来'].notna()]         # 必须有今年数据
df = df[df['近1年'] > 0]             # 近1年必须正收益
df = df[df['近6月'] > 0]             # 近6月必须正收益
df = df[df['近1月'] > -20]           # 近1月回撤不超过20%

# 排除C份额（定投选A份额更划算）
df = df[~df['基金简称'].str.contains('C$|C类', na=False, regex=True)]

# 排除ETF（场内交易，不适合定投）
df = df[~df['基金简称'].str.contains('ETF$', na=False, regex=True)]

print(f"  初筛后: {len(df)} 只")

# ============================================================
# 第3步：多因子评分
# ============================================================
print("\n[3/5] 多因子评分...")

def calc_score(row):
    """多因子评分（满分100）。"""
    score = 0
    
    # 1. 收益因子（40分）
    #    近1年收益（20分）
    y1 = row['近1年']
    if y1 >= 100:
        score += 20
    elif y1 >= 50:
        score += 15 + (y1 - 50) / 50 * 5
    elif y1 >= 20:
        score += 10 + (y1 - 20) / 30 * 5
    elif y1 >= 10:
        score += 5 + (y1 - 10) / 10 * 5
    else:
        score += y1 / 10 * 5
    
    #    近2年收益（10分，如果有的话）
    y2 = row.get('近2年', np.nan)
    if pd.notna(y2):
        if y2 >= 80:
            score += 10
        elif y2 >= 30:
            score += 5 + (y2 - 30) / 50 * 5
        elif y2 >= 10:
            score += (y2 - 10) / 20 * 5
    
    #    近3年收益（10分，如果有的话）
    y3 = row.get('近3年', np.nan)
    if pd.notna(y3):
        if y3 >= 60:
            score += 10
        elif y3 >= 20:
            score += 5 + (y3 - 20) / 40 * 5
        elif y3 >= 0:
            score += y3 / 20 * 5
    
    # 2. 风险因子（30分）- 用近期回撤衡量
    #    近1月表现（15分）- 跌得少得分高
    m1 = row['近1月']
    if m1 >= 5:
        score += 15
    elif m1 >= 0:
        score += 10 + m1 / 5 * 5
    elif m1 >= -5:
        score += 5 + (m1 + 5) / 5 * 5
    elif m1 >= -10:
        score += (m1 + 10) / 5 * 5
    else:
        score += 0
    
    #    近6月稳定性（15分）
    m6 = row['近6月']
    if m6 >= 30:
        score += 15
    elif m6 >= 15:
        score += 10 + (m6 - 15) / 15 * 5
    elif m6 >= 5:
        score += 5 + (m6 - 5) / 10 * 5
    else:
        score += m6 / 5 * 5
    
    # 3. 一致性因子（20分）- 各时段都好才给高分
    consistency = 0
    if row['近1月'] > 0:
        consistency += 5
    if row['近3月'] > 0:
        consistency += 5
    if row['近6月'] > 10:
        consistency += 5
    if row['近1年'] > 20:
        consistency += 5
    score += consistency
    
    # 4. 动量因子（10分）- 近期趋势
    if row['近1月'] > 0 and row['近3月'] > 0:
        score += 5  # 短期趋势向上
    if row['近6月'] > row['近1年'] / 2:
        score += 5  # 近期加速
    elif row['近1月'] > row['近3月'] / 3:
        score += 3  # 近期回暖
    
    return round(score, 1)

df['score'] = df.apply(calc_score, axis=1)

# ============================================================
# 第4步：分类 + 排名
# ============================================================
print("\n[4/5] 分类排名...")

# 按基金名称分类
categories = {
    '沪深300/大盘': df[df['基金简称'].str.contains('沪深300|300|大盘|蓝筹|价值', na=False)],
    '中证500/中小盘': df[df['基金简称'].str.contains('中证500|500|中小盘|中小', na=False)],
    '科技/半导体': df[df['基金简称'].str.contains('科技|半导体|芯片|电子|信息|数字经济|人工智能|AI|计算机|软件', na=False)],
    '医药/医疗': df[df['基金简称'].str.contains('医药|医疗|健康|生物|创新药|中药', na=False)],
    '新能源': df[df['基金简称'].str.contains('新能源|光伏|锂电|碳中和|绿色|储能|电力', na=False)],
    '消费': df[df['基金简称'].str.contains('消费|白酒|食品|饮料|内需|家电', na=False)],
    '金融/银行': df[df['基金简称'].str.contains('金融|银行|证券|保险|非银|地产', na=False)],
    '军工': df[df['基金简称'].str.contains('军工|国防|航天', na=False)],
    '科创/创业板': df[df['基金简称'].str.contains('科创|创业|双创', na=False)],
    '港股/QDII': df[df['基金简称'].str.contains('港股|恒生|QDII|海外|全球|纳斯达克', na=False)],
    '红利/价值': df[df['基金简称'].str.contains('红利|股息|高分红|价值|央企', na=False)],
    '债券/固收': df[df['基金简称'].str.contains('债券|纯债|信用债|可转债|固收', na=False)],
}

results = {}
for cat, sub_df in categories.items():
    if len(sub_df) == 0:
        continue
    top = sub_df.nlargest(5, 'score')
    results[cat] = top
    print(f"\n--- {cat} ({len(sub_df)}只) TOP5 ---")
    for _, r in top.iterrows():
        print(f"  {r['基金代码']:8s} {r['基金简称'][:25]:25s} 评分:{r['score']:5.1f}  近1年:{r['近1年']:+7.1f}%  近6月:{r['近6月']:+7.1f}%  近1月:{r['近1月']:+7.1f}%")

# ============================================================
# 第5步：最终推荐（稳中求进）
# ============================================================
print("\n[5/5] 生成最终推荐...")

# 稳中求进策略：核心60% + 弹性30% + 防守10%
print("\n" + "=" * 60)
print("最终推荐：稳中求进定投组合")
print("=" * 60)

# 从每个类别选最优
picks = []

# 底仓：沪深300增强
if '沪深300/大盘' in results:
    r = results['沪深300/大盘'].iloc[0]
    picks.append(('底仓', 30, r))

# 核心：科创/成长
if '科创/创业板' in results:
    r = results['科创/创业板'].iloc[0]
    picks.append(('核心', 25, r))
elif '科技/半导体' in results:
    r = results['科技/半导体'].iloc[0]
    picks.append(('核心', 25, r))

# 弹性：中证500
if '中证500/中小盘' in results:
    r = results['中证500/中小盘'].iloc[0]
    picks.append(('弹性', 20, r))

# 弹性2：新能源或港股
if '新能源' in results:
    r = results['新能源'].iloc[0]
    picks.append(('弹性', 15, r))
elif '港股/QDII' in results:
    r = results['港股/QDII'].iloc[0]
    picks.append(('弹性', 15, r))

# 防守：债券
if '债券/固收' in results:
    r = results['债券/固收'].iloc[0]
    picks.append(('防守', 10, r))

print(f"\n{'角色':6s} {'配比':>4s} {'代码':8s} {'名称':25s} {'评分':>5s} {'近1年':>8s} {'近2年':>8s} {'近6月':>8s} {'近1月':>8s}")
print("-" * 90)
for role, pct, r in picks:
    y2 = r.get('近2年', '-')
    if pd.notna(y2):
        y2 = f"{y2:+.1f}%"
    else:
        y2 = "-"
    print(f"{role:6s} {pct:3d}% {r['基金代码']:8s} {r['基金简称'][:25]:25s} {r['score']:5.1f} {r['近1年']:+7.1f}% {y2:>8s} {r['近6月']:+7.1f}% {r['近1月']:+7.1f}%")

# 保存结果到文件
output = []
for role, pct, r in picks:
    output.append({
        'role': role,
        'pct': pct,
        'code': r['基金代码'],
        'name': r['基金简称'],
        'score': r['score'],
        'ret_1y': r['近1年'],
        'ret_6m': r['近6月'],
        'ret_1m': r['近1月'],
    })

with open('data/fund_picks.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("\n结果已保存到 data/fund_picks.json")
print("完成！")
