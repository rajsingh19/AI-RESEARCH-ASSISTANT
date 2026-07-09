"""
polygon.py — Polygon.io financial data provider.
Queries Polygon v3/reference/tickers details API and falls back
to Gemini-based extraction if key is missing or calls fail.
"""
from __future__ import annotations

import logging
import httpx
from typing import List
from pydantic import BaseModel
from google.genai import types

from app.providers.financial.base_provider import (
    FinancialDataProvider, CompanyProfilePayload, CompanyFinancialsPayload,
    CompanyHistoricalFinancialsPayload, CompanyDividendPayload,
    CompanyDocumentPayload, CompanyNewsPayload, MarketDataPayload
)
from app.services.ai_service import GeminiAIService

logger = logging.getLogger(__name__)


class PolygonProvider(FinancialDataProvider):
    """Retrieves corporate metrics from Polygon.io with automatic LLM fallbacks."""

    def __init__(self, ai_service: GeminiAIService, api_key: str | None = None) -> None:
        self._ai = ai_service
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Polygon"

    def get_company_profile(self, ticker: str) -> CompanyProfilePayload:
        logger.info("PolygonProvider: get_company_profile ticker=%s", ticker)
        
        if self._api_key:
            try:
                url = f"https://api.polygon.io/v3/reference/tickers/{ticker}?apiKey={self._api_key}"
                resp = httpx.get(url, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", {})
                    if results and "name" in results:
                        logger.info("PolygonProvider: Fetched ticker details from API for %s", ticker)
                        return CompanyProfilePayload(
                            company_name=results.get("name", ticker),
                            ticker=ticker,
                            sector=results.get("locale", "US"),
                            industry=results.get("sic_description", "General Business"),
                            market_cap=float(results.get("market_cap", 0.0) or 0.0),
                            headquarters=results.get("address", {}).get("city", "N/A"),
                            ceo=results.get("ceo", "N/A"),
                            competitors=self._generate_competitors_via_llm(ticker, results.get("name", ticker)),
                            website=results.get("homepage_url", "N/A"),
                            listing_exchange=results.get("primary_exchange", "N/A"),
                            country=results.get("locale", "US"),
                            business_summary=results.get("description")
                        )
            except Exception as exc:
                logger.error("PolygonProvider: get_company_profile failed: %s. Falling back.", exc)

        return self._compile_profile_via_llm(ticker)

    def get_financials(self, ticker: str) -> CompanyFinancialsPayload:
        logger.info("PolygonProvider: get_financials ticker=%s", ticker)
        return self._compile_financials_via_llm(ticker)

    def get_historical_financials(self, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        logger.info("PolygonProvider: get_historical_financials ticker=%s", ticker)
        return self._compile_history_via_llm(ticker)

    def get_dividend_history(self, ticker: str) -> list[CompanyDividendPayload]:
        logger.info("PolygonProvider: get_dividend_history ticker=%s", ticker)
        return self._compile_dividends_via_llm(ticker)

    def get_annual_reports(self, ticker: str) -> list[CompanyDocumentPayload]:
        logger.info("PolygonProvider: get_annual_reports ticker=%s", ticker)
        return self._compile_reports_via_llm(ticker)

    def get_news(self, ticker: str) -> list[CompanyNewsPayload]:
        logger.info("PolygonProvider: get_news ticker=%s", ticker)
        
        if self._api_key:
            try:
                url = f"https://api.polygon.io/v2/reference/news?ticker={ticker}&limit=5&apiKey={self._api_key}"
                resp = httpx.get(url, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        logger.info("PolygonProvider: Fetched news articles from API for %s", ticker)
                        news_list = []
                        for article in results:
                            news_list.append(CompanyNewsPayload(
                                title=article.get("title", ""),
                                source=article.get("publisher", {}).get("name", "Financial News"),
                                author=article.get("author"),
                                published_at=article.get("published_utc", ""),
                                url=article.get("article_url"),
                                content=article.get("description", "No content description available.")
                            ))
                        return news_list
            except Exception as exc:
                logger.error("PolygonProvider: get_news failed: %s. Falling back.", exc)

        return self._compile_news_via_llm(ticker)

    # ── Fallback Helpers ────────────────────────────────────────────────────────

    def _generate_competitors_via_llm(self, ticker: str, company_name: str) -> list[str]:
        class CompetitorList(BaseModel):
            tickers: list[str]

        prompt = f"List 4-6 competitor stock tickers for '{company_name}' ({ticker}). Return only JSON."
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=CompetitorList,
                ),
            )
            if response.parsed and isinstance(response.parsed, CompetitorList):
                return response.parsed.tickers
        except Exception:
            pass
        return []

    def _compile_profile_via_llm(self, ticker: str) -> CompanyProfilePayload:
        prompt = f"Research and compile metadata and competitors for '{ticker}'. Return only JSON matching CompanyProfilePayload."
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=CompanyProfilePayload,
            ),
        )
        return response.parsed  # type: ignore

    def _compile_financials_via_llm(self, ticker: str) -> CompanyFinancialsPayload:
        prompt = (
            f"Research and compile current financials (Rev, Profit, EPS, PE) for '{ticker}'. "
            f"Identify the latest reported period (year like 'FY2025' or quarter like 'Q1 FY2026' if it is more recent than the annual data) and set the 'reporting_period' field to this period. "
            f"If the company is Indian, scale all financial table 'revenue' and 'profit' values to Crores of Rupees. "
            f"Return JSON matching CompanyFinancialsPayload."
        )
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=CompanyFinancialsPayload,
            ),
        )
        return response.parsed  # type: ignore

    def _compile_history_via_llm(self, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        class HistoryWrapper(BaseModel):
            history: List[CompanyHistoricalFinancialsPayload]

        prompt = f"Research and compile a 5-year financial history sheet for '{ticker}'. Return JSON matching HistoryWrapper."
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=HistoryWrapper,
            ),
        )
        return response.parsed.history if response.parsed else []  # type: ignore

    def _compile_dividends_via_llm(self, ticker: str) -> list[CompanyDividendPayload]:
        class DividendWrapper(BaseModel):
            dividends: List[CompanyDividendPayload]

        prompt = f"Research and compile the last 5-10 dividends payout history for '{ticker}'. Return JSON matching DividendWrapper."
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=DividendWrapper,
            ),
        )
        return response.parsed.dividends if response.parsed else []  # type: ignore

    def _compile_reports_via_llm(self, ticker: str) -> list[CompanyDocumentPayload]:
        class DocumentsWrapper(BaseModel):
            documents: List[CompanyDocumentPayload]

        prompt = f"Compile qualitative text reports (Annual Report, MD&A, Risks) for '{ticker}'. Return JSON matching DocumentsWrapper."
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=DocumentsWrapper,
            ),
        )
        return response.parsed.documents if response.parsed else []  # type: ignore

    def _compile_news_via_llm(self, ticker: str) -> list[CompanyNewsPayload]:
        class NewsWrapper(BaseModel):
            news: List[CompanyNewsPayload]

        prompt = f"Compile the latest news articles for stock '{ticker}'. Return JSON matching NewsWrapper."
        response = self._ai.client.models.generate_content(
            model=self._ai.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=NewsWrapper,
            ),
        )
        return response.parsed.news if response.parsed else []  # type: ignore

    def get_live_market_data(self, ticker: str) -> MarketDataPayload | None:
        logger.info("PolygonProvider: get_live_market_data ticker=%s", ticker)
        prompt = (
            f"Research and compile real-time market data for stock ticker '{ticker}'. "
            f"Provide current price, currency, daily change, percentage change, day high, day low, previous close, "
            f"market status (open/closed), and last updated timestamp.\n"
            f"Respond only with JSON matching the MarketDataPayload schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert real-time stock market data feed. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=MarketDataPayload,
                ),
            )
            if response.parsed and isinstance(response.parsed, MarketDataPayload):
                return response.parsed
            raise RuntimeError("Failed to parse market data payload.")
        except Exception as exc:
            logger.error("PolygonProvider: get_live_market_data failed: %s", exc)
            return None
