"""基本面分析模块：抓取财报数据，分析营收增速、盈利能力、财务风险。"""

import pandas as pd
import akshare as ak
from dataclasses import dataclass, field
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FundamentalScore:
    """基本面评分结果。"""
    code: str
    name: str = ""
    # 核心指标
    revenue_growth: float = 0.0      # 营收增速 (%)
    profit_growth: float = 0.0       # 净利润增速 (%)
    roe: float = 0.0                 # ROE (%)
    gross_margin: float = 0.0        # 毛利率 (%)
    debt_ratio: float = 0.0          # 资产负债率 (%)
    pe_ttm: float = 0.0              # 市盈率 TTM
    pb: float = 0.0                  # 市净率
    # 评分
    growth_score: float = 0.0        # 成长性 0-100
    profitability_score: float = 0.0 # 盈利能力 0-100
    safety_score: float = 0.0        # 财务安全 0-100
    valuation_score: float = 0.0     # 估值合理度 0-100
    total_score: float = 0.0         # 综合 0-100
    # 风险标记
    risk_flags: list = field(default_factory=list)
    summary: str = ""


class FundamentalAnalyzer:
    """基本面分析器。"""

    def analyze(self, codes: list[str]) -> dict[str, FundamentalScore]:
        """批量分析股票基本面，返回 {code: FundamentalScore}。"""
        results = {}
        # 获取实时行情（含 PE/PB）
        try:
            spot_df = ak.stock_zh_a_spot_em()
            spot_df["代码"] = spot_df["代码"].astype(str).str.zfill(6)
            spot_map = spot_df.set_index("代码").to_dict("index")
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")
            spot_map = {}

        for code in codes:
            try:
                score = self._analyze_one(code, spot_map.get(code, {}))
                results[code] = score
            except Exception as e:
                logger.warning(f"[{code}] 基本面分析失败: {e}")
                results[code] = FundamentalScore(code=code, summary=f"数据获取失败: {e}")

        return results

    def _analyze_one(self, code: str, spot_info: dict) -> FundamentalScore:
        """分析单只股票基本面。"""
        score = FundamentalScore(code=code)
        score.name = spot_info.get("名称", code)
        score.pe_ttm = self._safe_float(spot_info.get("市盈率-动态", 0))
        score.pb = self._safe_float(spot_info.get("市净率", 0))

        # 获取财务指标
        fin_data = self._get_financial_indicators(code)
        if fin_data:
            score.revenue_growth = fin_data.get("revenue_growth", 0)
            score.profit_growth = fin_data.get("profit_growth", 0)
            score.roe = fin_data.get("roe", 0)
            score.gross_margin = fin_data.get("gross_margin", 0)
            score.debt_ratio = fin_data.get("debt_ratio", 0)

        # 评分
        score.growth_score = self._score_growth(score.revenue_growth, score.profit_growth)
        score.profitability_score = self._score_profitability(score.roe, score.gross_margin)
        score.safety_score = self._score_safety(score.debt_ratio)
        score.valuation_score = self._score_valuation(score.pe_ttm, score.pb)

        # 加权总分
        score.total_score = (
            score.growth_score * 0.35
            + score.profitability_score * 0.25
            + score.safety_score * 0.20
            + score.valuation_score * 0.20
        )

        # 风险标记
        score.risk_flags = self._check_risks(score)
        score.summary = self._build_summary(score)

        return score

    def _get_financial_indicators(self, code: str) -> dict | None:
        """通过 akshare 获取财务指标。"""
        try:
            # 获取财务指标
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            if df is None or df.empty:
                return None

            # 取最近一期数据
            latest = df.iloc[0]
            result = {}

            # 营收增速
            for col in df.columns:
                col_lower = str(col).lower()
                if "营业" in str(col) and "增长" in str(col):
                    result["revenue_growth"] = self._safe_float(latest[col])
                elif "净利润" in str(col) and "增长" in str(col):
                    result["profit_growth"] = self._safe_float(latest[col])
                elif "roe" in col_lower or "净资产收益率" in str(col):
                    result["roe"] = self._safe_float(latest[col])
                elif "毛利率" in str(col):
                    result["gross_margin"] = self._safe_float(latest[col])
                elif "资产负债率" in str(col):
                    result["debt_ratio"] = self._safe_float(latest[col])

            return result
        except Exception as e:
            logger.debug(f"[{code}] akshare 财务指标获取失败: {e}")
            return None

    @staticmethod
    def _score_growth(rev_growth: float, profit_growth: float) -> float:
        """成长性评分 0-100。"""
        # 营收增速评分
        if rev_growth >= 50:
            rev_score = 100
        elif rev_growth >= 30:
            rev_score = 80
        elif rev_growth >= 15:
            rev_score = 60
        elif rev_growth >= 0:
            rev_score = 40
        elif rev_growth >= -15:
            rev_score = 20
        else:
            rev_score = 0

        # 利润增速评分
        if profit_growth >= 50:
            profit_score = 100
        elif profit_growth >= 30:
            profit_score = 80
        elif profit_growth >= 15:
            profit_score = 60
        elif profit_growth >= 0:
            profit_score = 40
        elif profit_growth >= -30:
            profit_score = 20
        else:
            profit_score = 0

        return rev_score * 0.4 + profit_score * 0.6

    @staticmethod
    def _score_profitability(roe: float, gross_margin: float) -> float:
        """盈利能力评分 0-100。"""
        # ROE 评分
        if roe >= 20:
            roe_score = 100
        elif roe >= 15:
            roe_score = 80
        elif roe >= 10:
            roe_score = 60
        elif roe >= 5:
            roe_score = 40
        else:
            roe_score = 20

        # 毛利率评分
        if gross_margin >= 60:
            gm_score = 100
        elif gross_margin >= 40:
            gm_score = 80
        elif gross_margin >= 25:
            gm_score = 60
        elif gross_margin >= 15:
            gm_score = 40
        else:
            gm_score = 20

        return roe_score * 0.6 + gm_score * 0.4

    @staticmethod
    def _score_safety(debt_ratio: float) -> float:
        """财务安全评分 0-100。负债率越低越安全。"""
        if debt_ratio <= 30:
            return 100
        elif debt_ratio <= 45:
            return 80
        elif debt_ratio <= 60:
            return 60
        elif debt_ratio <= 75:
            return 40
        else:
            return 20

    @staticmethod
    def _score_valuation(pe: float, pb: float) -> float:
        """估值合理度评分 0-100。"""
        # PE 评分（负 PE 说明亏损，给低分）
        if pe < 0:
            pe_score = 10
        elif pe <= 15:
            pe_score = 100
        elif pe <= 25:
            pe_score = 80
        elif pe <= 40:
            pe_score = 60
        elif pe <= 60:
            pe_score = 40
        else:
            pe_score = 20

        # PB 评分
        if pb <= 1:
            pb_score = 100
        elif pb <= 2:
            pb_score = 80
        elif pb <= 4:
            pb_score = 60
        elif pb <= 6:
            pb_score = 40
        else:
            pb_score = 20

        return pe_score * 0.6 + pb_score * 0.4

    @staticmethod
    def _check_risks(score: FundamentalScore) -> list[str]:
        """检查财务风险标记。"""
        flags = []
        if score.debt_ratio > 70:
            flags.append("⚠️ 高负债")
        if score.pe_ttm < 0:
            flags.append("🔴 亏损")
        if score.revenue_growth < -20:
            flags.append("📉 营收大幅下滑")
        if score.profit_growth < -50:
            flags.append("📉 利润暴跌")
        if score.roe < 3 and score.roe != 0:
            flags.append("⚡ ROE偏低")
        return flags

    @staticmethod
    def _build_summary(score: FundamentalScore) -> str:
        """生成一句话基本面摘要。"""
        parts = []
        if score.revenue_growth > 20:
            parts.append(f"营收+{score.revenue_growth:.0f}%")
        elif score.revenue_growth < -10:
            parts.append(f"营收{score.revenue_growth:.0f}%")

        if score.profit_growth > 30:
            parts.append(f"利润+{score.profit_growth:.0f}%")
        elif score.profit_growth < -20:
            parts.append(f"利润{score.profit_growth:.0f}%")

        if score.roe > 15:
            parts.append(f"ROE {score.roe:.1f}%")

        if score.risk_flags:
            parts.extend(score.risk_flags)

        return "，".join(parts) if parts else "数据不足"

    @staticmethod
    def _safe_float(val) -> float:
        """安全转换为 float。"""
        try:
            if pd.isna(val):
                return 0.0
            return float(val)
        except (ValueError, TypeError):
            return 0.0
