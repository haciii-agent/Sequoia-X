"""事件解读模块：抓取行业/政策新闻，分析对个股的影响程度。"""

import re
import json
import requests
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

# 行业关键词映射（股票行业 → 政策关键词）
INDUSTRY_KEYWORDS = {
    "半导体": ["芯片", "半导体", "集成电路", "光刻", "晶圆", "EDA"],
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电池", "充电桩"],
    "医药": ["医药", "医疗", "创新药", "集采", "医保", "生物"],
    "消费": ["消费", "零售", "白酒", "食品", "餐饮", "免税"],
    "房地产": ["房地产", "楼市", "地产", "房价", "限购", "房贷"],
    "金融": ["银行", "券商", "保险", "金融", "降息", "降准"],
    "科技": ["人工智能", "AI", "大模型", "算力", "数字经济", "数据"],
    "军工": ["军工", "国防", "航天", "导弹", "航空", "卫星"],
    "汽车": ["汽车", "新能源车", "智能驾驶", "自动驾驶", "充电"],
    "基建": ["基建", "水利", "铁路", "公路", "新型城镇化"],
}


@dataclass
class EventImpact:
    """事件影响评估结果。"""
    code: str
    name: str
    industry: str = ""
    # 事件数据
    related_events: list = field(default_factory=list)  # 相关事件
    policy_score: float = 50.0    # 政策面评分 0-100
    industry_score: float = 50.0  # 行业景气度 0-100
    total_score: float = 50.0     # 综合分 0-100
    summary: str = ""


class EventAnalyzer:
    """事件解读分析器。"""

    def __init__(self):
        self._industry_cache: dict[str, str] = {}

    def analyze(self, codes: list[str]) -> dict[str, EventImpact]:
        """批量分析事件影响。"""
        results = {}

        # 先获取个股行业信息
        self._load_industry_map(codes)

        # 抓取最新宏观政策新闻
        macro_news = self._fetch_macro_news()

        _consecutive_failures = 0
        _network_down = False
        for code in codes:
            try:
                if _network_down:
                    results[code] = EventImpact(code=code, name=code, summary="网络不可用，跳过")
                    continue
                impact = self._analyze_one(code, macro_news)
                results[code] = impact
                _consecutive_failures = 0
            except Exception as e:
                _consecutive_failures += 1
                if _consecutive_failures >= 3:
                    _network_down = True
                    logger.warning("连续3次事件分析失败，跳过剩余")
                logger.debug(f"[{code}] 事件分析失败: {e}")
                results[code] = EventImpact(code=code, name=code, summary="分析失败")

        return results

    def _load_industry_map(self, codes: list[str]):
        """批量获取股票所属行业。"""
        try:
            import akshare as ak
            spot_df = ak.stock_zh_a_spot_em()
            spot_df["代码"] = spot_df["代码"].astype(str).str.zfill(6)
            for _, row in spot_df[spot_df["代码"].isin(codes)].iterrows():
                self._industry_cache[row["代码"]] = ""
        except Exception:
            pass

        # 通过 baostock 获取行业
        try:
            import baostock as bs
            bs.login()
            for code in codes:
                if code not in self._industry_cache:
                    continue
                prefix = "sh" if code.startswith(("6", "9")) else "sz"
                rs = bs.query_stock_industry(code=f"{prefix}.{code}")
                while rs.next():
                    row = rs.get_row_data()
                    if len(row) > 1:
                        self._industry_cache[code] = row[1]
                        break
            bs.logout()
        except Exception as e:
            logger.debug(f"行业数据获取失败: {e}")

    def _analyze_one(self, code: str, macro_news: list[dict]) -> EventImpact:
        """分析单只股票的事件影响。"""
        industry = self._industry_cache.get(code, "")
        impact = EventImpact(code=code, name=code, industry=industry)

        # 1. 匹配宏观政策新闻
        related = []
        for news in macro_news:
            title = news.get("title", "")
            # 检查是否与该股票行业相关
            keywords = self._get_industry_keywords(industry)
            if any(kw in title for kw in keywords):
                related.append(news)

        impact.related_events = [e.get("title", "") for e in related[:5]]

        # 2. 政策面评分
        if related:
            pos, neg = 0, 0
            for event in related:
                title = event.get("title", "")
                if any(w in title for w in ["利好", "支持", "补贴", "鼓励", "促进", "加快"]):
                    pos += 1
                elif any(w in title for w in ["利空", "限制", "整治", "打压", "收紧", "禁止"]):
                    neg += 1

            if pos > neg:
                impact.policy_score = 60 + min(30, (pos - neg) * 10)
            elif neg > pos:
                impact.policy_score = 40 - min(30, (neg - pos) * 10)
            else:
                impact.policy_score = 50
        else:
            impact.policy_score = 50  # 无明显政策影响

        # 3. 行业景气度评分（基于行业关键词出现频率）
        industry_freq = sum(
            1 for news in macro_news
            if any(kw in news.get("title", "") for kw in self._get_industry_keywords(industry))
        )
        if industry_freq >= 10:
            impact.industry_score = 80
        elif industry_freq >= 5:
            impact.industry_score = 65
        elif industry_freq >= 2:
            impact.industry_score = 55
        else:
            impact.industry_score = 45

        # 4. 综合分
        impact.total_score = impact.policy_score * 0.5 + impact.industry_score * 0.5
        impact.summary = self._build_summary(impact)

        return impact

    def _get_industry_keywords(self, industry: str) -> list[str]:
        """根据行业获取相关关键词。"""
        for key, keywords in INDUSTRY_KEYWORDS.items():
            if key in industry:
                return keywords
        # 默认返回通用关键词
        return [industry] if industry else []

    def _fetch_macro_news(self) -> list[dict]:
        """抓取宏观/政策新闻。"""
        try:
            url = "https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": "jQuery",
                "param": json.dumps({
                    "uid": "",
                    "keyword": "A股 政策 利好",
                    "type": ["cmsArticleWebOld"],
                    "client": "web",
                    "clientType": "web",
                    "clientVersion": "curr",
                    "param": {
                        "cmsArticleWebOld": {
                            "searchScope": "default",
                            "sort": "default",
                            "pageIndex": 1,
                            "pageSize": 30,
                        }
                    },
                }),
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://so.eastmoney.com/",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=3)
            text = resp.text
            json_str = text[text.index("(") + 1: text.rindex(")")]
            data = json.loads(json_str)

            items = []
            result = data.get("result", {})
            cms = result.get("cmsArticleWebOld", [])
            if isinstance(cms, list):
                raw_list = cms
            elif isinstance(cms, dict):
                raw_list = cms.get("list", [])
            else:
                raw_list = []

            for item in raw_list:
                if isinstance(item, dict):
                    title = re.sub(r"<[^>]+>", "", str(item.get("title", "")))
                    items.append({"title": title, "date": item.get("date", "")})

            return items
        except Exception as e:
            logger.debug(f"宏观新闻获取失败: {e}")
            return []

    @staticmethod
    def _build_summary(impact: EventImpact) -> str:
        """生成事件影响摘要。"""
        parts = []

        if impact.related_events:
            parts.append(f"关联{len(impact.related_events)}条政策新闻")

        if impact.policy_score >= 70:
            parts.append("政策面偏利好")
        elif impact.policy_score <= 30:
            parts.append("政策面偏利空")

        if impact.industry_score >= 70:
            parts.append(f"{impact.industry}行业热度高")
        elif impact.industry_score <= 40:
            parts.append(f"{impact.industry}行业关注度低")

        return "，".join(parts) if parts else "无明显事件驱动"
