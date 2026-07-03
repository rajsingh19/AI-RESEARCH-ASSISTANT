from __future__ import annotations

import logging
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Dict, List

from app.models.chat import RetrievalContext

logger = logging.getLogger(__name__)


class FinancialReasoningIntent(str, Enum):
    VALUATION = "valuation"
    GROWTH = "growth"
    PROFITABILITY = "profitability"
    RISK = "risk"
    LIQUIDITY = "liquidity"
    DIVIDEND = "dividend"
    UNKNOWN = "unknown"


# Define financial importance guidelines for missing parameters
METRIC_IMPORTANCE: Dict[str, str] = {
    "pe_ratio": "Price-to-Earnings Ratio is crucial to evaluate current valuation relative to earnings power.",
    "pb_ratio": "Price-to-Book Ratio measures valuation relative to tangible asset net worth.",
    "peg_ratio": "Price-to-Earnings-to-Growth Ratio adjusts valuation for expected earnings expansion rate.",
    "industry_pe": "Industry Average PE sets the benchmark baseline for sector peer valuation comparison.",
    "historical_pe": "Historical PE trends verify if the stock is trading above or below its own normalized ranges.",
    "revenue_growth": "Year-over-Year Revenue Growth confirms top-line expansion and market demand trends.",
    "profit_growth": "Net Profit Growth indicates bottom-line profitability expansion over time.",
    "eps_growth": "Earnings Per Share Growth measures return growth on a per-share basis, indicating equity dilution impact.",
    "operating_margin": "Operating Margin trends show operational efficiency and pricing power stability.",
    "net_margin": "Net Margin indicates final profitability after all overhead expenses and interest costs.",
    "roe": "Return on Equity (ROE) measures how efficiently management generates profit from shareholder equity.",
    "roce": "Return on Capital Employed (ROCE) tracks capital efficiency across both debt and equity funding.",
    "debt_to_equity": "Debt-to-Equity Ratio measures capital leverage structure and financial solvency risks.",
    "interest_coverage": "Interest Coverage Ratio measures the safety cushion to pay finance charges from operating profits.",
    "current_ratio": "Current Ratio evaluates short-term capability to pay current obligations using current assets.",
    "quick_ratio": "Quick Ratio (Acid-Test) measures immediate short-term liquidity excluding inventory assets.",
    "working_capital": "Working Capital verifies net operational liquidity buffer available for day-to-day operations.",
    "dividend_history": "Dividend History confirms consistency of payout habits across previous market cycles.",
    "dividend_yield": "Dividend Yield computes the cash return rate on investment from payouts.",
    "dividend_payout_ratio": "Dividend Payout Ratio checks safety margins, measuring what percentage of earnings are distributed."
}


class FinancialReasoningContext(BaseModel):
    intent: FinancialReasoningIntent
    available_metrics: List[str] = Field(default_factory=list)
    missing_metrics: List[str] = Field(default_factory=list)
    metric_values: Dict[str, Any] = Field(default_factory=dict)
    importance_explanations: Dict[str, str] = Field(default_factory=dict)


class FinancialReasoningService:
    """Classifies valuation/health questions and generates available/missing indicators lists."""

    @staticmethod
    def detect_intent(query: str) -> FinancialReasoningIntent:
        normalized = query.lower()
        
        valuation_keywords = {"undervalued", "overvalued", "expensive", "cheap", "valuation", "pricing", "attractive", "fair value", "buy tcs", "buy infy", "should i buy", "recommendation"}
        if any(kw in normalized for kw in valuation_keywords):
            return FinancialReasoningIntent.VALUATION
            
        growth_keywords = {"growth", "growing", "expansion", "trend", "grow"}
        if any(kw in normalized for kw in growth_keywords):
            return FinancialReasoningIntent.GROWTH
            
        profitability_keywords = {"profitable", "profitability", "margins", "roe", "roce", "strong", "weak", "financially strong", "financial health"}
        if any(kw in normalized for kw in profitability_keywords):
            return FinancialReasoningIntent.PROFITABILITY
            
        risk_keywords = {"debt", "risk", "leverage", "default", "interest coverage", "solvency"}
        if any(kw in normalized for kw in risk_keywords):
            return FinancialReasoningIntent.RISK
            
        liquidity_keywords = {"cash flow", "liquidity", "current ratio", "quick ratio", "working capital"}
        if any(kw in normalized for kw in liquidity_keywords):
            return FinancialReasoningIntent.LIQUIDITY
            
        dividend_keywords = {"dividend", "yield", "payout", "dividends"}
        if any(kw in normalized for kw in dividend_keywords):
            return FinancialReasoningIntent.DIVIDEND
            
        return FinancialReasoningIntent.UNKNOWN

    def analyze(self, query: str, ctx: RetrievalContext) -> FinancialReasoningContext:
        """
        Runs reasoning analysis on the query and database retrieval context.
        """
        intent = self.detect_intent(query)
        if intent == FinancialReasoningIntent.UNKNOWN:
            return FinancialReasoningContext(intent=intent)

        # 1. Define required metrics for the intent
        required = []
        if intent == FinancialReasoningIntent.VALUATION:
            required = ["pe_ratio", "pb_ratio", "peg_ratio", "industry_pe", "historical_pe"]
        elif intent == FinancialReasoningIntent.GROWTH:
            required = ["revenue_growth", "profit_growth", "eps_growth", "operating_margin"]
        elif intent == FinancialReasoningIntent.PROFITABILITY:
            required = ["roe", "roce", "operating_margin", "net_margin"]
        elif intent == FinancialReasoningIntent.RISK:
            required = ["debt_to_equity", "interest_coverage", "current_ratio"]
        elif intent == FinancialReasoningIntent.LIQUIDITY:
            required = ["current_ratio", "quick_ratio", "working_capital"]
        elif intent == FinancialReasoningIntent.DIVIDEND:
            required = ["dividend_history", "dividend_yield", "dividend_payout_ratio"]

        available = []
        missing = []
        metric_values = {}

        # Look up tickers from the context
        sql_ctx = getattr(ctx, "sql_context", ctx)
        tickers = list(getattr(sql_ctx, "company_metadata", {}).keys())
        ticker = tickers[0] if tickers else None

        if ticker:
            # Current snapshot metrics
            comp_snap = next((c for c in ctx.companies if c.ticker.upper() == ticker.upper()), None)
            
            # Fetch arrays from retrieval context
            meta = getattr(sql_ctx, "company_metadata", {}).get(ticker, {})
            history = getattr(sql_ctx, "company_history", {}).get(ticker, [])
            dividends = getattr(sql_ctx, "company_dividends", {}).get(ticker, [])

            # Check and calculate required metrics
            for m in required:
                val = None
                
                # Check PE Ratio
                if m == "pe_ratio" and comp_snap and comp_snap.pe_ratio:
                    val = comp_snap.pe_ratio
                    
                # Check historical operating margins
                elif m == "operating_margin" and history:
                    val = [f"{h['year']}: {h['operating_margin']:.1f}%" for h in history]
                    
                # Check net margins
                elif m == "net_margin" and history:
                    val = [f"{h['year']}: {h['net_margin']:.1f}%" for h in history]

                # Check ROE
                elif m == "roe" and history:
                    val = [f"{h['year']}: {h['roe']:.1f}%" for h in history]

                # Check ROCE
                elif m == "roce" and history:
                    val = [f"{h['year']}: {h['roce']:.1f}%" for h in history]

                # Check Dividend Yield
                elif m == "dividend_yield" and dividends:
                    val = f"{dividends[0]['yield']:.2f}%" if 'yield' in dividends[0] else None

                # Check Dividend History
                elif m == "dividend_history" and dividends:
                    val = [f"{d['date']}: Rs. {d['dividend']:.2f}" for d in dividends[:5]]

                # Calculate YoY Revenue Growth
                elif m == "revenue_growth" and history and len(history) >= 2:
                    yoy_growth = []
                    for i in range(1, len(history)):
                        prev = history[i-1]["revenue"]
                        curr = history[i]["revenue"]
                        if prev > 0:
                            pct = ((curr - prev) / prev) * 100.0
                            yoy_growth.append(f"{history[i]['year']}: {pct:+.1f}%")
                    if yoy_growth:
                        val = yoy_growth

                # Calculate YoY Profit Growth
                elif m == "profit_growth" and history and len(history) >= 2:
                    yoy_growth = []
                    for i in range(1, len(history)):
                        prev = history[i-1]["profit"]
                        curr = history[i]["profit"]
                        if prev > 0:
                            pct = ((curr - prev) / prev) * 100.0
                            yoy_growth.append(f"{history[i]['year']}: {pct:+.1f}%")
                    if yoy_growth:
                        val = yoy_growth

                # Calculate YoY EPS Growth
                elif m == "eps_growth" and history and len(history) >= 2:
                    yoy_growth = []
                    for i in range(1, len(history)):
                        prev = history[i-1]["eps"]
                        curr = history[i]["eps"]
                        if prev > 0:
                            pct = ((curr - prev) / prev) * 100.0
                            yoy_growth.append(f"{history[i]['year']}: {pct:+.1f}%")
                    if yoy_growth:
                        val = yoy_growth

                # If found, add to available, else missing
                if val is not None:
                    available.append(m)
                    metric_values[m] = val
                else:
                    missing.append(m)
        else:
            # If no ticker, everything required is missing
            missing = list(required)

        # Extract explanations for missing items
        importance_explanations = {
            m: METRIC_IMPORTANCE.get(m, "This metric provides extra dimensions to analyze core capital performance.")
            for m in missing
        }

        logger.info("FinancialReasoningService: Intent=%s | Available=%s | Missing=%s",
                    intent.value, available, missing)

        return FinancialReasoningContext(
            intent=intent,
            available_metrics=available,
            missing_metrics=missing,
            metric_values=metric_values,
            importance_explanations=importance_explanations
        )
