"""Sequoia-X AI 综合选股系统 V3 - 短线优化 + ML全市场训练。"""
import sys
import argparse
from dotenv import load_dotenv
load_dotenv()

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.dingtalk import DingTalkNotifier

# 原有策略
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy

# 短线策略
from sequoia_x.strategy.short_term import (
    ShortTermMomentumStrategy,
    VolumeBreakoutStrategy,
    GapUpFollowStrategy,
    ConsecutiveRedStrategy,
    ShortTermPullbackStrategy,
)

# AI 分析
from sequoia_x.analysis.fundamental import FundamentalAnalyzer
from sequoia_x.analysis.sentiment import SentimentAnalyzer
from sequoia_x.analysis.event import EventAnalyzer
from sequoia_x.analysis.ml_predictor import MLPredictor
from sequoia_x.analysis.scorer import ComprehensiveScorer
from sequoia_x.analysis.backtest import run_multi_strategy_backtest


def main():
    parser = argparse.ArgumentParser(description="Sequoia-X AI 综合选股系统")
    parser.add_argument("--backtest", action="store_true", help="运行历史回测")
    parser.add_argument("--train-ml", action="store_true", help="训练ML模型（全市场）")
    parser.add_argument("--train-ml-cache", action="store_true", help="从缓存重新训练ML模型")
    parser.add_argument("--days", type=int, default=180, help="回测天数")
    args = parser.parse_args()

    settings = get_settings()
    logger = get_logger(__name__)
    engine = DataEngine(settings)

    # ================================================================
    # 回测模式
    # ================================================================
    if args.backtest:
        logger.info(f"回测模式：过去 {args.days} 天，短线策略")
        strategies = [
            ShortTermMomentumStrategy(engine=engine, settings=settings),
            VolumeBreakoutStrategy(engine=engine, settings=settings),
            GapUpFollowStrategy(engine=engine, settings=settings),
            ConsecutiveRedStrategy(engine=engine, settings=settings),
            ShortTermPullbackStrategy(engine=engine, settings=settings),
            MaVolumeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
        ]
        results = run_multi_strategy_backtest(
            engine=engine, strategies=strategies,
            lookback_days=args.days, holding_days=5, step_days=3,
        )
        DingTalkNotifier().send_backtest_report(results)
        return

    # ================================================================
    # ML 训练模式
    # ================================================================
    if args.train_ml or args.train_ml_cache:
        ml = MLPredictor()

        if args.train_ml_cache:
            logger.info("从缓存重新训练 ML 模型...")
            accuracy = ml.train_from_cache()
            logger.info(f"训练完成，准确率: {accuracy:.2%}")
            return

        logger.info("全市场 ML 训练...")
        symbols = engine.get_local_symbols()
        logger.info(f"加载 {len(symbols)} 只股票数据...")

        all_data = []
        for i, code in enumerate(symbols):
            try:
                df = engine.get_ohlcv(code)
                if df is not None and len(df) >= 80:
                    all_data.append(df)
            except Exception:
                pass
            if (i + 1) % 1000 == 0:
                logger.info(f"  已加载 {i+1}/{len(symbols)}...")

        logger.info(f"有效数据: {len(all_data)} 只股票")
        accuracy = ml.train(all_data, forward_days=3, threshold=0.03)
        logger.info(f"ML 模型训练完成，准确率: {accuracy:.2%}")
        return

    # ================================================================
    # 日常选股模式
    # ================================================================
    notifier = DingTalkNotifier()

    # ── 阶段 1：策略选股（短线为主） ──
    logger.info("=" * 60)
    logger.info("阶段 1：策略选股（短线优化）")
    logger.info("=" * 60)

    strategy_list = [
        # 短线策略（权重更高）
        ("ShortTermMomentumStrategy", ShortTermMomentumStrategy(engine=engine, settings=settings)),
        ("VolumeBreakoutStrategy", VolumeBreakoutStrategy(engine=engine, settings=settings)),
        ("GapUpFollowStrategy", GapUpFollowStrategy(engine=engine, settings=settings)),
        ("ConsecutiveRedStrategy", ConsecutiveRedStrategy(engine=engine, settings=settings)),
        ("ShortTermPullbackStrategy", ShortTermPullbackStrategy(engine=engine, settings=settings)),
        # 原有策略（辅助）
        ("MaVolumeStrategy", MaVolumeStrategy(engine=engine, settings=settings)),
        ("HighTightFlagStrategy", HighTightFlagStrategy(engine=engine, settings=settings)),
        ("RpsBreakoutStrategy", RpsBreakoutStrategy(engine=engine, settings=settings)),
        ("TurtleTradeStrategy", TurtleTradeStrategy(engine=engine, settings=settings)),
    ]

    # 短线策略权重
    SHORT_TERM_STRATEGIES = {
        "ShortTermMomentumStrategy", "VolumeBreakoutStrategy",
        "GapUpFollowStrategy", "ConsecutiveRedStrategy",
        "ShortTermPullbackStrategy",
    }

    all_candidates: dict[str, list[str]] = {}
    strategy_reasons: dict[str, dict[str, str]] = {}
    technical_scores: dict[str, float] = {}

    for name, strategy in strategy_list:
        logger.info(f"执行策略：{name}")
        try:
            result = strategy.run()
            if isinstance(result, tuple):
                selected, reasons = result
                strategy_reasons[name] = reasons
            else:
                selected = result

            logger.info(f"  → {len(selected)} 只")
            for code in selected:
                if code not in all_candidates:
                    all_candidates[code] = []
                all_candidates[code].append(name)
        except Exception as e:
            logger.error(f"  → 失败: {e}")

    # 技术面评分（短线策略权重更高）
    for code, strats in all_candidates.items():
        score = 50
        for s in strats:
            if s in SHORT_TERM_STRATEGIES:
                score += 18  # 短线策略 +18
            else:
                score += 12  # 原有策略 +12
        # 多策略共振
        if len(strats) >= 3:
            score += 25
        elif len(strats) >= 2:
            score += 10
        technical_scores[code] = min(100, score)

    all_reasons: dict[str, str] = {}
    for reasons in strategy_reasons.values():
        for code, reason in reasons.items():
            if code not in all_reasons:
                all_reasons[code] = reason

    candidates = list(all_candidates.keys())
    logger.info(f"共 {len(candidates)} 只候选股票")

    if not candidates:
        logger.info("无候选股票，退出")
        return

    # ── 阶段 2：AI 分析 ──
    logger.info("=" * 60)
    logger.info("阶段 2：AI 多维度分析")
    logger.info("=" * 60)

    logger.info("基本面分析...")
    fundamental_scores = FundamentalAnalyzer().analyze(candidates)

    logger.info("舆情分析...")
    sentiment_scores = SentimentAnalyzer().analyze(candidates)

    logger.info("事件解读...")
    event_scores = EventAnalyzer().analyze(candidates)

    logger.info("资金面分析...")
    capital_scores: dict[str, float] = {}
    for code in candidates:
        try:
            df = engine.get_ohlcv(code)
            if df is not None and len(df) >= 20:
                vol_3 = df["volume"].iloc[-3:].mean()
                vol_10 = df["volume"].iloc[-10:].mean()
                ratio = vol_3 / (vol_10 + 1e-10)
                capital_scores[code] = min(100, max(0, 30 + ratio * 40))
            else:
                capital_scores[code] = 50
        except Exception:
            capital_scores[code] = 50

    logger.info("ML 预测...")
    ml = MLPredictor()
    ml_predictions = ml.predict_batch(candidates, lambda code: engine.get_ohlcv(code))

    # ── 阶段 3：综合评分 ──
    logger.info("=" * 60)
    logger.info("阶段 3：综合评分")
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

    # 注入 ML 预测
    for r in ratings:
        ml_pred = ml_predictions.get(r.code)
        if ml_pred:
            ml_bonus = (ml_pred.bull_prob - 50) / 50 * 12  # -12 ~ +12
            r.total_score += ml_bonus
            r.tags.append(f"ML:{ml_pred.bull_prob:.0f}%")

    ratings.sort(key=lambda r: r.total_score, reverse=True)
    for i, r in enumerate(ratings):
        r.rank = i + 1

    # 打印 TOP10
    logger.info("")
    logger.info("TOP10 综合排名（短线优化）：")
    for r in ratings[:10]:
        strats = [s for s in r.strategies if s in SHORT_TERM_STRATEGIES]
        is_short = "⚡" if strats else "  "
        logger.info(
            f"  {is_short}#{r.rank} {r.code} {r.name:8s} "
            f"综合={r.total_score:5.1f} "
            f"技术={r.technical_score:.0f} 基本面={r.fundamental_score:.0f} "
            f"舆情={r.sentiment_score:.0f} 事件={r.event_score:.0f} "
            f"资金={r.capital_score:.0f} "
            f"{' '.join(r.tags)}"
        )

    # ── 阶段 4：推送 ──
    logger.info("=" * 60)
    logger.info("阶段 4：推送综合报告")
    logger.info("=" * 60)
    notifier.send_comprehensive_report(ratings, top_n=15)
    logger.info("AI 综合选股完成（短线优化）")


if __name__ == "__main__":
    main()
