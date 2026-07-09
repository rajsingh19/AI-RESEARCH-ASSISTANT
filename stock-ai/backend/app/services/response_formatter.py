"""
response_formatter.py — Format templates and instructions for LLM outputs based on financial intent.
"""
from typing import Optional, Dict

class ResponseFormatter:
    """Provides specific instructions and formatting templates for the LLM based on user intent."""

    TEMPLATES = {
        "metric_lookup": (
            "You are a concise financial assistant. The user is asking for a simple metric lookup.\n"
            "Format your response EXACTLY as follows, replacing placeholders with actual values. "
            "Do NOT include any summary, supporting evidence, news, confidence level, risk analysis, "
            "business overview, or investment disclaimer (unless strictly required by policy).\n\n"
            "[Full Company Name]\n"
            "[Metric 1 Name] (reporting period, e.g. FY2025 or Q1 FY2026): [Value 1]\n"
            "[Metric 2 Name] (reporting period, e.g. FY2025 or Q1 FY2026): [Value 2] (if requested)\n"
            "Source: [Source, e.g., Structured Financial Data (SQLite Database) or SQLite Financial Metrics]\n"
            "Latest Reported Period: [Reporting Period, e.g. FY2025 or Q1 FY2026]"
        ),
        "earnings_analysis": (
            "Format your response as a detailed Morgan Stanley/Goldman Sachs-style research note containing:\n"
            "- Executive Summary\n"
            "- Financial Highlights\n"
            "- Business Highlights\n"
            "- Segment Performance\n"
            "- Management Commentary\n"
            "- Challenges & Risks\n"
            "- Future Outlook\n"
            "- Sources & Confidence Level"
        ),
        "company_overview": (
            "Format your response as a comprehensive company summary containing:\n"
            "- Company Profile & Core Business\n"
            "- Key Operations & Sectors\n"
            "- Leadership & Competitors\n"
            "- Financial Standing Summary"
        ),
        "risk_analysis": (
            "Format your response as a dedicated risk assessment report containing:\n"
            "- Macroeconomic & Industry Risks\n"
            "- Operational & Supply Chain Risks\n"
            "- Financial & Leverage Risks\n"
            "- Risk Mitigation & Outlook"
        ),
        "comparison": (
            "Format your response as a side-by-side comparison report containing:\n"
            "- Comparative Performance Table / Summary\n"
            "- Operational Strengths Comparison\n"
            "- Financial Metric Comparison (Revenue, Profit, EPS, PE Ratios)\n"
            "- Valuation Assessment (Which appears more attractive)"
        ),
        "news": (
            "Format your response as a concise news summary report containing:\n"
            "- Recent Headline Bulletins\n"
            "- Key Operational Events & Announcements\n"
            "- Market Sentiment / Impact Assessment"
        ),
        "valuation": (
            "Format your response as a detailed valuation analysis report containing:\n"
            "- Pricing Multiples Analysis (P/E Ratio, Market Cap size)\n"
            "- Historical Averages comparison\n"
            "- Valuation Health Assessment (Undervalued / Overvalued signals)"
        ),
        "growth": (
            "Format your response as a growth analysis report containing:\n"
            "- Revenue & Profit Growth Trends (Past 5 Years review)\n"
            "- Operating Margin Expansion/Contraction trends\n"
            "- Key growth drivers & expansion metrics"
        )
    }

    @classmethod
    def is_simple_metric_lookup(cls, query: str) -> bool:
        """Determines if a query is a simple factual metric lookup or an analytical question."""
        normalized = query.lower().strip()
        
        # Keywords indicating analysis, comparison, or reports
        analytical = {
            "compare", "versus", "vs", "growth analysis", "trend", "growing",
            "why", "how", "analyze", "analysis", "swot", "performance", "outlook", "future",
            "valuation analysis", "risk", "risks", "should i", "growing?", "summarize",
            "buy", "sell", "good investment", "investment advice"
        }
        if any(kw in normalized for kw in analytical):
            return False
            
        # Common metric keywords
        metrics = {
            "revenue", "sales", "profit", "net profit", "income", "eps", "pe", 
            "pe ratio", "p/e", "market cap", "mcap", "dividend", "yield", 
            "dividend yield", "roe", "roce", "margin", "margins", "operating margin"
        }
        return any(m in normalized for m in metrics)

    @classmethod
    def get_formatting_instructions(cls, query: str, intent_value: str) -> str:
        """Returns the formatting instructions block for the LLM based on detected intent."""
        # 1. Check if simple metric lookup
        if cls.is_simple_metric_lookup(query):
            return cls.TEMPLATES["metric_lookup"]

        # 2. Determine formatting template from intent string
        intent_value = intent_value.lower()
        if "metric" in intent_value:
            # Fallback for metric questions that contain analytical words
            return cls.TEMPLATES["growth"]
        if "earnings_analysis" in intent_value:
            return cls.TEMPLATES["earnings_analysis"]
        if "overview" in intent_value:
            return cls.TEMPLATES["company_overview"]
        if "risk" in intent_value:
            return cls.TEMPLATES["risk_analysis"]
        if "comparison" in intent_value or "compare" in intent_value:
            return cls.TEMPLATES["comparison"]
        if "news" in intent_value:
            return cls.TEMPLATES["news"]
        if "valuation" in intent_value:
            return cls.TEMPLATES["valuation"]
        if "growth" in intent_value:
            return cls.TEMPLATES["growth"]
            
        return cls.TEMPLATES["company_overview"]
