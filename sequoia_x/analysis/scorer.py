"""综合打分模块：多维度加权评分，输出最终排名。"""

from dataclasses import dataclass, field
from sequoia_x.core.logger import get_logger
from sequoia_x.analysis.fundamental import FundamentalScore
from sequoia_x.analysis.sentiment import SentimentScore
from sequoia_x.analysis.event import EventImpact

logger = get_logger(__name__)


@dataclass
class StockRating:
    """综合评分结果。"""
    code: str
    name: str = ""
    # 各维度分数 (0-100)
    technical_score: float = 50.0    # 技术面（来自策略信号强度）
    fundamental_score: float = 50.0  # 基本面
    sentiment_score: float = 50.0    # 舆情面
    event_score: float = 50.0        # 事件驱动
    capital_score: float = 50.0      # 资金面（成交量/换手率）
    # 综合
    total_score: float = 50.0        # 加权总分
    rank: int = 0                    # 排名
    # 标签
    tags: list = field(default_factory=list)  # ["高成长", "低估值", "机构关注"]
    strategies: list = field(default_factory=list)  # 命中的策略列表
    # 摘要
    summary: str = ""
    # 原始数据
    fundamental: FundamentalScore | None = None
    sentiment: SentimentScore | None = None
    event: EventImpact | None = None


# 各维度权重
WEIGHTS = {
    "technical": 0.30,    # 技术面
    "fundamental": 0.25,  # 基本面
    "sentiment": 0.15,    # 舆情
    "event": 0.15,        # 事件驱动
    "capital": 0.15,      # 资金面
}


class ComprehensiveScorer:
    """综合打分器。"""

    def score(
        self,
        codes: list[str],
        strategy_hits: dict[str, list[str]],  # {code: [策略名列表]}
        technical_scores: dict[str, float],   # {code: 技术分}
        fundamental_scores: dict[str, FundamentalScore],
        sentiment_scores: dict[str, SentimentScore],
        event_scores: dict[str, EventImpact],
        capital_scores: dict[str, float],     # {code: 资金面分}
    ) -> list[StockRating]:
        """综合评分并排名。"""
        ratings = []

        for code in codes:
            rating = StockRating(code=code)

            # 技术面
            rating.technical_score = technical_scores.get(code, 50.0)
            rating.strategies = strategy_hits.get(code, [])

            # 基本面
            fund = fundamental_scores.get(code)
            if fund:
                rating.fundamental_score = fund.total_score
                rating.name = fund.name
                rating.fundamental = fund

            # 舆情
            sent = sentiment_scores.get(code)
            if sent:
                rating.sentiment_score = sent.total_score
                if not rating.name:
                    rating.name = sent.code
                rating.sentiment = sent

            # 事件
            evt = event_scores.get(code)
            if evt:
                rating.event_score = evt.total_score
                if not rating.name:
                    rating.name = evt.name
                rating.event = evt

            # 资金面
            rating.capital_score = capital_scores.get(code, 50.0)

            # 加权总分
            rating.total_score = (
                rating.technical_score * WEIGHTS["technical"]
                + rating.fundamental_score * WEIGHTS["fundamental"]
                + rating.sentiment_score * WEIGHTS["sentiment"]
                + rating.event_score * WEIGHTS["event"]
                + rating.capital_score * WEIGHTS["capital"]
            )

            # 生成标签
            rating.tags = self._generate_tags(rating)

            # 生成摘要
            rating.summary = self._build_summary(rating)

            ratings.append(rating)

        # 按总分排序
        ratings.sort(key=lambda r: r.total_score, reverse=True)
        for i, r in enumerate(ratings):
            r.rank = i + 1

        return ratings

    @staticmethod
    def _generate_tags(rating: StockRating) -> list[str]:
        """根据各维度分数生成标签。"""
        tags = []

        # 技术面标签
        if rating.technical_score >= 80:
            tags.append("🔥 强势信号")

        # 基本面标签
        if rating.fundamental:
            if rating.fundamental.growth_score >= 80:
                tags.append("📈 高成长")
            if rating.fundamental.valuation_score >= 80:
                tags.append("💰 低估值")
            if rating.fundamental.risk_flags:
                tags.append("⚠️ " + rating.fundamental.risk_flags[0])

        # 舆情标签
        if rating.sentiment:
            if rating.sentiment.attention_score >= 80:
                tags.append("👁️ 高关注")
            if rating.sentiment.sentiment_score >= 70:
                tags.append("😊 情绪正面")
            elif rating.sentiment.sentiment_score <= 30:
                tags.append("😟 情绪负面")

        # 事件标签
        if rating.event:
            if rating.event.policy_score >= 70:
                tags.append("📋 政策利好")

        # 多策略共振
        if len(rating.strategies) >= 3:
            tags.append("🎯 多策略共振")
        elif len(rating.strategies) >= 2:
            tags.append("🎯 双策略共振")

        return tags

    @staticmethod
    def _build_summary(rating: StockRating) -> str:
        """生成一句话综合摘要。"""
        parts = []

        if rating.strategies:
            parts.append(f"命中{len(rating.strategies)}个策略")

        if rating.fundamental and rating.fundamental.summary:
            parts.append(rating.fundamental.summary)

        if rating.sentiment and rating.sentiment.summary:
            parts.append(rating.sentiment.summary)

        if rating.event and rating.event.summary:
            parts.append(rating.event.summary)

        return " | ".join(parts[:3]) if parts else "综合评估中"
