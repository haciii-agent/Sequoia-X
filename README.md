# Sequoia-X

> A 股量化选股与 AI 综合评分系统（当前主线：日线数据同步 + 多策略筛选 + 钉钉推送）

---

## 项目简介

Sequoia-X 是面向 A 股市场的本地化选股系统，核心能力包括：

- 本地 SQLite 行情库维护
- 收盘后日线增量同步
- 多策略候选股筛选
- 基本面 / 舆情 / 事件 / 资金面 / ML 综合评分
- 钉钉综合报告推送

当前数据源主链路使用 `baostock`，数据库为 `data/sequoia_v2.db`。
项目已经完成一轮全库清洗：**北交所 `920xxx` 股票已从数据库移除，不再参与同步和分析**。

---

## 当前能力总览

### 1. 长期保留的数据同步能力

项目已经收敛为适合长期维护的同步方案：

- **日常增量同步**：只补到“昨天”的最新日线，避免盘中/当日数据不稳定
- **历史补洞同步**：用于修复明显落后的股票数据
- **分块并发**：按 chunk 分批同步，降低 baostock 断连风险
- **自动重试**：单只股票失败自动重试
- **断点续传**：失败分块会写入状态文件，便于续跑
- **脏数据兼容**：允许停牌/无成交但有有效收盘价的日线入库

### 2. 选股与分析能力

#### 技术策略

当前代码里包含以下策略：

- `ShortTermMomentumStrategy`：短线动量
- `VolumeBreakoutStrategy`：放量突破
- `GapUpFollowStrategy`：跳空跟随
- `ConsecutiveRedStrategy`：连阴反包
- `ShortTermPullbackStrategy`：回踩支撑
- `MaVolumeStrategy`：均线放量
- `HighTightFlagStrategy`：高位旗形
- `RpsBreakoutStrategy`：RPS 突破
- `TurtleTradeStrategy`：海龟突破
- `LimitUpShakeoutStrategy`：涨停洗盘
- `UptrendLimitDownStrategy`：趋势跌停
- `PrivatePlacementStrategy`：定增机会

#### AI 综合分析

`run_strategy.py` 已接入以下分析模块：

- `FundamentalAnalyzer`：基本面分析
- `SentimentAnalyzer`：舆情分析
- `EventAnalyzer`：事件驱动分析
- `MLPredictor`：机器学习预测
- `ComprehensiveScorer`：综合评分器

#### 推送

- 当前主推送链路：**钉钉机器人（加签）**
- 代码中仍保留 `FeishuNotifier`，但当前主流程与实盘使用已偏向钉钉

---

## 运行模式

### 1. 日常模式

```bash
uv run python main.py
```

日常模式会：

1. 执行近期增量同步（目标补到昨天）
2. 跑策略
3. 输出/推送筛选结果

### 2. 历史补洞模式

```bash
uv run python main.py --repair
```

常用参数：

```bash
uv run python main.py --repair --workers 4 --chunk-size 120
uv run python main.py --repair --workers 4 --chunk-size 120 --max-chunks 5
uv run python main.py --repair --workers 4 --chunk-size 120 --no-resume
```

说明：

- `--workers`：并发 worker 数
- `--chunk-size`：每个分块包含多少股票
- `--max-chunks`：本次最多处理多少个分块
- `--no-resume`：忽略断点状态，从头重新生成任务

### 3. 兼容旧入口的增量同步脚本

```bash
uv run python sync_incremental.py
```

这个脚本现在已经不是旧的多线程实现，而是**兼容旧 cron 的薄封装**，内部直接调用新的 `DataEngine.sync_today_bulk()`。

### 4. AI 综合选股运行

```bash
uv run python run_strategy.py
```

### 5. ML 训练

```bash
uv run python run_strategy.py --train-ml
uv run python run_strategy.py --train-ml-cache
```

### 6. 回测

```bash
uv run python run_strategy.py --backtest --days 180
```

---

## 当前数据约束

### 数据目标日

项目当前的日常维护目标是：

- **每天同步到“昨天”的收盘数据**
- 不追求盘中/当日实时行情

### 北交所处理策略

当前仓库的数据库与同步逻辑已按你的实际交易约束调整：

- **北交所 `920xxx` 已从数据库中移除**
- **后续不同步、不分析、不参与选股**

### 数据源说明

- 主数据源：`baostock`
- 本地数据库：`data/sequoia_v2.db`
- 运行时会产生 SQLite 附属文件：`data/sequoia_v2.db-wal`、`data/sequoia_v2.db-shm`
  - 这是正常现象
  - 数据库占用期间不建议手动删除

---

## 环境要求

- Python `>=3.10`
- 推荐使用 `uv`

安装依赖：

```bash
uv sync
```

或：

```bash
pip install .
```

---

## 配置说明

复制环境变量模板：

```bash
cp .env.example .env
```

再按实际情况修改 `.env`。

当前 `Settings` 里主要用到：

- `DB_PATH`：SQLite 路径
- `START_DATE`：历史起始日
- `FEISHU_WEBHOOK_URL`：兼容旧通知逻辑的默认 webhook
- `STRATEGY_WEBHOOK_*`：策略级 webhook 映射（仍保留兼容）

注意：

- 目前主流程的综合报告推送主要走 **钉钉**
- `.env.example` 里保留了飞书相关字段，主要用于兼容旧模块

---

## 推荐定时方案

当前仓库所在环境已经有长期定时任务，推荐延续以下思路：

### 1. 交易日 15:00 后同步数据

```bash
uv run python sync_incremental.py
```

### 2. 交易日 16:00 后跑综合选股

```bash
uv run python run_strategy.py
```

如果你在 Linux / WSL / 服务器环境中手工配置，可参考：

```cron
0 15 * * 1-5 cd /path/to/Sequoia-X && uv run python sync_incremental.py >> sync.log 2>&1
0 16 * * 1-5 cd /path/to/Sequoia-X && uv run python run_strategy.py >> strategy.log 2>&1
```

Windows 本机则建议继续使用 Hermes / 任务计划程序 / 批处理脚本托管。

---

## 目录结构

```text
Sequoia-X/
├── main.py                         # 主入口：日常增量 / 历史补洞
├── sync_incremental.py             # 兼容旧 cron 的增量同步薄封装
├── run_strategy.py                 # AI 综合选股主入口
├── pyproject.toml                  # 项目依赖声明
├── .env.example                    # 环境变量模板
├── data/                           # SQLite 数据库与 ML 模型
├── scripts/
│   ├── report_sync_progress.py     # 同步进度播报脚本
│   ├── notify_sync_complete.py     # 同步完成通知脚本
│   └── fund_full_scan.py           # 基金全量扫描脚本
├── sequoia_x/
│   ├── analysis/                   # 基本面 / 舆情 / 事件 / ML / 评分 / 回测
│   ├── core/                       # 配置与日志
│   ├── data/
│   │   └── engine.py               # 数据同步与 SQLite 写入核心
│   ├── notify/
│   │   ├── dingtalk.py             # 钉钉通知
│   │   └── feishu.py               # 飞书通知（兼容保留）
│   └── strategy/                   # 各类技术策略
└── tests/                          # 测试
```

---

## 最近收敛的关键变更

最近已经完成以下重要收敛：

- 移除数据库中的北交所 `920xxx` 股票
- 同步目标统一为“昨天”，不再追当天盘中数据
- 修复指定 `symbols` 时补洞被 cutoff 误跳过的问题
- 修复停牌/无成交但有有效收盘价时无法写库的问题
- 将旧 `sync_incremental.py` 收敛为新数据引擎的兼容入口
- 增加同步进度与完成通知脚本

---

## 开发与测试

最小编译检查：

```bash
python -m compileall main.py sync_incremental.py sequoia_x/data/engine.py scripts/report_sync_progress.py scripts/notify_sync_complete.py
```

测试：

```bash
pytest tests/test_data_engine.py -q
pytest tests/ -q
```

如果当前环境没有直接安装 `pytest`，可通过 `uv` 或 dev 依赖补齐后再执行。

---

## License

MIT
