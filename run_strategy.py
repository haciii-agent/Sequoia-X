"""快速选股 - 跳过数据同步，直接用库中已有数据跑策略，钉钉推送"""
import sys
from dotenv import load_dotenv
load_dotenv()

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.dingtalk import DingTalkNotifier
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy


def main():
    settings = get_settings()
    logger = get_logger(__name__)
    engine = DataEngine(settings)

    strategies = [
        MaVolumeStrategy(engine=engine, settings=settings),
        TurtleTradeStrategy(engine=engine, settings=settings),
        HighTightFlagStrategy(engine=engine, settings=settings),
        LimitUpShakeoutStrategy(engine=engine, settings=settings),
        UptrendLimitDownStrategy(engine=engine, settings=settings),
        RpsBreakoutStrategy(engine=engine, settings=settings),
        PrivatePlacementStrategy(engine=engine, settings=settings),
    ]

    notifier = DingTalkNotifier()

    for strategy in strategies:
        name = type(strategy).__name__
        logger.info(f"执行策略：{name}")
        try:
            result = strategy.run()

            # HighTightFlagStrategy 返回 (selected, reasons)
            if isinstance(result, tuple):
                selected, reasons = result
            else:
                selected = result
                reasons = None

            logger.info(f"{name} 选出 {len(selected)} 只")
            if selected:
                logger.info(f"  结果：{selected[:20]}")

            notifier.send(
                symbols=selected,
                strategy_name=name,
                webhook_key=getattr(strategy, 'webhook_key', 'default'),
                reasons=reasons,
            )
        except Exception as e:
            logger.error(f"{name} 执行失败: {e}")

    logger.info("选股完成")


if __name__ == "__main__":
    main()
