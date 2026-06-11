"""Sequoia-X AI 综合选股系统 - 跳过数据同步，直接跑策略 + AI 分析 + 钉钉推送。"""
import sys
from dotenv import load_dotenv
load_dotenv()

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.dingtalk import DingTalkNotifier

# 策略
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy

# AI 分析
from sequoia_x.analysis.fundamental import FundamentalAnalyzer
from sequoia_x.analysis.sentiment import SentimentAnalyzer
from sequoia_x.analysis.event import EventAnalyzer
from sequoia_x.analysis.predictor import StockPredictor
from sequoia_x.analysis.scorer import ComprehensiveScorer


def main():
    settings = get_settings()
    logger = get_logger(__name__)
    engine = DataEngine(settings)
    notifier = DingTalkNotifier()

    # ============================================================
    # 阶段 1：运行技术面策略，收集候选股票
    # ============================================================
    logger.info("=" * 60)
    logger.info("阶段 1：技术面策略选股")
    logger.info("=" * 60)

    strategies = [
        ("MaVolumeStrategy", MaVolumeStrategy(engine=engine, settings=settings)),
        ("TurtleTradeStrategy", TurtleTradeStrategy(engine=engine, settings=settings)),
        ("HighTightFlagStrategy", HighTightFlagStrategy(engine=engine, settings=settings)),
        ("LimitUpShakeoutStrategy", LimitUpShakeoutStrategy(engine=engine, settings=settings)),
        ("UptrendLimitDownStrategy", UptrendLimitDownStrategy(engine=engine, settings=settings)),
        ("RpsBreakoutStrategy", RpsBreakoutStrategy(engine=engine, settings=settings)),
        ("PrivatePlacementStrategy", PrivatePlacementStrategy(engine=engine, settings=settings)),
    ]

    # 收集所有候选股 + 每只股命中了哪些策略
    all_candidates: dict[str, list[str]] = {}   # {code: [策略名列表]}
    strategy_reasons: dict[str, dict[str, str]] = {}  # {策略名: {code: reason}}
    technical_scores: dict[str, float] = {}

    for name, strategy in strategies:
        logger.info(f"执行策略：{name}")
        try:
            result = strategy.run()
            if isinstance(result, tuple):
                selected, reasons = result
                strategy_reasons[name] = reasons
            else:
                selected = result
                reasons = None

            logger.info(f"{name} 选出 {len(selected)} 只")

            # 推送单策略结果
            notifier.send(
                symbols=selected,
                strategy_name=name,
                webhook_key=getattr(strategy, 'webhook_key', 'default'),
                reasons=reasons,
            )

            # 收集候选
            for code in selected:
                if code not in all_candidates:
                    all_candidates[code] = []
                all_candidates[code].append(name)

        except Exception as e:
            logger.error(f"{name} 执行失败: {e}")

    # 技术面评分：命中策略越多分越高
    max_strategies = max((len(v) for v in all_candidates.values()), default=1)
    for code, strats in all_candidates.items():
        # 基础分 50，每命中一个策略 +15，多策略共振额外加分
        base = 50 + len(strats) * 15
        if len(strats) >= 3:
            base += 20  # 三策略共振加 bonus
        technical_scores[code] = min(100, base)

    # 合并所有选股理由
    all_reasons: dict[str, str] = {}
    for strat_name, reasons in strategy_reasons.items():
        for code, reason in reasons.items():
            if code not in all_reasons:
                all_reasons[code] = reason

    candidates = list(all_candidates.keys())
    logger.info(f"共 {len(candidates)} 只候选股票进入 AI 分析")

    if not candidates:
        logger.info("无候选股票，退出")
        return

    # ============================================================
    # 阶段 2：AI 多维度分析
    # ============================================================
    logger.info("=" * 60)
    logger.info("阶段 2：AI 多维度分析")
    logger.info("=" * 60)

    # 2.1 基本面分析
    logger.info("基本面分析中...")
    fundamental_analyzer = FundamentalAnalyzer()
    fundamental_scores = fundamental_analyzer.analyze(candidates)
    logger.info(f"基本面分析完成：{len(fundamental_scores)} 只")

    # 2.2 舆情分析
    logger.info("舆情分析中...")
    sentiment_analyzer = SentimentAnalyzer()
    sentiment_scores = sentiment_analyzer.analyze(candidates)
    logger.info(f"舆情分析完成：{len(sentiment_scores)} 只")

    # 2.3 事件解读
    logger.info("事件解读中...")
    event_analyzer = EventAnalyzer()
    event_scores = event_analyzer.analyze(candidates)
    logger.info(f"事件解读完成：{len(event_scores)} 只")

    # 2.4 资金面评分（基于成交量变化）
    logger.info("资金面分析中...")
    capital_scores: dict[str, float] = {}
    for code in candidates:
        try:
            df = engine.get_ohlcv(code)
            if df is not None and len(df) >= 20:
                vol_5 = df["volume"].iloc[-5:].mean()
                vol_20 = df["volume"].iloc[-20:].mean()
                if vol_20 > 0:
                    ratio = vol_5 / vol_20
                    if ratio > 2.0:
                        capital_scores[code] = 90
                    elif ratio > 1.5:
                        capital_scores[code] = 75
                    elif ratio > 1.0:
                        capital_scores[code] = 60
                    elif ratio > 0.5:
                        capital_scores[code] = 40
                    else:
                        capital_scores[code] = 25
                else:
                    capital_scores[code] = 50
            else:
                capital_scores[code] = 50
        except Exception:
            capital_scores[code] = 50

    logger.info("资金面分析完成")

    # ============================================================
    # 阶段 3：综合评分 + 排名
    # ============================================================
    logger.info("=" * 60)
    logger.info("阶段 3：综合评分与排名")
    logger.info("=" * 60)

    scorer = ComprehensiveScorer()
    ratings = scorer.score(
        codes=candidates,
        strategy_hits=all_candidates,
        technical_scores=technical_scores,
        fundamental_scores=fundamental_scores,
        sentiment_scores=sentiment_scores,
        event_scores=event_scores,
        capital_scores=capital_scores,
    )

    # 打印 TOP10
    logger.info("")
    logger.info("TOP10 综合排名：")
    logger.info("-" * 80)
    for r in ratings[:10]:
        tags_str = " ".join(r.tags) if r.tags else ""
        logger.info(
            f"  #{r.rank} {r.code} {r.name:8s} "
            f"综合={r.total_score:5.1f} "
            f"技术={r.technical_score:.0f} "
            f"基本面={r.fundamental_score:.0f} "
            f"舆情={r.sentiment_score:.0f} "
            f"事件={r.event_score:.0f} "
            f"资金={r.capital_score:.0f} "
            f"{tags_str}"
        )

    # ============================================================
    # 阶段 4：钉钉推送综合报告
    # ============================================================
    logger.info("=" * 60)
    logger.info("阶段 4：推送综合报告")
    logger.info("=" * 60)

    notifier.send_comprehensive_report(ratings, top_n=15)

    logger.info("AI 综合选股完成")


if __name__ == "__main__":
    main()
