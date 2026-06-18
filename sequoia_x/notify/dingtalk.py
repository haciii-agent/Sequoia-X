"""钉钉通知模块：支持综合分析报告推送。"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import date

import baostock as bs
import requests

from sequoia_x.analysis.scorer import StockRating
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

# 策略中文名映射
STRATEGY_NAMES = {
    "MaVolumeStrategy": "均线放量",
    "TurtleTradeStrategy": "海龟突破",
    "HighTightFlagStrategy": "高位旗形",
    "LimitUpShakeoutStrategy": "涨停洗盘",
    "UptrendLimitDownStrategy": "趋势跌停",
    "RpsBreakoutStrategy": "RPS突破",
    "PrivatePlacementStrategy": "定增机会",
    "ShortTermMomentumStrategy": "短线动量",
    "VolumeBreakoutStrategy": "放量突破",
    "GapUpFollowStrategy": "跳空跟随",
    "ConsecutiveRedStrategy": "连阴反包",
    "ShortTermPullbackStrategy": "回踩支撑",
}


def _sign_url(url: str, secret: str) -> str:
    """给钉钉 Webhook URL 加签。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{url}&timestamp={timestamp}&sign={sign}"


class DingTalkNotifier:
    """钉钉 Webhook 推送器（加签方式）。"""

    def __init__(self) -> None:
        self.webhook_url = os.getenv("DINGTALK_WEBHOOK", "").strip()
        self.secret = os.getenv("DINGTALK_SECRET", "").strip()
        if not self.webhook_url or not self.secret:
            raise ValueError(
                "缺少钉钉配置：请在 .env 中设置 DINGTALK_WEBHOOK 和 DINGTALK_SECRET"
            )

    @staticmethod
    def _to_eastmoney_code(code: str) -> str:
        """纯数字代码转东方财富格式。"""
        if code.startswith("6"):
            return f"sh{code}"
        elif code.startswith(("4", "8")):
            return f"bj{code}"
        return f"sz{code}"

    @staticmethod
    def _get_stock_names(symbols: list[str]) -> dict[str, str]:
        """通过 baostock 批量查询股票名称，北交所用东方财富补充。"""
        bs.login()
        mapping = {}
        missing = []
        for code in symbols:
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            rs = bs.query_stock_basic(code=f"{prefix}.{code}")
            found = False
            while rs.next():
                row = rs.get_row_data()
                if len(row) > 1 and row[1]:
                    mapping[code] = row[1]
                    found = True
            if not found:
                missing.append(code)
        bs.logout()

        for code in missing:
            try:
                if code.startswith("6"):
                    secid = f"1.{code}"
                else:
                    secid = f"0.{code}"
                url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58"
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                data = response.json().get("data", {})
                name = data.get("f58", "")
                if name:
                    mapping[code] = name
            except Exception:
                pass

        return mapping

    def send(
        self,
        symbols: list[str],
        strategy_name: str,
        webhook_key: str = "default",
        reasons: dict[str, str] | None = None,
    ) -> None:
        """推送单个策略的选股结果。"""
        if not symbols:
            logger.info(f"钉钉推送 [{webhook_key}] 无选股结果，跳过")
            return

        today = date.today().strftime("%Y-%m-%d")
        cn_name = STRATEGY_NAMES.get(strategy_name, strategy_name)
        names = self._get_stock_names(symbols)

        lines = [
            f"## {cn_name} 选股播报",
            f"**日期：** {today} | **数量：** {len(symbols)}",
            "",
            "| 代码 | 名称 | 链接 |",
            "|------|------|------|",
        ]

        for code in symbols:
            em_code = self._to_eastmoney_code(code)
            name = names.get(code, code)
            lines.append(f"| {code} | {name} | [东方财富](https://quote.eastmoney.com/{em_code}.html) |")

        if reasons:
            lines.append("")
            lines.append("**选股理由：**")
            for code in symbols:
                reason = reasons.get(code, "")
                if reason:
                    name = names.get(code, code)
                    lines.append(f"- {code} {name}：{reason}")

        self._send_markdown(f"{cn_name} 选出 {len(symbols)} 只", "\n".join(lines), webhook_key)

    def send_comprehensive_report(self, ratings: list[StockRating], top_n: int = 20) -> None:
        """推送综合分析报告。"""
        if not ratings:
            return

        today = date.today().strftime("%Y-%m-%d")
        top = ratings[:top_n]
        all_codes = [rating.code for rating in ratings]
        names = self._get_stock_names(all_codes)

        lines = [
            "## Sequoia-X AI 综合选股报告",
            f"**日期：** {today} | **分析：** {len(ratings)} 只 | **展示 TOP{top_n}**",
            "",
            "### 综合排名",
            "",
            "| # | 代码 | 名称 | 综合 | 技术 | 基本面 | 舆情 | 事件 | 资金 |",
            "|---|------|------|------|------|--------|------|------|------|",
        ]

        for rating in top:
            name = names.get(rating.code, rating.name or rating.code)
            lines.append(
                f"| {rating.rank} | {rating.code} | {name} | **{rating.total_score:.1f}** | "
                f"{rating.technical_score:.0f} | {rating.fundamental_score:.0f} | "
                f"{rating.sentiment_score:.0f} | {rating.event_score:.0f} | "
                f"{rating.capital_score:.0f} |"
            )

        lines.append("")
        lines.append("### TOP5 详细分析")

        for rating in top[:5]:
            em_code = self._to_eastmoney_code(rating.code)
            name = names.get(rating.code, rating.name or rating.code)
            lines.append("")
            lines.append(f"**{rating.rank}. {rating.code} {name}** — 综合 {rating.total_score:.1f} 分")

            if rating.tags:
                lines.append(f"标签：{' '.join(rating.tags)}")

            if rating.strategies:
                cn_strs = [STRATEGY_NAMES.get(strategy, strategy) for strategy in rating.strategies]
                lines.append(f"策略：{'、'.join(cn_strs)}")

            if rating.fundamental:
                fundamental = rating.fundamental
                parts = []
                if fundamental.revenue_growth != 0:
                    parts.append(f"营收{'+' if fundamental.revenue_growth > 0 else ''}{fundamental.revenue_growth:.1f}%")
                if fundamental.profit_growth != 0:
                    parts.append(f"利润{'+' if fundamental.profit_growth > 0 else ''}{fundamental.profit_growth:.1f}%")
                if fundamental.roe != 0:
                    parts.append(f"ROE {fundamental.roe:.1f}%")
                if fundamental.pe_ttm != 0:
                    parts.append(f"PE {fundamental.pe_ttm:.1f}")
                if parts:
                    lines.append(f"基本面：{'，'.join(parts)}")
                if fundamental.risk_flags:
                    lines.append(f"风险：{' '.join(fundamental.risk_flags)}")

            if rating.sentiment:
                lines.append(f"舆情：{rating.sentiment.summary}")
                if rating.sentiment.headlines:
                    lines.append(f"热点：{'; '.join(rating.sentiment.headlines[:3])}")

            if rating.event:
                lines.append(f"事件：{rating.event.summary}")
                if rating.event.related_events:
                    lines.append(f"政策：{'; '.join(rating.event.related_events[:3])}")

            lines.append(f"[东方财富](https://quote.eastmoney.com/{em_code}.html)")

        lines.append("")
        lines.append("---")
        lines.append("AI 分析仅供参考，不构成投资建议。")

        self._send_markdown(
            f"AI选股报告 TOP{top_n} ({today})",
            "\n".join(lines),
            "comprehensive",
        )

    def send_backtest_report(self, results: list) -> None:
        """推送回测报告。"""
        today = date.today().strftime("%Y-%m-%d")

        lines = [
            "## Sequoia-X 策略回测报告",
            f"**日期：** {today}",
            "",
            "| 策略 | 胜率 | 盈亏比 | 累计收益 | 最大回撤 | 夏普 | 交易数 |",
            "|------|------|--------|----------|----------|------|--------|",
        ]

        for result in results:
            lines.append(
                f"| {result.strategy_name} | {result.win_rate:.1f}% | {result.profit_loss_ratio:.2f} | "
                f"{result.total_return:+.1f}% | {result.max_drawdown:.1f}% | "
                f"{result.sharpe_ratio:.2f} | {result.valid_trades} |"
            )

        lines.append("")
        for result in results:
            lines.append(f"**{result.strategy_name}**：{result.summary}")

        lines.append("")
        lines.append("回测结果仅供研究，不构成投资建议。")

        self._send_markdown(
            f"策略回测报告 ({today})",
            "\n".join(lines),
            "backtest",
        )

    def _send_markdown(self, title: str, text: str, webhook_key: str = "default") -> None:
        """发送 Markdown 消息到钉钉。"""
        url = _sign_url(self.webhook_url, self.secret)
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"钉钉推送成功 [{webhook_key}] {title}")
            else:
                logger.error(f"钉钉推送失败 [{webhook_key}] err={result}")
        except Exception as exc:
            logger.error(f"钉钉推送异常 [{webhook_key}] {exc}")
