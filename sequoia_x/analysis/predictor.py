"""预测模块：基于历史K线数据计算技术指标，评估短期涨跌概率。"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PredictionResult:
    """预测结果。"""
    code: str
    # 技术指标
    rsi: float = 50.0           # RSI(14)
    macd_hist: float = 0.0      # MACD 柱状
    bb_position: float = 0.5    # 布林带位置 (0=下轨, 1=上轨)
    ma_trend: str = "neutral"   # 均线趋势 (bullish/bearish/neutral)
    volume_trend: str = "normal" # 量能趋势 (expanding/shrinking/normal)
    # 预测
    bull_probability: float = 50.0  # 看涨概率 0-100
    bear_probability: float = 50.0  # 看跌概率 0-100
    signal_strength: float = 50.0   # 信号强度 0-100
    summary: str = ""


class StockPredictor:
    """股票涨跌概率预测器（纯技术指标，非ML）。"""

    def predict(self, code: str, df: pd.DataFrame) -> PredictionResult:
        """预测单只股票短期走势。"""
        result = PredictionResult(code=code)

        if df is None or len(df) < 30:
            result.summary = "数据不足，无法预测"
            return result

        try:
            close = df["close"].values
            high = df["high"].values
            low = df["low"].values
            volume = df["volume"].values

            # 1. RSI
            result.rsi = self._calc_rsi(close, 14)

            # 2. MACD
            result.macd_hist = self._calc_macd_hist(close)

            # 3. 布林带位置
            result.bb_position = self._calc_bb_position(close)

            # 4. 均线趋势
            result.ma_trend = self._calc_ma_trend(close)

            # 5. 量能趋势
            result.volume_trend = self._calc_volume_trend(volume)

            # 6. 综合预测
            result = self._predict(result)

            result.summary = self._build_summary(result)

        except Exception as e:
            logger.warning(f"[{code}] 预测计算失败: {e}")
            result.summary = f"计算异常: {e}"

        return result

    def predict_batch(self, codes: list[str], data_getter) -> dict[str, PredictionResult]:
        """批量预测。data_getter: callable(code) -> DataFrame。"""
        results = {}
        for code in codes:
            try:
                df = data_getter(code)
                results[code] = self.predict(code, df)
            except Exception as e:
                logger.warning(f"[{code}] 预测失败: {e}")
                results[code] = PredictionResult(code=code, summary=f"预测失败: {e}")
        return results

    @staticmethod
    def _calc_rsi(close: np.ndarray, period: int = 14) -> float:
        """计算 RSI。"""
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_macd_hist(close: np.ndarray) -> float:
        """计算 MACD 柱状值（归一化）。"""
        ema12 = pd.Series(close).ewm(span=12).mean().values
        ema26 = pd.Series(close).ewm(span=26).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9).mean().values
        macd_hist = (dif - dea) * 2
        # 归一化到价格百分比
        return (macd_hist[-1] / close[-1]) * 100 if close[-1] > 0 else 0

    @staticmethod
    def _calc_bb_position(close: np.ndarray, period: int = 20) -> float:
        """计算布林带位置：0=下轨, 0.5=中轨, 1=上轨。"""
        sma = np.mean(close[-period:])
        std = np.std(close[-period:])
        if std == 0:
            return 0.5
        upper = sma + 2 * std
        lower = sma - 2 * std
        current = close[-1]
        return (current - lower) / (upper - lower) if upper != lower else 0.5

    @staticmethod
    def _calc_ma_trend(close: np.ndarray) -> str:
        """判断均线趋势。"""
        if len(close) < 60:
            return "neutral"

        ma5 = np.mean(close[-5:])
        ma10 = np.mean(close[-10:])
        ma20 = np.mean(close[-20:])
        ma60 = np.mean(close[-60:])

        if ma5 > ma10 > ma20 > ma60:
            return "bullish"      # 多头排列
        elif ma5 < ma10 < ma20 < ma60:
            return "bearish"      # 空头排列
        else:
            return "neutral"

    @staticmethod
    def _calc_volume_trend(volume: np.ndarray, period: int = 5) -> str:
        """判断量能趋势。"""
        if len(volume) < period * 2:
            return "normal"

        recent_avg = np.mean(volume[-period:])
        prev_avg = np.mean(volume[-period * 2:-period])

        if prev_avg == 0:
            return "normal"

        ratio = recent_avg / prev_avg
        if ratio > 1.5:
            return "expanding"    # 放量
        elif ratio < 0.6:
            return "shrinking"    # 缩量
        else:
            return "normal"

    def _predict(self, result: PredictionResult) -> PredictionResult:
        """综合技术指标计算涨跌概率。"""
        bull_score = 50.0

        # RSI 信号
        if result.rsi < 30:
            bull_score += 15  # 超卖，看涨
        elif result.rsi < 40:
            bull_score += 8
        elif result.rsi > 70:
            bull_score -= 15  # 超买，看跌
        elif result.rsi > 60:
            bull_score -= 8

        # MACD 信号
        if result.macd_hist > 0.5:
            bull_score += 12  # MACD 金叉/红柱
        elif result.macd_hist > 0:
            bull_score += 5
        elif result.macd_hist < -0.5:
            bull_score -= 12  # MACD 死叉/绿柱
        elif result.macd_hist < 0:
            bull_score -= 5

        # 布林带位置
        if result.bb_position < 0.1:
            bull_score += 10  # 触及下轨，反弹概率大
        elif result.bb_position < 0.3:
            bull_score += 5
        elif result.bb_position > 0.9:
            bull_score -= 10  # 触及上轨，回调概率大
        elif result.bb_position > 0.7:
            bull_score -= 5

        # 均线趋势
        if result.ma_trend == "bullish":
            bull_score += 10
        elif result.ma_trend == "bearish":
            bull_score -= 10

        # 量能
        if result.volume_trend == "expanding" and result.ma_trend == "bullish":
            bull_score += 5  # 放量上涨
        elif result.volume_trend == "expanding" and result.ma_trend == "bearish":
            bull_score -= 5  # 放量下跌

        # 限制在 0-100
        bull_score = max(0, min(100, bull_score))

        result.bull_probability = bull_score
        result.bear_probability = 100 - bull_score
        result.signal_strength = abs(bull_score - 50) * 2  # 信号强度

        return result

    @staticmethod
    def _build_summary(result: PredictionResult) -> str:
        """生成预测摘要。"""
        parts = []

        if result.bull_probability >= 70:
            parts.append(f"🟢 看涨概率 {result.bull_probability:.0f}%")
        elif result.bull_probability >= 55:
            parts.append(f"🟡 偏多 {result.bull_probability:.0f}%")
        elif result.bull_probability <= 30:
            parts.append(f"🔴 看跌概率 {result.bear_probability:.0f}%")
        elif result.bull_probability <= 45:
            parts.append(f"🟠 偏空 {result.bear_probability:.0f}%")
        else:
            parts.append(f"⚪ 中性 {result.bull_probability:.0f}%")

        # 技术指标补充
        if result.rsi < 30:
            parts.append("RSI超卖")
        elif result.rsi > 70:
            parts.append("RSI超买")

        if result.ma_trend == "bullish":
            parts.append("多头排列")
        elif result.ma_trend == "bearish":
            parts.append("空头排列")

        if result.volume_trend == "expanding":
            parts.append("放量")
        elif result.volume_trend == "shrinking":
            parts.append("缩量")

        return "，".join(parts)
