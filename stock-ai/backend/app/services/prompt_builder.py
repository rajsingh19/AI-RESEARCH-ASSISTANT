"""
prompt_builder.py — Builds the final LLM prompt from HybridContext.

Sections:
  1. Structured Financial Data (SQLite)
  2. Annual Report / Filing Chunks (ChromaDB docs)
  3. Latest News (ChromaDB news) — includes freshness metadata
  4. Question

Uses news_prompt.txt when news_chunks present, hybrid_prompt.txt otherwise.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.models.chat import CompanySnapshot, DocumentChunk, MetricName, NewsChunk
from app.services.hybrid_retrieval_service import HybridContext
from app.services.financial_reasoning_service import FinancialReasoningContext

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
HYBRID_PROMPT_PATH = _PROMPTS_DIR / "hybrid_prompt.txt"
NEWS_PROMPT_PATH = _PROMPTS_DIR / "news_prompt.txt"

METRIC_LABELS: dict[str, str] = {
    MetricName.REVENUE: "Revenue",
    MetricName.PROFIT: "Profit",
    MetricName.EPS: "EPS",
    MetricName.PE_RATIO: "PE Ratio",
}


class PromptBuilder:
    def __init__(self, hybrid_template: str, news_template: str) -> None:
        self._hybrid = hybrid_template
        self._news = news_template

    def build(
        self,
        question: str,
        hybrid_context: HybridContext,
        reasoning_context: FinancialReasoningContext | None = None
    ) -> str:
        structured = self._build_structured(hybrid_context)
        
        # Append reasoning rules section to structured data parameter block (Problem 5)
        if reasoning_context and reasoning_context.intent != "unknown":
            reasoning_section = self._build_reasoning_section(reasoning_context)
            structured = f"{structured}\n\n{reasoning_section}"

        documents = self._build_documents(hybrid_context.document_chunks)

        if hybrid_context.news_chunks:
            news = self._build_news(hybrid_context.news_chunks)
            prompt = self._news.format(
                structured_financial_data=structured,
                retrieved_documents=documents,
                latest_news=news,
                question=question.strip(),
            )
            logger.info("PromptBuilder: news prompt. sql=%d docs=%d news=%d",
                        len(hybrid_context.companies), len(hybrid_context.document_chunks),
                        len(hybrid_context.news_chunks))
        else:
            prompt = self._hybrid.format(
                structured_financial_data=structured,
                retrieved_documents=documents,
                question=question.strip(),
            )
            logger.info("PromptBuilder: hybrid prompt. sql=%d docs=%d",
                        len(hybrid_context.companies), len(hybrid_context.document_chunks))
        return prompt

    def _build_reasoning_section(self, rc: FinancialReasoningContext) -> str:
        lines = [
            "=========================================",
            "CRITICAL FINANCIAL REASONING SYSTEM RULES",
            "=========================================",
            f"User is asking a stock analysis question related to: {rc.intent.value.upper()}.",
            "",
            "AVAILABLE METRICS (use only these, never invent or hallucinate data):",
        ]
        if rc.available_metrics:
            for m in rc.available_metrics:
                val = rc.metric_values.get(m)
                lines.append(f"  - {m}: {val}")
        else:
            lines.append("  - None")
            
        lines.append("")
        lines.append("MISSING METRICS (you must explicitly list these as unavailable to the user):")
        if rc.missing_metrics:
            for m in rc.missing_metrics:
                exp = rc.importance_explanations.get(m, "")
                lines.append(f"  - {m} | Importance: {exp}")
        else:
            lines.append("  - None")

        lines.append("")
        lines.append("STRICT LLM BEHAVIORAL DIRECTIVES:")
        lines.append("1. Data limitations mapping:")
        lines.append("   - Explain clearly what information is available.")
        lines.append("   - List exactly what required metrics are missing.")
        lines.append("   - Explain why the missing information is important to make a complete assessment.")
        lines.append("   - Cautiously state that there is insufficient evidence to make a definitive conclusion.")
        lines.append("2. Cautious Language requirement:")
        lines.append("   - Use words like: suggests, may indicate, could imply, appears, based on available information.")
        lines.append("   - NEVER use definitive words like: definitely, guaranteed, will, must, certainly.")
        lines.append("3. Advisory constraints:")
        lines.append("   - Do NOT provide buy, sell, or hold recommendations under any circumstances.")
        lines.append("   - Discuss strengths and weaknesses using available metrics and facts objectively.")
        lines.append("   - You MUST end your response with this disclaimer:")
        lines.append("     'This information is for educational purposes and should not be considered investment advice.'")
        lines.append("=========================================")
        return "\n".join(lines)

    def _build_structured(self, ctx: HybridContext) -> str:
        if not ctx.has_sql_data:
            return "No structured financial data available."
        lines: list[str] = []
        metrics = ctx.sql_context.requested_metrics or list(MetricName)
        
        # Access extra metadata if present
        meta_dict = getattr(ctx.sql_context, "company_metadata", {})
        hist_dict = getattr(ctx.sql_context, "company_history", {})
        div_dict = getattr(ctx.sql_context, "company_dividends", {})

        for company in ctx.companies:
            ticker = company.ticker.upper()
            lines.append(f"Company: {company.company_name} ({ticker})")
            
            # 1. Current metrics
            lines.append("  Current Financial Metrics:")
            for m in metrics:
                lines.append(f"    - {METRIC_LABELS.get(m, str(m))}: {self._fmt(m, company)}")
            
            # 2. Profile Metadata (Problem 2)
            meta = meta_dict.get(ticker)
            if meta:
                lines.append("  Company Metadata:")
                lines.append(f"    - Sector: {meta.get('sector') or 'N/A'}")
                lines.append(f"    - Industry: {meta.get('industry') or 'N/A'}")
                market_cap = meta.get('market_cap')
                lines.append(f"    - Market Cap: Rs. {market_cap:,.0f} crore" if market_cap else "    - Market Cap: N/A")
                lines.append(f"    - Headquarters: {meta.get('headquarters') or 'N/A'}")
                lines.append(f"    - CEO: {meta.get('ceo') or 'N/A'}")
                lines.append(f"    - Competitors: {', '.join(meta.get('competitors', [])) or 'N/A'}")
                lines.append(f"    - Website: {meta.get('website') or 'N/A'}")
                lines.append(f"    - Listing Exchange: {meta.get('listing_exchange') or 'N/A'}")
                lines.append(f"    - Country: {meta.get('country') or 'N/A'}")

            # 3. Financial History (Problem 3)
            history = hist_dict.get(ticker)
            if history:
                lines.append("  Historical Financials (Past 5 Years):")
                for h in history:
                    lines.append(
                        f"    - Year {h['year']}: Revenue: Rs. {h['revenue']:,.0f} crore | "
                        f"Profit: Rs. {h['profit']:,.0f} crore | EPS: {h['eps']:.2f} | "
                        f"Operating Margin: {h['operating_margin']:.1f}% | Net Margin: {h['net_margin']:.1f}% | "
                        f"ROE: {h['roe']:.1f}% | ROCE: {h['roce']:.1f}% | Dividend: Rs. {h['dividend']:.2f}"
                    )

            # 4. Dividend History (Problem 4)
            dividends = div_dict.get(ticker)
            if dividends:
                lines.append("  Dividend Payout History:")
                for d in dividends:
                    lines.append(f"    - Date: {d['date']} | Dividend Paid: Rs. {d['dividend']:.2f} | Yield: {d['yield']:.2f}%")

            lines.append("")

        if ctx.sql_context.analysis_notes:
            lines += ["Analysis Notes:"] + [f"  - {n}" for n in ctx.sql_context.analysis_notes] + [""]
        if ctx.sql_context.unavailable_identifiers:
            lines += ["Not found:"] + [f"  - {i}" for i in ctx.sql_context.unavailable_identifiers]
        return "\n".join(lines).strip()

    def _build_documents(self, chunks: list[DocumentChunk]) -> str:
        if not chunks:
            return "No document chunks retrieved."
        lines: list[str] = []
        for i, c in enumerate(chunks, 1):
            lines.append(f"[Doc {i}] Source: {c.document} | ID: {c.chunk_id}")
            lines.append(c.content.strip())
            lines.append("")
        return "\n".join(lines).strip()

    def _build_news(self, chunks: list[NewsChunk]) -> str:
        if not chunks:
            return "No recent news available."
        lines: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.article_id not in seen:
                lines.append(f"Title: {chunk.title}")
                lines.append(f"Source: {chunk.source}")
                if chunk.author:
                    lines.append(f"Author: {chunk.author}")
                lines.append(f"Published: {chunk.published_at}")
                lines.append(f"URL: {chunk.url}")
                seen.add(chunk.article_id)
            lines.append(f"Content: {chunk.content.strip()}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _fmt(metric: MetricName | str, company: CompanySnapshot) -> str:
        val = getattr(company, metric if isinstance(metric, str) else metric.value, None)
        if val is None:
            return "N/A"
        if metric in {MetricName.REVENUE, MetricName.PROFIT}:
            return f"Rs. {val:,.0f} crore"
        return f"{val:,.2f}".rstrip("0").rstrip(".")


@lru_cache(maxsize=1)
def get_prompt_builder() -> PromptBuilder:
    return PromptBuilder(
        hybrid_template=HYBRID_PROMPT_PATH.read_text(encoding="utf-8").strip(),
        news_template=NEWS_PROMPT_PATH.read_text(encoding="utf-8").strip(),
    )
