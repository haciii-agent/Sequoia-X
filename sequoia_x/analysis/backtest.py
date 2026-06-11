"""回测验证模块：用历史数据验证策略胜率、盈亏比、最大回撤。"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradeRecord:
    """单笔交易记录。"""
    code: str
    strategy: str
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    holding_days: int = 0
    return_pct: float = 0.0
    is_win: bool = False


@dataclass
class BacktestResult:
    """回测结果。"""
    strategy_name: str
    period: str = ""                    # 回测区间
    total_signals: int = 0              # 总信号数
    valid_trades: int = 0               # 有效交易数
    win_count: int = 0                  # 盈利次数
    loss_count: int = 0                 # 亏损次数
    win_rate: float = 0.0              # 胜率 (%)
    avg_win: float = 0.0               # 平均盈利 (%)
    avg_loss: float = 0.0              # 平均亏损 (%)
    profit_loss_ratio: float = 0.0     # 盈亏比
    total_return: float = 0.0          # 累计收益 (%)
    max_drawdown: float = 0.0          # 最大回撤 (%)
    avg_holding_days: float = 0.0      # 平均持仓天数
    sharpe_ratio: float = 0.0          # 夏普比率
    trades: list = field(default_factory=list)
    summary: str = ""


class Backtester:
    """策略回测器。"""

    def __init__(
        self,
        holding_days: int = 10,       # 默认持仓天数
        stop_loss: float = -0.08,     # 止损 -8%
        take_profit: float = 0.20,    # 止盈 +20%
    ):
        self.holding_days = holding_days
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def run(
        self,
        strategy_name: str,
        signals: list[dict],          # [{"code": str, "date": str, "price": float}, ...]
        price_data: dict[str, pd.DataFrame],  # {code: DataFrame with OHLCV}
    ) -> BacktestResult:
        """运行回测。

        Args:
            strategy_name: 策略名称
            signals: 信号列表（选股结果+日期+入场价）
            price_data: 价格数据 {code: DataFrame}

        Returns:
            BacktestResult
        """
        result = BacktestResult(strategy_name=strategy_name)
        result.total_signals = len(signals)

        trades = []
        for sig in signals:
            code = sig["code"]
            entry_date = sig["date"]
            entry_price = sig["price"]

            if code not in price_data:
                continue

            df = price_data[code]
            trade = self._simulate_trade(code, entry_date, entry_price, df, strategy_name)
            if trade:
                trades.append(trade)

        result.valid_trades = len(trades)
        result.trades = trades

        if not trades:
            result.summary = f"{strategy_name}: 无有效交易"
            return result

        # 统计
        returns = [t.return_pct for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        result.win_count = len(wins)
        result.loss_count = len(losses)
        result.win_rate = len(wins) / len(trades) * 100
        result.avg_win = np.mean(wins) * 100 if wins else 0
        result.avg_loss = np.mean(losses) * 100 if losses else 0
        result.profit_loss_ratio = abs(result.avg_win / result.avg_loss) if result.avg_loss != 0 else 0
        result.total_return = sum(returns) * 100
        result.avg_holding_days = np.mean([t.holding_days for t in trades])

        # 最大回撤
        cumulative = np.cumprod(1 + np.array(returns))
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak
        result.max_drawdown = abs(drawdown.min()) * 100 if len(drawdown) > 0 else 0

        # 夏普比率（假设无风险利率 3%/年）
        if len(returns) > 1:
            excess = np.mean(returns) - 0.03 / 252 * result.avg_holding_days
            vol = np.std(returns)
            result.sharpe_ratio = excess / vol * np.sqrt(252 / result.avg_holding_days) if vol > 0 else 0

        result.period = f"{trades[0].entry_date} ~ {trades[-1].entry_date}"
        result.summary = self._build_summary(result)

        return result

    def _simulate_trade(
        self,
        code: str,
        entry_date: str,
        entry_price: float,
        df: pd.DataFrame,
        strategy: str,
    ) -> TradeRecord | None:
        """模拟单笔交易。"""
        try:
            # 找到入场日之后的数据
            df = df.copy()
            if "date" in df.columns:
                future = df[df["date"] > entry_date].head(self.holding_days)
            else:
                # 假设 index 是日期
                future = df.loc[entry_date:].iloc[1:self.holding_days + 1] if entry_date in df.index else pd.DataFrame()

            if future.empty or len(future) < 2:
                return None

            trade = TradeRecord(
                code=code,
                strategy=strategy,
                entry_date=entry_date,
                entry_price=entry_price,
            )

            # 逐日检查止损止盈
            for _, row in future.iterrows():
                current_price = row["close"]
                ret = (current_price - entry_price) / entry_price

                if ret <= self.stop_loss:
                    trade.exit_date = str(row.get("date", ""))
                    trade.exit_price = current_price
                    trade.return_pct = self.stop_loss
                    trade.is_win = False
                    trade.holding_days = len(future.loc[:row.name]) if row.name else 0
                    return trade

                if ret >= self.take_profit:
                    trade.exit_date = str(row.get("date", ""))
                    trade.exit_price = current_price
                    trade.return_pct = self.take_profit
                    trade.is_win = True
                    trade.holding_days = len(future.loc[:row.name]) if row.name else 0
                    return trade

            # 到期平仓
            last = future.iloc[-1]
            trade.exit_date = str(last.get("date", ""))
            trade.exit_price = last["close"]
            trade.return_pct = (last["close"] - entry_price) / entry_price
            trade.is_win = trade.return_pct > 0
            trade.holding_days = len(future)

            return trade

        except Exception as e:
            logger.debug(f"[{code}] 回测交易模拟失败: {e}")
            return None

    @staticmethod
    def _build_summary(result: BacktestResult) -> str:
        parts = [
            f"{result.strategy_name}:",
            f"胜率{result.win_rate:.1f}%",
            f"盈亏比{result.profit_loss_ratio:.2f}",
            f"累计{result.total_return:+.1f}%",
            f"最大回撤{result.max_drawdown:.1f}%",
            f"夏普{result.sharpe_ratio:.2f}",
            f"共{result.valid_trades}笔交易",
        ]
        return " | ".join(parts)


def run_multi_strategy_backtest(
    engine,
    strategies: list,
    lookback_days: int = 180,
    holding_days: int = 10,
    step_days: int = 5,
) -> list[BacktestResult]:
    """多策略历史回测。

    从过去 lookback_days 天开始，每隔 step_days 天跑一次策略选股，
    然后模拟持仓 holding_days 天看收益。

    Args:
        engine: 数据引擎
        strategies: 策略实例列表
        lookback_days: 回看天数
        holding_days: 持仓天数
        step_days: 步进天数

    Returns:
        各策略的回测结果列表
    """
    logger.info(f"开始回测：回看{lookback_days}天，持仓{holding_days}天，步进{step_days}天")

    # 获取所有股票数据
    symbols = engine.get_local_symbols()
    logger.info(f"加载 {len(symbols)} 只股票数据...")

    all_data: dict[str, pd.DataFrame] = {}
    for code in symbols:
        try:
            df = engine.get_ohlcv(code)
            if df is not None and len(df) >= 60:
                all_data[code] = df
        except Exception:
            pass

    logger.info(f"有效数据: {len(all_data)} 只股票")

    backtester = Backtester(holding_days=holding_days)
    results = []

    for strategy in strategies:
        strategy_name = type(strategy).__name__
        logger.info(f"回测策略: {strategy_name}")

        signals = []

        # 在历史多个时间点跑策略
        # 用简化方式：取每只股票的数据，截断到历史日期，看信号
        for code, df in all_data.items():
            try:
                # 取最近 lookback_days 的数据
                if len(df) < lookback_days + 60:
                    continue

                hist_df = df.iloc[-(lookback_days + 60):]
                dates = hist_df["date"].values if "date" in hist_df.columns else hist_df.index

                # 每隔 step_days 天检查一次
                for i in range(60, len(hist_df) - holding_days, step_days):
                    window = hist_df.iloc[:i + 1]
                    if len(window) < 60:
                        continue

                    try:
                        # 用 engine 的方法可能不支持截断，直接在这里做简单判断
                        # 基于策略类型的简化信号检测
                        if _check_signal(strategy_name, window):
                            entry_date = str(dates[i]) if i < len(dates) else ""
                            entry_price = window.iloc[-1]["close"]
                            signals.append({
                                "code": code,
                                "date": entry_date,
                                "price": entry_price,
                            })
                    except Exception:
                        pass

            except Exception:
                pass

        logger.info(f"{strategy_name} 历史信号数: {len(signals)}")

        # 运行回测
        result = backtester.run(strategy_name, signals, all_data)
        results.append(result)
        logger.info(f"  {result.summary}")

    return results


def _check_signal(strategy_name: str, df: pd.DataFrame) -> bool:
    """简化的策略信号检测（用于回测加速）。"""
    try:
        close = df["close"].values
        volume = df["volume"].values

        if "MaVolume" in strategy_name:
            # 均线放量：价格站上MA20 + 量比>1.5
            ma20 = np.mean(close[-20:])
            vol_ratio = volume[-1] / (np.mean(volume[-20:]) + 1e-10)
            return close[-1] > ma20 and vol_ratio > 1.5

        elif "Turtle" in strategy_name:
            # 海龟突破：突破20日新高
            high20 = np.max(close[-21:-1])
            return close[-1] > high20

        elif "HighTightFlag" in strategy_name:
            # 高位旗形：40日涨60% + 10日振幅<15% + 缩量
            if len(close) < 40:
                return False
            high40 = np.max(close[-40:])
            low40 = np.min(close[-40:])
            high10 = np.max(close[-10:])
            low10 = np.min(close[-10:])
            vol_ma20 = np.mean(volume[-21:-1])
            momentum = high40 / (low40 + 1e-10) > 1.6
            consolidation = high10 / (low10 + 1e-10) < 1.15
            shrink = volume[-1] < vol_ma20 * 0.6
            high_level = low10 >= high40 * 0.8
            return momentum and consolidation and high_level and shrink

        elif "RpsBreakout" in strategy_name:
            # RPS突破：20日涨幅排名靠前（简化：涨幅>15%）
            ret20 = (close[-1] / close[-20] - 1) if len(close) >= 20 else 0
            return ret20 > 0.15

        elif "LimitUpShakeout" in strategy_name:
            # 涨停洗盘：近期有涨停 + 回调
            if len(close) < 10:
                return False
            for i in range(-10, -1):
                daily_ret = close[i] / close[i - 1] - 1 if i > -len(close) else 0
                if daily_ret > 0.095:  # 涨停
                    # 之后回调
                    later_ret = close[-1] / close[i] - 1
                    if -0.1 < later_ret < 0:
                        return True
            return False

        elif "UptrendLimitDown" in strategy_name:
            # 趋势跌停：上升趋势中出现跌停
            if len(close) < 20:
                return False
            trend_up = close[-20] < close[-10] < close[-5]
            daily_ret = close[-1] / close[-2] - 1
            return trend_up and daily_ret < -0.095

        elif "PrivatePlacement" in strategy_name:
            return False  # 定增策略需要公告数据，回测中跳过

        return False

    except Exception:
        return False
