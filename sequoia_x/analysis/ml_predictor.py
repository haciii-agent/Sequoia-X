"""ML 预测模块：用历史K线特征训练 GradientBoosting 模型，预测未来N日涨跌概率。"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler
import joblib
import os

from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml_models")


@dataclass
class MLPrediction:
    """ML 预测结果。"""
    code: str
    bull_prob: float = 50.0     # 看涨概率 0-100
    bear_prob: float = 50.0     # 看跌概率 0-100
    confidence: float = 0.0     # 模型置信度（交叉验证准确率）
    signal: str = "neutral"     # bullish / bearish / neutral
    summary: str = ""


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """从 OHLCV 数据构建技术指标特征矩阵。"""
    feat = pd.DataFrame(index=df.index)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # ---- 价格动量 ----
    for n in [5, 10, 20, 40]:
        feat[f"ret_{n}"] = close.pct_change(n)

    # ---- 均线偏离 ----
    for n in [5, 10, 20, 60]:
        ma = close.rolling(n).mean()
        feat[f"ma_bias_{n}"] = (close - ma) / ma

    # ---- RSI ----
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    for n in [6, 14]:
        avg_gain = gain.rolling(n).mean()
        avg_loss = loss.rolling(n).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        feat[f"rsi_{n}"] = 100 - 100 / (1 + rs)

    # ---- MACD ----
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    feat["macd_dif"] = dif / close
    feat["macd_dea"] = dea / close
    feat["macd_hist"] = (dif - dea) * 2 / close

    # ---- 布林带 ----
    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    feat["bb_position"] = (close - bb_ma) / (2 * bb_std + 1e-10)
    feat["bb_width"] = (4 * bb_std) / (bb_ma + 1e-10)

    # ---- 量能 ----
    for n in [5, 10, 20]:
        vol_ma = volume.rolling(n).mean()
        feat[f"vol_ratio_{n}"] = volume / (vol_ma + 1e-10)

    # ---- 波动率 ----
    for n in [5, 10, 20]:
        feat[f"volatility_{n}"] = close.pct_change().rolling(n).std()

    # ---- ATR ----
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    feat["atr_14"] = tr.rolling(14).mean() / close

    # ---- K线形态 ----
    feat["upper_shadow"] = (high - close.clip(lower=df["open"])) / close
    feat["lower_shadow"] = (close.clip(upper=df["open"]) - low) / close
    feat["body_ratio"] = (close - df["open"]).abs() / (high - low + 1e-10)

    # ---- 高低点位置 ----
    for n in [10, 20, 40]:
        feat[f"high_pos_{n}"] = (close - low.rolling(n).min()) / (high.rolling(n).max() - low.rolling(n).min() + 1e-10)

    return feat


def _build_labels(df: pd.DataFrame, forward_days: int = 5, threshold: float = 0.03) -> pd.Series:
    """构建标签：未来N日涨幅超过阈值 → 1，跌幅超阈值 → -1，其余 → 0。"""
    future_ret = df["close"].shift(-forward_days) / df["close"] - 1
    labels = pd.Series(0, index=df.index)
    labels[future_ret > threshold] = 1
    labels[future_ret < -threshold] = -1
    return labels


class MLPredictor:
    """基于 GradientBoosting 的涨跌预测器。"""

    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self._is_trained = False
        self._accuracy = 0.0
        os.makedirs(MODEL_DIR, exist_ok=True)

    def train(self, all_data: list[pd.DataFrame], forward_days: int = 5, threshold: float = 0.03) -> float:
        """用多只股票的历史数据训练模型。

        Args:
            all_data: 多只股票的 OHLCV DataFrame 列表
            forward_days: 预测未来N天
            threshold: 涨跌阈值

        Returns:
            交叉验证准确率
        """
        logger.info(f"开始训练 ML 模型，{len(all_data)} 只股票数据...")

        X_list, y_list = [], []

        for df in all_data:
            if len(df) < 100:
                continue

            features = _build_features(df)
            labels = _build_labels(df, forward_days, threshold)

            # 合并并去掉 NaN
            merged = features.copy()
            merged["label"] = labels
            merged = merged.dropna()

            if len(merged) < 60:
                continue

            X_list.append(merged.drop("label", axis=1))
            y_list.append(merged["label"])

        if not X_list:
            logger.warning("训练数据不足")
            return 0.0

        X = pd.concat(X_list, ignore_index=True)
        y = pd.concat(y_list, ignore_index=True)

        # 只保留二分类（涨 vs 不涨）
        y_binary = (y == 1).astype(int)

        logger.info(f"训练集大小: {len(X)} 条，正样本比例: {y_binary.mean():.2%}")

        # 标准化
        X_scaled = self.scaler.fit_transform(X)

        # 训练
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=20,
            random_state=42,
        )

        # 交叉验证
        scores = cross_val_score(self.model, X_scaled, y_binary, cv=5, scoring="accuracy")
        self._accuracy = scores.mean()
        logger.info(f"5折交叉验证准确率: {self._accuracy:.2%} (+/- {scores.std():.2%})")

        # 全量训练
        self.model.fit(X_scaled, y_binary)
        self._is_trained = True

        # 保存模型
        self._save_model()

        return self._accuracy

    def predict(self, code: str, df: pd.DataFrame) -> MLPrediction:
        """预测单只股票。"""
        result = MLPrediction(code=code)

        if not self._is_trained:
            if not self._load_model():
                result.summary = "模型未训练"
                return result

        if df is None or len(df) < 60:
            result.summary = "数据不足"
            return result

        try:
            features = _build_features(df)
            latest = features.dropna().iloc[[-1]]

            if latest.empty:
                result.summary = "特征计算失败"
                return result

            X_scaled = self.scaler.transform(latest)
            prob = self.model.predict_proba(X_scaled)[0]

            # prob[0] = 不涨概率, prob[1] = 涨概率
            result.bull_prob = prob[1] * 100
            result.bear_prob = prob[0] * 100
            result.confidence = self._accuracy * 100

            if result.bull_prob >= 60:
                result.signal = "bullish"
            elif result.bull_prob <= 40:
                result.signal = "bearish"
            else:
                result.signal = "neutral"

            result.summary = self._build_summary(result)

        except Exception as e:
            logger.warning(f"[{code}] ML 预测失败: {e}")
            result.summary = f"预测异常: {e}"

        return result

    def predict_batch(self, codes: list[str], data_getter) -> dict[str, MLPrediction]:
        """批量预测。"""
        # 先尝试加载模型
        if not self._is_trained:
            self._load_model()

        results = {}
        for code in codes:
            try:
                df = data_getter(code)
                results[code] = self.predict(code, df)
            except Exception as e:
                logger.warning(f"[{code}] ML 预测失败: {e}")
                results[code] = MLPrediction(code=code, summary=f"预测失败: {e}")
        return results

    def _save_model(self):
        """保存模型和scaler。"""
        try:
            joblib.dump(self.model, os.path.join(MODEL_DIR, "gbm_model.pkl"))
            joblib.dump(self.scaler, os.path.join(MODEL_DIR, "scaler.pkl"))
            logger.info(f"模型已保存到 {MODEL_DIR}")
        except Exception as e:
            logger.warning(f"模型保存失败: {e}")

    def _load_model(self) -> bool:
        """加载已保存的模型。"""
        model_path = os.path.join(MODEL_DIR, "gbm_model.pkl")
        scaler_path = os.path.join(MODEL_DIR, "scaler.pkl")

        if os.path.exists(model_path) and os.path.exists(scaler_path):
            try:
                self.model = joblib.load(model_path)
                self.scaler = joblib.load(scaler_path)
                self._is_trained = True
                logger.info("已加载预训练模型")
                return True
            except Exception as e:
                logger.warning(f"模型加载失败: {e}")
        return False

    @staticmethod
    def _build_summary(result: MLPrediction) -> str:
        if result.signal == "bullish":
            return f"ML看涨 {result.bull_prob:.0f}%（置信度{result.confidence:.0f}%）"
        elif result.signal == "bearish":
            return f"ML看跌 {result.bear_prob:.0f}%（置信度{result.confidence:.0f}%）"
        else:
            return f"ML中性 {result.bull_prob:.0f}%（置信度{result.confidence:.0f}%）"
