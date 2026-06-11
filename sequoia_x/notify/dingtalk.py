"""钉钉通知模块：支持综合分析报告推送。"""

import hashlib
import hmac
import base64
import json
import time
import urllib.parse
from datetime import date

import requests
import baostock as bs

from sequoia_x.core.logger import get_logger
from sequoia_x.analysis.scorer import StockRating

logger = get_logger(__name__)

# 钉钉 Webhook 配置
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=3eb30f8d052e349dabf404d46d173ce3725a01434a21f4754c7ccc1bd1da8b80"
DINGTALK_SECRET = "SECc00e1486253015c8048903db9dbdb4c3e8b1a331212bd2859c232ff16e059e33"

# 策略中文名映射
STRATEGY_NAMES = {
    "MaVolumeStrategy": "均线放量",
    "TurtleTradeStrategy": "海龟突破",
    "HighTightFlagStrategy": "高位旗形",
    "LimitUpShakeoutStrategy": "涨停洗盘",
    "UptrendLimitDownStrategy": "趋势跌停",
    "RpsBreakoutStrategy": "RPS突破",
    "PrivatePlacementStrategy": "定增机会",
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
        self.webhook_url = DINGTALK_WEBHOOK
        self.secret = DINGTALK_SECRET

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
        """通过 baostock 批量查询股票名称。"""
        bs.login()
        mapping = {}
        for code in symbols:
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            rs = bs.query_stock_basic(code=f"{prefix}.{code}")
            while rs.next():
                row = rs.get_row_data()
                mapping[code] = row[1]
        bs.logout()
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

        lines = [
            f"## Sequoia-X AI 综合选股报告",
            f"**日期：** {today} | **分析：** {len(ratings)} 只 | **展示 TOP{top_n}**",
            "",
            "### 综合排名",
            "",
            "| # | 代码 | 名称 | 综合 | 技术 | 基本面 | 舆情 | 事件 | 资金 |",
            "|---|------|------|------|------|--------|------|------|------|",
        ]

        for r in top:
            lines.append(
                f"| {r.rank} | {r.code} | {r.name} | **{r.total_score:.1f}** | "
                f"{r.technical_score:.0f} | {r.fundamental_score:.0f} | "
                f"{r.sentiment_score:.0f} | {r.event_score:.0f} | "
                f"{r.capital_score:.0f} |"
            )

        # TOP5 详细分析
        lines.append("")
        lines.append("### TOP5 详细分析")

        for r in top[:5]:
            em_code = self._to_eastmoney_code(r.code)
            lines.append("")
            lines.append(f"**{r.rank}. {r.code} {r.name}** — 综合 {r.total_score:.1f} 分")

            if r.tags:
                lines.append(f"标签：{' '.join(r.tags)}")

            if r.strategies:
                cn_strs = [STRATEGY_NAMES.get(s, s) for s in r.strategies]
                lines.append(f"策略：{'、'.join(cn_strs)}")

            if r.fundamental:
                f = r.fundamental
                parts = []
                if f.revenue_growth != 0:
                    parts.append(f"营收{'+'if f.revenue_growth>0 else ''}{f.revenue_growth:.1f}%")
                if f.profit_growth != 0:
                    parts.append(f"利润{'+'if f.profit_growth>0 else ''}{f.profit_growth:.1f}%")
                if f.roe != 0:
                    parts.append(f"ROE {f.roe:.1f}%")
                if f.pe_ttm != 0:
                    parts.append(f"PE {f.pe_ttm:.1f}")
                if parts:
                    lines.append(f"基本面：{'，'.join(parts)}")
                if f.risk_flags:
                    lines.append(f"风险：{' '.join(f.risk_flags)}")

            if r.sentiment:
                lines.append(f"舆情：{r.sentiment.summary}")
                if r.sentiment.headlines:
                    lines.append(f"热点：{'; '.join(r.sentiment.headlines[:3])}")

            if r.event:
                lines.append(f"事件：{r.event.summary}")
                if r.event.related_events:
                    lines.append(f"政策：{'; '.join(r.event.related_events[:3])}")

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
        from sequoia_x.analysis.backtest import BacktestResult
        from sequoia_x.core.logger import get_logger
        bt_logger = get_logger(__name__)

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")

        lines = [
            "## Sequoia-X 策略回测报告",
            f"**日期：** {today}",
            "",
            "| 策略 | 胜率 | 盈亏比 | 累计收益 | 最大回撤 | 夏普 | 交易数 |",
            "|------|------|--------|----------|----------|------|--------|",
        ]

        for r in results:
            lines.append(
                f"| {r.strategy_name} | {r.win_rate:.1f}% | {r.profit_loss_ratio:.2f} | "
                f"{r.total_return:+.1f}% | {r.max_drawdown:.1f}% | "
                f"{r.sharpe_ratio:.2f} | {r.valid_trades} |"
            )

        lines.append("")
        for r in results:
            lines.append(f"**{r.strategy_name}**：{r.summary}")

        lines.append("")
        lines.append("---")
        lines.append("回测数据仅供参考，历史表现不代表未来收益。")

        self._send_markdown(f"回测报告 ({today})", "\n".join(lines), "backtest")

    def _send_markdown(self, title: str, markdown_text: str, webhook_key: str = "default") -> None:
        """发送 Markdown 消息到钉钉。"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown_text,
            },
        }

        url = _sign_url(self.webhook_url, self.secret)

        try:
            resp = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            resp_json = resp.json()

            if resp.status_code != 200 or resp_json.get("errcode") != 0:
                logger.error(f"钉钉推送失败 [{webhook_key}] HTTP={resp.status_code} 响应={resp.text}")
            else:
                logger.info(f"钉钉推送成功 [{webhook_key}]")
        except requests.RequestException as exc:
            logger.error(f"钉钉推送异常 [{webhook_key}]：{exc}")
