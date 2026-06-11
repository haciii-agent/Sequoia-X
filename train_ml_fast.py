"""快速全市场 ML 训练脚本 - 直接从 SQLite 批量加载。"""
import sys
import os
import time
import sqlite3
import pandas as pd
import numpy as np

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from sequoia_x.core.logger import get_logger
from sequoia_x.analysis.ml_predictor import MLPredictor

logger = get_logger(__name__)


def load_all_data_from_db(db_path: str, min_bars: int = 80) -> list[pd.DataFrame]:
    """直接从 SQLite 批量加载所有股票数据（比逐只快 100 倍）。"""
    logger.info(f"从数据库批量加载: {db_path}")
    t0 = time.time()

    conn = sqlite3.connect(db_path)

    # 一次性加载所有数据
    df = pd.read_sql("SELECT * FROM stock_daily ORDER BY symbol, date", conn)
    conn.close()

    logger.info(f"原始数据: {len(df)} 行, {df['symbol'].nunique()} 只股票, 耗时 {time.time()-t0:.1f}s")

    # 按股票分组
    t1 = time.time()
    all_data = []
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("date").reset_index(drop=True)
        if len(group) >= min_bars:
            # 确保列名正确
            required = ["open", "high", "low", "close", "volume"]
            if all(c in group.columns for c in required):
                all_data.append(group[required].copy())

    logger.info(f"有效股票: {len(all_data)} 只, 分组耗时 {time.time()-t1:.1f}s")
    return all_data


def main():
    db_path = os.path.join(os.path.dirname(__file__), "data", "sequoia_v2.db")

    if not os.path.exists(db_path):
        logger.error(f"数据库不存在: {db_path}")
        return

    # 批量加载
    all_data = load_all_data_from_db(db_path, min_bars=80)
    logger.info(f"共 {len(all_data)} 只股票进入训练")

    # 训练
    ml = MLPredictor()
    accuracy = ml.train(all_data, forward_days=3, threshold=0.03)
    logger.info(f"ML 模型训练完成，准确率: {accuracy:.2%}")


if __name__ == "__main__":
    main()
