"""ML 预测模块 V2：全市场训练，并发特征工程，缓存优化。"""

import numpy as np
import pandas as pd
import os
import time
import joblib
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml_models")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml_cache")


@dataclass
class MLPrediction:
    """ML 预测结果。"""
    code: str
    bull_prob: float = 50.0
    bear_prob: float = 50.0
    confidence: float = 0.0
    signal: str = "neutral"
    summary: str = ""


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """从 OHLCV 数据构建技术指标特征矩阵。"""
    feat = pd.DataFrame(index=df.index)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # 价格动量
    for n in [3, 5, 10, 20]:
        feat[f"ret_{n}"] = close.pct_change(n)

    # 均线偏离
    for n in [5, 10, 20]:
        ma = close.rolling(n).mean()
        feat[f"ma_bias_{n}"] = (close - ma) / ma

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    for n in [6, 14]:
        avg_gain = gain.rolling(n).mean()
        avg_loss = loss.rolling(n).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        feat[f"rsi_{n}"] = 100 - 100 / (1 + rs)

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    feat["macd_dif"] = dif / close
    feat["macd_dea"] = dea / close
    feat["macd_hist"] = (dif - dea) * 2 / close

    # 布林带
    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    feat["bb_position"] = (close - bb_ma) / (2 * bb_std + 1e-10)

    # 量能
    for n in [3, 5, 10]:
        vol_ma = volume.rolling(n).mean()
        feat[f"vol_ratio_{n}"] = volume / (vol_ma + 1e-10)

    # 波动率
    for n in [5, 10]:
        feat[f"volatility_{n}"] = close.pct_change().rolling(n).std()

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    feat["atr_5"] = tr.rolling(5).mean() / close

    # K线形态
    feat["upper_shadow"] = (high - close.clip(lower=df["open"])) / close
    feat["lower_shadow"] = (close.clip(upper=df["open"]) - low) / close
    feat["body_ratio"] = (close - df["open"]).abs() / (high - low + 1e-10)

    # 高低点位置
    for n in [5, 10, 20]:
        feat[f"high_pos_{n}"] = (close - low.rolling(n).min()) / (high.rolling(n).max() - low.rolling(n).min() + 1e-10)

    # 涨停/跌停标记
    daily_ret = close.pct_change()
    feat["is_limit_up"] = (daily_ret > 0.095).astype(float)
    feat["is_limit_down"] = (daily_ret < -0.095).astype(float)

    # 连涨/连跌天数
    up = (daily_ret > 0).astype(int)
    down = (daily_ret < 0).astype(int)
    feat["consecutive_up"] = up * (up.groupby((up != up.shift()).cumsum()).cumcount() + 1)
    feat["consecutive_down"] = down * (down.groupby((down != down.shift()).cumsum()).cumcount() + 1)

    return feat


def _build_labels(df: pd.DataFrame, forward_days: int = 3, threshold: float = 0.03) -> pd.Series:
    """构建标签：未来N日涨超阈值 → 1，跌超阈值 → -1，其余 → 0。"""
    future_ret = df["close"].shift(-forward_days) / df["close"] - 1
    labels = pd.Series(0, index=df.index)
    labels[future_ret > threshold] = 1
    labels[future_ret < -threshold] = -1
    return labels


def _process_one_stock(args):
    """处理单只股票（用于多进程）。"""
    code, df_dict, forward_days, threshold = args
    df = pd.DataFrame(df_dict)
    if len(df) < 80:
        return None

    try:
        features = _build_features(df)
        labels = _build_labels(df, forward_days, threshold)
        merged = features.copy()
        merged["label"] = labels
        merged = merged.dropna()
        if len(merged) < 40:
            return None
        return merged
    except Exception:
        return None


class MLPredictor:
    """基于 GradientBoosting 的涨跌预测器（全市场并发训练）。"""

    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self._is_trained = False
        self._accuracy = 0.0
        os.makedirs(MODEL_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)

    def train(
        self,
        all_data: list[pd.DataFrame],
        forward_days: int = 3,
        threshold: float = 0.03,
        max_workers: int = 8,
    ) -> float:
        """用全市场数据并发训练模型。"""
        logger.info(f"开始训练 ML 模型，{len(all_data)} 只股票，{max_workers} 进程并发...")

        # 准备多进程参数
        tasks = []
        for i, df in enumerate(all_data):
            if len(df) >= 80:
                df_dict = df.to_dict(orient="list")
                df_dict["__index__"] = list(df.index)
                tasks.append((f"stock_{i}", df_dict, forward_days, threshold))

        logger.info(f"有效股票: {len(tasks)} 只，开始并发特征工程...")

        # 并发特征工程
        chunks = []
        t0 = time.time()

        # 直接串行处理（避免Windows多进程问题）
        for i, task in enumerate(tasks):
            result = _process_one_stock(task)
            if result is not None:
                chunks.append(result)
            if (i + 1) % 500 == 0:
                logger.info(f"  特征工程进度: {i+1}/{len(tasks)}")

        elapsed = time.time() - t0
        logger.info(f"特征工程完成: {len(chunks)} 只股票有效，耗时 {elapsed:.1f}s")

        if not chunks:
            logger.warning("训练数据不足")
            return 0.0

        X = pd.concat(chunks, ignore_index=True)
        y = X.pop("label")
        y_binary = (y == 1).astype(int)

        logger.info(f"训练集: {len(X)} 条，正样本: {y_binary.mean():.2%}")

        # 缓存特征矩阵
        cache_path = os.path.join(CACHE_DIR, "features.pkl")
        joblib.dump((X, y_binary), cache_path)
        logger.info(f"特征已缓存到 {cache_path}")

        # 标准化
        X_scaled = self.scaler.fit_transform(X)

        # 训练
        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.15,
            subsample=0.8,
            min_samples_leaf=50,
            random_state=42,
        )

        scores = cross_val_score(self.model, X_scaled, y_binary, cv=5, scoring="accuracy")
        self._accuracy = scores.mean()
        logger.info(f"5折交叉验证准确率: {self._accuracy:.2%} (+/- {scores.std():.2%})")

        self.model.fit(X_scaled, y_binary)
        self._is_trained = True
        self._save_model()

        # 特征重要性
        importances = self.model.feature_importances_
        feature_names = X.columns.tolist()
        top_features = sorted(zip(feature_names, importances), key=lambda x: -x[1])[:10]
        logger.info("TOP10 重要特征:")
        for name, imp in top_features:
            logger.info(f"  {name}: {imp:.4f}")

        return self._accuracy

    def train_from_cache(self) -> float:
        """从缓存特征矩阵直接训练（跳过特征工程）。"""
        cache_path = os.path.join(CACHE_DIR, "features.pkl")
        if not os.path.exists(cache_path):
            logger.warning("无缓存特征，请先运行全量训练")
            return 0.0

        logger.info("从缓存加载特征矩阵...")
        X, y_binary = joblib.load(cache_path)
        logger.info(f"训练集: {len(X)} 条，正样本: {y_binary.mean():.2%}")

        X_scaled = self.scaler.fit_transform(X)

        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.15,
            subsample=0.8,
            min_samples_leaf=50,
            random_state=42,
        )

        scores = cross_val_score(self.model, X_scaled, y_binary, cv=5, scoring="accuracy")
        self._accuracy = scores.mean()
        logger.info(f"5折交叉验证准确率: {self._accuracy:.2%} (+/- {scores.std():.2%})")

        self.model.fit(X_scaled, y_binary)
        self._is_trained = True
        self._save_model()

        return self._accuracy

    def predict(self, code: str, df: pd.DataFrame) -> MLPrediction:
        """预测单只股票。"""
        result = MLPrediction(code=code)

        if not self._is_trained and not self._load_model():
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
        try:
            joblib.dump(self.model, os.path.join(MODEL_DIR, "gbm_model.pkl"))
            joblib.dump(self.scaler, os.path.join(MODEL_DIR, "scaler.pkl"))
            logger.info(f"模型已保存到 {MODEL_DIR}")
        except Exception as e:
            logger.warning(f"模型保存失败: {e}")

    def _load_model(self) -> bool:
        model_path = os.path.join(MODEL_DIR, "gbm_model.pkl")
        scaler_path = os.path.join(MODEL_DIR, "scaler.pkl")
        if os.path.exists(model_path) and os.path.exists(scaler_path):
            try:
                self.model = joblib.load(model_path)
                self.scaler = joblib.load(scaler_path)
                self._is_trained = True
                return True
            except Exception as e:
                logger.warning(f"模型加载失败: {e}")
        return False

    @staticmethod
    def _build_summary(result: MLPrediction) -> str:
        if result.signal == "bullish":
            return f"ML看涨{result.bull_prob:.0f}%（置信度{result.confidence:.0f}%）"
        elif result.signal == "bearish":
            return f"ML看跌{result.bear_prob:.0f}%（置信度{result.confidence:.0f}%）"
        return f"ML中性{result.bull_prob:.0f}%（置信度{result.confidence:.0f}%）"
