"""舆情分析模块：抓取新闻/研报/股吧情绪，判断市场关注度。"""

import re
import requests
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)

# 情绪词典
POSITIVE_WORDS = {
    "利好", "大涨", "涨停", "突破", "新高", "增长", "盈利", "增持", "回购",
    "超预期", "景气", "龙头", "爆发", "放量", "强势", "机构看好", "买入",
    "推荐", "上调", "加速", "翻倍", "暴涨", "拉升", "飙升", "创新高",
    "业绩预增", "订单", "中标", "战略合作", "重大突破",
}

NEGATIVE_WORDS = {
    "利空", "大跌", "跌停", "暴跌", "下滑", "亏损", "减持", "质押",
    "爆雷", "违规", "处罚", "退市", "风险", "下跌", "破位", "卖出",
    "下调", "业绩预减", "商誉减值", "财务造假", "立案调查", "诉讼",
    "债务违约", "资金链", "暂停上市", "实控人变更",
}


@dataclass
class SentimentScore:
    """舆情评分结果。"""
    code: str
    name: str = ""
    # 新闻数据
    news_count: int = 0           # 近期新闻数量
    research_count: int = 0       # 研报数量
    positive_count: int = 0       # 正面新闻数
    negative_count: int = 0       # 负面新闻数
    # 评分
    sentiment_score: float = 50.0   # 情绪分 0-100（50=中性）
    attention_score: float = 0.0    # 关注度 0-100
    total_score: float = 50.0       # 综合分 0-100
    # 摘要
    headlines: list = field(default_factory=list)   # 重要新闻标题
    summary: str = ""


class SentimentAnalyzer:
    """舆情分析器。"""

    def analyze(self, codes: list[str]) -> dict[str, SentimentScore]:
        """批量分析股票舆情。"""
        results = {}
        for code in codes:
            try:
                score = self._analyze_one(code)
                results[code] = score
                time.sleep(0.3)  # 限速
            except Exception as e:
                logger.warning(f"[{code}] 舆情分析失败: {e}")
                results[code] = SentimentScore(code=code, summary=f"数据获取失败")
        return results

    def _analyze_one(self, code: str) -> SentimentScore:
        """分析单只股票舆情。"""
        score = SentimentScore(code=code)

        # 1. 抓取东方财富新闻
        news_items = self._fetch_eastmoney_news(code)
        score.news_count = len(news_items)

        # 2. 情绪分析
        for item in news_items:
            title = item.get("title", "")
            pos = sum(1 for w in POSITIVE_WORDS if w in title)
            neg = sum(1 for w in NEGATIVE_WORDS if w in title)
            if pos > neg:
                score.positive_count += 1
            elif neg > pos:
                score.negative_count += 1
            score.headlines.append(title)

        # 3. 抓取研报
        try:
            research = self._fetch_research_report(code)
            score.research_count = research.get("count", 0)
        except Exception:
            pass

        # 4. 计算评分
        total_sentiments = score.positive_count + score.negative_count
        if total_sentiments > 0:
            score.sentiment_score = 50 + (score.positive_count - score.negative_count) / total_sentiments * 50
        else:
            score.sentiment_score = 50  # 中性

        # 关注度评分（新闻数量越多关注度越高）
        if score.news_count >= 20:
            score.attention_score = 100
        elif score.news_count >= 10:
            score.attention_score = 80
        elif score.news_count >= 5:
            score.attention_score = 60
        elif score.news_count >= 2:
            score.attention_score = 40
        else:
            score.attention_score = 20

        # 研报加分
        if score.research_count >= 3:
            score.attention_score = min(100, score.attention_score + 20)

        # 综合分 = 情绪 * 0.6 + 关注度 * 0.4
        score.total_score = score.sentiment_score * 0.6 + score.attention_score * 0.4

        # 生成摘要
        score.summary = self._build_summary(score)
        # 只保留前5条标题
        score.headlines = score.headlines[:5]

        return score

    def _fetch_eastmoney_news(self, code: str) -> list[dict]:
        """从东方财富抓取个股新闻。"""
        try:
            # 东方财富个股新闻 API
            prefix = "0" if code.startswith(("0", "3")) else "1"
            url = f"https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": "jQuery",
                "param": f'{{"uid":"","keyword":"{code}","type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr","param":{{"cmsArticleWebOld":{{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":20,"preTag":"<em>","postTag":"</em>"}}}}}}',
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://so.eastmoney.com/",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            text = resp.text

            # 解析 JSONP
            json_str = text[text.index("(") + 1: text.rindex(")")]
            import json
            data = json.loads(json_str)

            items = []
            result = data.get("result", {})
            cms = result.get("cmsArticleWebOld", [])
            # cms 可能是 list 或 dict
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

            return items[:20]
        except Exception as e:
            logger.debug(f"[{code}] 东方财富新闻获取失败: {e}")
            return []

    def _fetch_research_report(self, code: str) -> dict:
        """获取研报数据。"""
        try:
            url = "https://reportapi.eastmoney.com/report/list"
            params = {
                "industryCode": "*",
                "pageSize": 10,
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "endTime": datetime.now().strftime("%Y-%m-%d"),
                "pageNo": 1,
                "fields": "",
                "qType": 0,
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": 1,
                "pageNum": 1,
                "pageNumber": 1,
            }
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
            return {"count": data.get("hits", 0)}
        except Exception:
            return {"count": 0}

    @staticmethod
    def _build_summary(score: SentimentScore) -> str:
        """生成舆情摘要。"""
        parts = []

        if score.sentiment_score >= 70:
            parts.append("🟢 市场情绪偏正面")
        elif score.sentiment_score >= 55:
            parts.append("🟡 市场情绪中性偏正")
        elif score.sentiment_score >= 45:
            parts.append("⚪ 市场情绪中性")
        elif score.sentiment_score >= 30:
            parts.append("🟠 市场情绪偏负面")
        else:
            parts.append("🔴 市场情绪负面")

        if score.research_count >= 3:
            parts.append(f"近期{score.research_count}份研报覆盖")
        elif score.research_count >= 1:
            parts.append(f"近期{score.research_count}份研报")

        if score.news_count >= 10:
            parts.append(f"高关注度({score.news_count}条新闻)")

        return "，".join(parts) if parts else "关注度低"
