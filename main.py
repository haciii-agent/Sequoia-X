"""Sequoia-X V2 主程序入口。

两种运行模式：
  python main.py                    # 日常模式：近期增量同步 + 跑策略
  python main.py --repair           # 历史补洞：分块修复落后股票
  python main.py --backfill         # 兼容旧入口，等同于 --repair
"""

import argparse
import sys
from dotenv import load_dotenv
load_dotenv()

import socket
socket.setdefaulttimeout(10.0)

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.feishu import FeishuNotifier
from sequoia_x.strategy.base import BaseStrategy
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X V2 选股系统")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="兼容旧入口：历史补洞模式",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="历史补洞模式：分块修复明显落后的股票",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="同步并发 worker 数，默认 4",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=150,
        help="每个同步分块的股票数，默认 150",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="单只股票最大重试次数，默认 3",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="日常增量只处理最近落后 N 天的股票，默认 3",
    )
    parser.add_argument(
        "--stale-before-days",
        type=int,
        default=3,
        help="历史补洞：只处理落后超过 N 天的股票，默认 3",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="本次最多处理多少个分块，默认不限",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续传，从头生成同步任务",
    )
    args = parser.parse_args()

    try:
        settings = get_settings()
        logger = get_logger(__name__)
        logger.info("Sequoia-X V2 启动")
        engine = DataEngine(settings)

        if args.backfill or args.repair:
            logger.info("进入历史补洞模式...")
            summary = engine.repair_history(
                workers=args.workers,
                chunk_size=args.chunk_size,
                max_retries=args.max_retries,
                stale_before_days=args.stale_before_days,
                resume=not args.no_resume,
                max_chunks=args.max_chunks,
            )
            logger.info(f"历史补洞完成: {summary}")
            return

        logger.info("开始近期增量同步...")
        summary = engine.sync_today_bulk(
            workers=args.workers,
            chunk_size=args.chunk_size,
            max_retries=args.max_retries,
            lookback_days=args.lookback_days,
            resume=not args.no_resume,
            max_chunks=args.max_chunks,
        )
        logger.info(f"近期增量同步完成: {summary}")

        strategies: list[BaseStrategy] = [
            MaVolumeStrategy(engine=engine, settings=settings),
            TurtleTradeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
            LimitUpShakeoutStrategy(engine=engine, settings=settings),
            UptrendLimitDownStrategy(engine=engine, settings=settings),
            RpsBreakoutStrategy(engine=engine, settings=settings),
            PrivatePlacementStrategy(engine=engine, settings=settings),
        ]

        notifier = FeishuNotifier(settings)

        for strategy in strategies:
            strategy_name = type(strategy).__name__
            logger.info(f"执行策略：{strategy_name}")

            selected: list[str] = strategy.run()
            logger.info(f"{strategy_name} 选出 {len(selected)} 只股票")

            if selected:
                notifier.send(
                    symbols=selected,
                    strategy_name=strategy_name,
                    webhook_key=strategy.webhook_key,
                )
            else:
                logger.info(f"{strategy_name} 无选股结果，跳过推送")

    except Exception:
        try:
            _logger = get_logger(__name__)
            _logger.exception("主流程发生未捕获异常，程序终止")
        except Exception:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    logger.info("Sequoia-X V2 运行完成")


if __name__ == "__main__":
    main()
