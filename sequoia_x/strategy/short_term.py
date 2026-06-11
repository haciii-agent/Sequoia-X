"""短线策略集合：专为 3-5 天持仓优化的选股策略。"""

import numpy as np
import pandas as pd
from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)


class ShortTermMomentumStrategy(BaseStrategy):
    """短线动量策略：3日强动量 + 放量突破 + RSI 未超买。

    核心逻辑：
    - 3日涨幅 5-15%（有动力但未透支）
    - 今日放量（量比 > 1.5）
    - RSI(6) 在 50-80 区间（强势但未超买）
    - 收盘价站上 5 日均线
    - 近 5 日波动率适中（不是横盘也不是暴涨暴跌）
    """
    webhook_key: str = "short_momentum"
    _MIN_BARS: int = 30

    def run(self) -> tuple[list[str], dict[str, str]]:
        symbols = self.engine.get_local_symbols()
        selected, reasons = [], {}

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                close = df["close"].values
                volume = df["volume"].values
                high = df["high"].values
                low = df["low"].values

                # 3日涨幅
                ret3 = close[-1] / close[-4] - 1 if len(close) >= 4 else 0
                # 5日涨幅
                ret5 = close[-1] / close[-6] - 1 if len(close) >= 6 else 0
                # 量比
                vol_ratio = volume[-1] / (np.mean(volume[-5:]) + 1e-10)
                # RSI(6)
                deltas = np.diff(close[-7:])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses) + 1e-10
                rsi6 = 100 - 100 / (1 + avg_gain / avg_loss)
                # MA5
                ma5 = np.mean(close[-5:])
                # 波动率
                vol5 = np.std(np.diff(close[-6:]) / close[-6:-1]) if len(close) >= 6 else 0

                # 条件
                cond_ret = 0.05 <= ret3 <= 0.20  # 3日涨5%-20%
                cond_vol = vol_ratio > 1.3        # 放量
                cond_rsi = 50 < rsi6 < 80         # RSI 强势未超买
                cond_ma = close[-1] > ma5         # 站上 MA5
                cond_volatility = 0.01 < vol5 < 0.06  # 波动适中

                if cond_ret and cond_vol and cond_rsi and cond_ma and cond_volatility:
                    selected.append(symbol)
                    reasons[symbol] = (
                        f"3日涨{ret3*100:.1f}%，量比{vol_ratio:.1f}，"
                        f"RSI6={rsi6:.0f}，站上MA5"
                    )

            except Exception as e:
                logger.debug(f"[{symbol}] 短线动量策略失败: {e}")

        logger.info(f"ShortTermMomentumStrategy 选出 {len(selected)} 只")
        return selected, reasons


class VolumeBreakoutStrategy(BaseStrategy):
    """放量突破策略：突破近 N 日高点 + 成交量暴增。

    核心逻辑：
    - 突破 10 日或 20 日最高价
    - 今日成交量是近 5 日均量的 2 倍以上
    - 涨幅 3%-10%（不能涨停，涨停第二天大概率高开低走）
    - 不是连续大涨后的放量（避免高位出货）
    """
    webhook_key: str = "vol_breakout"
    _MIN_BARS: int = 30

    def run(self) -> tuple[list[str], dict[str, str]]:
        symbols = self.engine.get_local_symbols()
        selected, reasons = [], {}

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                close = df["close"].values
                volume = df["volume"].values
                high = df["high"].values

                # 今日涨幅
                daily_ret = close[-1] / close[-2] - 1 if len(close) >= 2 else 0
                # 突破 10/20 日高点
                high10 = np.max(high[-11:-1]) if len(high) >= 11 else 0
                high20 = np.max(high[-21:-1]) if len(high) >= 21 else 0
                # 量比
                vol_ratio = volume[-1] / (np.mean(volume[-5:]) + 1e-10)
                # 近 5 日涨幅（排除连续大涨）
                ret5 = close[-1] / close[-6] - 1 if len(close) >= 6 else 0

                cond_break = close[-1] > high10  # 突破 10 日高点
                cond_vol = vol_ratio > 2.0        # 量比 > 2
                cond_ret = 0.03 <= daily_ret <= 0.10  # 涨 3%-10%
                cond_not_hot = ret5 < 0.20        # 近 5 日没涨太多

                if cond_break and cond_vol and cond_ret and cond_not_hot:
                    selected.append(symbol)
                    reasons[symbol] = (
                        f"突破{10}日高点，量比{vol_ratio:.1f}，"
                        f"今日涨{daily_ret*100:.1f}%"
                    )

            except Exception as e:
                logger.debug(f"[{symbol}] 放量突破策略失败: {e}")

        logger.info(f"VolumeBreakoutStrategy 选出 {len(selected)} 只")
        return selected, reasons


class GapUpFollowStrategy(BaseStrategy):
    """跳空高开跟随策略：跳空高开 + 回踩不补缺口 + 缩量整理。

    核心逻辑：
    - 近 5 日内有跳空高开（开盘价 > 前日最高价）
    - 之后回踩但不补缺口
    - 今日缩量（整理完成的信号）
    - 收盘价在缺口上方
    """
    webhook_key: str = "gap_up"
    _MIN_BARS: int = 30

    def run(self) -> tuple[list[str], dict[str, str]]:
        symbols = self.engine.get_local_symbols()
        selected, reasons = [], {}

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                close = df["close"].values
                open_ = df["open"].values
                high = df["high"].values
                low = df["low"].values
                volume = df["volume"].values

                # 检查近 5 日内是否有跳空高开
                gap_found = False
                gap_low = 0
                gap_day = -1

                for i in range(-5, -1):
                    if abs(i) > len(close):
                        continue
                    prev_high = high[i - 1]
                    curr_open = open_[i]
                    if curr_open > prev_high * 1.01:  # 跳空 1% 以上
                        gap_found = True
                        gap_low = prev_high  # 缺口下沿
                        gap_day = i
                        break

                if not gap_found:
                    continue

                # 回踩不补缺口
                low_after_gap = np.min(low[gap_day:])
                gap_intact = low_after_gap > gap_low

                # 今日缩量
                vol_ratio = volume[-1] / (np.mean(volume[-5:]) + 1e-10)

                # 收盘价在缺口上方
                above_gap = close[-1] > gap_low * 1.01

                if gap_intact and above_gap and vol_ratio < 0.8:
                    selected.append(symbol)
                    gap_pct = (open_[gap_day] / gap_low - 1) * 100
                    reasons[symbol] = (
                        f"跳空{gap_pct:.1f}%缺口未补，缩量整理中"
                    )

            except Exception as e:
                logger.debug(f"[{symbol}] 跳空策略失败: {e}")

        logger.info(f"GapUpFollowStrategy 选出 {len(selected)} 只")
        return selected, reasons


class ConsecutiveRedStrategy(BaseStrategy):
    """连阴反包策略：连续下跌后出现大阳线反包。

    核心逻辑：
    - 连续 3-5 天阴线（收盘 < 开盘）
    - 今日出现大阳线（涨幅 > 3%）
    - 今日成交量放大（量比 > 1.5）
    - 今日收盘价超过前 3 日最高价（反包）
    - 不是在下降趋势的高位（用 20 日位置过滤）
    """
    webhook_key: str = "red_cover"
    _MIN_BARS: int = 30

    def run(self) -> tuple[list[str], dict[str, str]]:
        symbols = self.engine.get_local_symbols()
        selected, reasons = [], {}

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                close = df["close"].values
                open_ = df["open"].values
                high = df["high"].values
                volume = df["volume"].values

                # 今日涨幅
                daily_ret = close[-1] / close[-2] - 1 if len(close) >= 2 else 0

                # 统计连续阴线
                red_count = 0
                for i in range(-2, -7, -1):
                    if abs(i) > len(close):
                        break
                    if close[i] < open_[i]:
                        red_count += 1
                    else:
                        break

                # 今日大阳
                is_big_green = daily_ret > 0.03 and close[-1] > open_[-1]

                # 量比
                vol_ratio = volume[-1] / (np.mean(volume[-5:]) + 1e-10)

                # 反包：今日收盘 > 前 3 日最高
                high3 = np.max(high[-4:-1]) if len(high) >= 4 else 0
                is_cover = close[-1] > high3

                # 位置过滤：不在 20 日高位
                pos20 = (close[-1] - np.min(low[-20:])) / (np.max(high[-20:]) - np.min(low[-20:]) + 1e-10) if len(close) >= 20 else 0.5
                not_high = pos20 < 0.7

                if red_count >= 3 and is_big_green and vol_ratio > 1.3 and is_cover and not_high:
                    selected.append(symbol)
                    reasons[symbol] = (
                        f"连跌{red_count}天后大阳反包，涨{daily_ret*100:.1f}%，量比{vol_ratio:.1f}"
                    )

            except Exception as e:
                logger.debug(f"[{symbol}] 连阴反包策略失败: {e}")

        logger.info(f"ConsecutiveRedStrategy 选出 {len(selected)} 只")
        return selected, reasons


class ShortTermPullbackStrategy(BaseStrategy):
    """短线回踩支撑策略：上升趋势中回踩均线支撑。

    核心逻辑：
    - 20 日涨幅 > 10%（上升趋势）
    - 近 3 日回调（跌 3-8%，不能太多）
    - 今日触及 10 日或 20 日均线后企稳
    - 今日缩量（卖压减弱）
    - RSI(14) 回落到 40-55 区间（超卖反弹区）
    """
    webhook_key: str = "pullback"
    _MIN_BARS: int = 30

    def run(self) -> tuple[list[str], dict[str, str]]:
        symbols = self.engine.get_local_symbols()
        selected, reasons = [], {}

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                close = df["close"].values
                volume = df["volume"].values
                low = df["low"].values

                # 20 日涨幅
                ret20 = close[-1] / close[-21] - 1 if len(close) >= 21 else 0
                # 近 3 日回调
                ret3 = close[-1] / close[-4] - 1 if len(close) >= 4 else 0
                # MA10, MA20
                ma10 = np.mean(close[-10:])
                ma20 = np.mean(close[-20:])
                # 今日最低触及均线
                touch_ma = low[-1] <= ma10 * 1.01 or low[-1] <= ma20 * 1.01
                # 收盘站上均线
                above_ma = close[-1] > ma10 * 0.99
                # 缩量
                vol_ratio = volume[-1] / (np.mean(volume[-5:]) + 1e-10)
                # RSI(14)
                deltas = np.diff(close[-15:])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                rsi14 = 100 - 100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10))

                cond_trend = ret20 > 0.10
                cond_pullback = -0.08 < ret3 < -0.02
                cond_support = touch_ma and above_ma
                cond_vol = vol_ratio < 0.9
                cond_rsi = 35 < rsi14 < 55

                if cond_trend and cond_pullback and cond_support and cond_vol and cond_rsi:
                    selected.append(symbol)
                    reasons[symbol] = (
                        f"20日涨{ret20*100:.1f}%回踩MA10支撑，3日跌{ret3*100:.1f}%，RSI={rsi14:.0f}"
                    )

            except Exception as e:
                logger.debug(f"[{symbol}] 回踩策略失败: {e}")

        logger.info(f"ShortTermPullbackStrategy 选出 {len(selected)} 只")
        return selected, reasons
