"""增量同步脚本：兼容旧 cron，委托给新的 DataEngine 增量同步。"""

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine


logger = get_logger(__name__)


def main() -> None:
    engine = DataEngine(get_settings())
    summary = engine.sync_today_bulk(
        workers=4,
        chunk_size=150,
        max_retries=3,
        lookback_days=3,
        resume=True,
    )
    logger.info(f"增量同步完成: {summary}")


if __name__ == "__main__":
    main()
