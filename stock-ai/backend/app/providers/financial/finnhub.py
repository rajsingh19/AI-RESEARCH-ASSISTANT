"""
finnhub.py — Finnhub financial data provider.
Queries Finnhub endpoints (stock/profile2, stock/metric) and falls back
to Gemini-based extraction if rate-limited or key is missing.
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
    CompanyDocumentPayload, CompanyNewsPayload
)
from app.services.ai_service import GeminiAIService

logger = logging.getLogger(__name__)


class FinnhubProvider(FinancialDataProvider):
    """Retrieves corporate metrics from Finnhub with automatic LLM fallbacks."""

    def __init__(self, ai_service: GeminiAIService, api_key: str | None = None) -> None:
        self._ai = ai_service
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Finnhub"

    def get_company_profile(self, ticker: str) -> CompanyProfilePayload:
        logger.info("FinnhubProvider: get_company_profile ticker=%s", ticker)
        
        if self._api_key:
            try:
                headers = {"X-Finnhub-Token": self._api_key}
                url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}"
                resp = httpx.get(url, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and "name" in data:
                        logger.info("FinnhubProvider: Fetched profile from API for %s", ticker)
                        return CompanyProfilePayload(
                            company_name=data.get("name", ticker),
                            ticker=ticker,
                            sector=data.get("finnhubIndustry"),
                            industry=data.get("finnhubIndustry"),
                            market_cap=float(data.get("marketCapitalization", 0.0) or 0.0),
                            headquarters=data.get("headquarters", "N/A"),
                            ceo=data.get("ceo", "N/A"),
                            competitors=self._generate_competitors_via_llm(ticker, data.get("name", ticker)),
                            website=data.get("weburl", "N/A"),
                            listing_exchange=data.get("exchange", "N/A"),
                            country=data.get("country", "US"),
                            business_summary=None
                        )
            except Exception as exc:
                logger.error("FinnhubProvider: get_company_profile failed: %s. Falling back.", exc)

        return self._compile_profile_via_llm(ticker)

    def get_financials(self, ticker: str) -> CompanyFinancialsPayload:
        logger.info("FinnhubProvider: get_financials ticker=%s", ticker)

        if self._api_key:
            try:
                headers = {"X-Finnhub-Token": self._api_key}
                # Profile to get name
                profile_url = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}"
                profile_resp = httpx.get(profile_url, headers=headers, timeout=10.0)
                
                # Metrics
                metric_url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all"
                metric_resp = httpx.get(metric_url, headers=headers, timeout=10.0)
                
                if profile_resp.status_code == 200 and metric_resp.status_code == 200:
                    profile_data = profile_resp.json()
                    metric_data = metric_resp.json()
                    
                    if profile_data and "name" in profile_data:
                        logger.info("FinnhubProvider: Fetched financials from API for %s", ticker)
                        
                        metrics = metric_data.get("metric", {})
                        pe = float(metrics.get("peBasicExclExtraItems", 0.0) or 0.0)
                        eps = float(metrics.get("epsExclExtraItemsTTM", 0.0) or 0.0)
                        rev = float(metrics.get("revenueTTM", 0.0) or 0.0)
                        net_margin = float(metrics.get("netProfitMarginAllTime", 0.0) or 0.0)
                        profit = (rev * (net_margin / 100.0)) if net_margin else 0.0
                        
                        return CompanyFinancialsPayload(
                            ticker=ticker,
                            revenue=rev,
                            profit=profit,
                            eps=eps,
                            pe_ratio=pe
                        )
            except Exception as exc:
                logger.error("FinnhubProvider: get_financials failed: %s. Falling back.", exc)

        return self._compile_financials_via_llm(ticker)

    def get_historical_financials(self, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        logger.info("FinnhubProvider: get_historical_financials ticker=%s", ticker)
        return self._compile_history_via_llm(ticker)

    def get_dividend_history(self, ticker: str) -> list[CompanyDividendPayload]:
        logger.info("FinnhubProvider: get_dividend_history ticker=%s", ticker)
        return self._compile_dividends_via_llm(ticker)

    def get_annual_reports(self, ticker: str) -> list[CompanyDocumentPayload]:
        logger.info("FinnhubProvider: get_annual_reports ticker=%s", ticker)
        return self._compile_reports_via_llm(ticker)

    def get_news(self, ticker: str) -> list[CompanyNewsPayload]:
        logger.info("FinnhubProvider: get_news ticker=%s", ticker)
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
        prompt = f"Research and compile current financials (Rev, Profit, EPS, PE) for '{ticker}'. Return JSON matching CompanyFinancialsPayload."
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
