"""钉钉通知模块：将选股结果通过 Webhook 推送至钉钉群（加签方式）。"""

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
        """纯数字代码转东方财富格式：6开头→sh，其余→sz/bj。"""
        if code.startswith("6"):
            return f"sh{code}"
        elif code.startswith(("4", "8")):
            return f"bj{code}"
        return f"sz{code}"

    @staticmethod
    def _get_stock_info(symbols: list[str]) -> dict[str, dict]:
        """通过 baostock 批量查询股票名称和行业。"""
        bs.login()
        mapping = {}
        for code in symbols:
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            rs = bs.query_stock_basic(code=f"{prefix}.{code}")
            while rs.next():
                row = rs.get_row_data()
                mapping[code] = {"name": row[1], "industry": row[4] if len(row) > 4 else ""}
        bs.logout()
        return mapping

    def _build_markdown(
        self,
        symbols: list[str],
        strategy_name: str,
        reasons: dict[str, str] | None = None,
    ) -> str:
        """构建 Markdown 格式消息体。"""
        today = date.today().strftime("%Y-%m-%d")
        cn_name = STRATEGY_NAMES.get(strategy_name, strategy_name)
        info = self._get_stock_info(symbols)

        lines = [
            "## 📈 Sequoia-X 选股播报",
            f"**策略：** {cn_name}",
            f"**日期：** {today}",
            f"**选股数量：** {len(symbols)}",
            "",
            "| 代码 | 名称 | 行业 | 链接 |",
            "|------|------|------|------|",
        ]

        for code in symbols:
            em_code = self._to_eastmoney_code(code)
            name = info.get(code, {}).get("name", code)
            industry = info.get(code, {}).get("industry", "")
            lines.append(f"| {code} | {name} | {industry} | [东方财富](https://quote.eastmoney.com/{em_code}.html) |")

        # 选股理由
        if reasons:
            lines.append("")
            lines.append("### 📋 选股理由")
            for code in symbols:
                reason = reasons.get(code, "")
                if reason:
                    name = info.get(code, {}).get("name", code)
                    lines.append(f"- **{code} {name}**：{reason}")

        return "\n".join(lines)

    def send(
        self,
        symbols: list[str],
        strategy_name: str,
        webhook_key: str = "default",
        reasons: dict[str, str] | None = None,
    ) -> None:
        """推送选股结果到钉钉群。"""
        if not symbols:
            logger.info(f"钉钉推送 [{webhook_key}] 无选股结果，跳过")
            return

        markdown_text = self._build_markdown(symbols, strategy_name, reasons)

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"📈 {STRATEGY_NAMES.get(strategy_name, strategy_name)} 选出 {len(symbols)} 只",
                "text": markdown_text,
            },
        }

        url = _sign_url(self.webhook_url, self.secret)

        try:
            resp = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp_json = resp.json()

            if resp.status_code != 200 or resp_json.get("errcode") != 0:
                logger.error(
                    f"钉钉推送失败 [{webhook_key}] "
                    f"HTTP={resp.status_code} 响应={resp.text}"
                )
            else:
                logger.info(f"钉钉推送成功 [{webhook_key}]，共 {len(symbols)} 只股票")

        except requests.RequestException as exc:
            logger.error(f"钉钉推送异常 [{webhook_key}]：{exc}")
