"""Sequoia-X AI 综合选股系统 V2 - ML预测 + 回测 + 综合报告（仅推送一次钉钉）。"""
import sys
import argparse
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
from sequoia_x.analysis.ml_predictor import MLPredictor
from sequoia_x.analysis.scorer import ComprehensiveScorer
from sequoia_x.analysis.backtest import run_multi_strategy_backtest


def main():
    parser = argparse.ArgumentParser(description="Sequoia-X AI 综合选股系统")
    parser.add_argument("--backtest", action="store_true", help="运行历史回测")
    parser.add_argument("--train-ml", action="store_true", help="训练ML模型")
    parser.add_argument("--days", type=int, default=180, help="回测天数（默认180天）")
    args = parser.parse_args()

    settings = get_settings()
    logger = get_logger(__name__)
    engine = DataEngine(settings)

    # ================================================================
    # 回测模式
    # ================================================================
    if args.backtest:
        logger.info("=" * 60)
        logger.info(f"回测模式：过去 {args.days} 天")
        logger.info("=" * 60)

        strategies = [
            MaVolumeStrategy(engine=engine, settings=settings),
            TurtleTradeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
            LimitUpShakeoutStrategy(engine=engine, settings=settings),
            UptrendLimitDownStrategy(engine=engine, settings=settings),
            RpsBreakoutStrategy(engine=engine, settings=settings),
        ]

        results = run_multi_strategy_backtest(
            engine=engine,
            strategies=strategies,
            lookback_days=args.days,
            holding_days=10,
            step_days=5,
        )

        # 推送回测报告
        notifier = DingTalkNotifier()
        notifier.send_backtest_report(results)
        return

    # ================================================================
    # 训练 ML 模型
    # ================================================================
    if args.train_ml:
        logger.info("训练 ML 模型...")
        symbols = engine.get_local_symbols()
        all_data = []
        for code in symbols:
            try:
                df = engine.get_ohlcv(code)
                if df is not None and len(df) >= 100:
                    all_data.append(df)
            except Exception:
                pass

        ml = MLPredictor()
        accuracy = ml.train(all_data)
        logger.info(f"ML 模型训练完成，准确率: {accuracy:.2%}")
        return

    # ================================================================
    # 日常选股模式（只推送一次综合报告）
    # ================================================================
    notifier = DingTalkNotifier()
    logger = get_logger(__name__)

    # ── 阶段 1：技术面策略选股 ──
    logger.info("=" * 60)
    logger.info("阶段 1：技术面策略选股")
    logger.info("=" * 60)

    strategy_list = [
        ("MaVolumeStrategy", MaVolumeStrategy(engine=engine, settings=settings)),
        ("TurtleTradeStrategy", TurtleTradeStrategy(engine=engine, settings=settings)),
        ("HighTightFlagStrategy", HighTightFlagStrategy(engine=engine, settings=settings)),
        ("LimitUpShakeoutStrategy", LimitUpShakeoutStrategy(engine=engine, settings=settings)),
        ("UptrendLimitDownStrategy", UptrendLimitDownStrategy(engine=engine, settings=settings)),
        ("RpsBreakoutStrategy", RpsBreakoutStrategy(engine=engine, settings=settings)),
        ("PrivatePlacementStrategy", PrivatePlacementStrategy(engine=engine, settings=settings)),
    ]

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

    # 技术面评分
    for code, strats in all_candidates.items():
        base = 50 + len(strats) * 15
        if len(strats) >= 3:
            base += 20
        technical_scores[code] = min(100, base)

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

    # ── 阶段 2：AI 多维度分析 ──
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
                vol_5 = df["volume"].iloc[-5:].mean()
                vol_20 = df["volume"].iloc[-20:].mean()
                ratio = vol_5 / (vol_20 + 1e-10)
                capital_scores[code] = min(100, max(0, 30 + ratio * 35))
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

    # 注入 ML 预测结果到评分
    for r in ratings:
        ml_pred = ml_predictions.get(r.code)
        if ml_pred:
            # ML 预测作为额外加权
            ml_bonus = (ml_pred.bull_prob - 50) / 50 * 10  # -10 ~ +10
            r.total_score += ml_bonus
            r.tags.append(f"ML:{ml_pred.bull_prob:.0f}%")

    # 重新排序
    ratings.sort(key=lambda r: r.total_score, reverse=True)
    for i, r in enumerate(ratings):
        r.rank = i + 1

    # 打印 TOP10
    logger.info("")
    logger.info("TOP10 综合排名：")
    for r in ratings[:10]:
        logger.info(
            f"  #{r.rank} {r.code} {r.name:8s} "
            f"综合={r.total_score:5.1f} "
            f"技术={r.technical_score:.0f} 基本面={r.fundamental_score:.0f} "
            f"舆情={r.sentiment_score:.0f} 事件={r.event_score:.0f} "
            f"资金={r.capital_score:.0f} "
            f"{' '.join(r.tags)}"
        )

    # ── 阶段 4：只推送一次综合报告 ──
    logger.info("=" * 60)
    logger.info("阶段 4：推送综合报告（唯一钉钉消息）")
    logger.info("=" * 60)

    notifier.send_comprehensive_report(ratings, top_n=15)

    logger.info("AI 综合选股完成")


if __name__ == "__main__":
    main()
