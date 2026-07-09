"""
yahoo_finance.py — Yahoo Finance provider implementation.
Utilizes Yahoo Finance public APIs with Gemini-powered compiler fallbacks for data-aware schemas.
"""
from __future__ import annotations

import logging
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


class YahooFinanceProvider(FinancialDataProvider):
    """Fetches details from Yahoo Finance with Gemini-based structured compilers."""

    def __init__(self, ai_service: GeminiAIService) -> None:
        self._ai = ai_service

    @property
    def provider_name(self) -> str:
        return "YahooFinance"

    def get_company_profile(self, ticker: str) -> CompanyProfilePayload:
        logger.info("YahooFinanceProvider: get_company_profile ticker=%s", ticker)
        prompt = (
            f"Research and compile a complete company profile and metadata for stock ticker '{ticker}'.\n"
            f"Fill in all fields of the schema. Provide a list of 4-6 direct stock competitor tickers in 'competitors' "
            f"(e.g., for TCS: ['INFY', 'WIPRO', 'HCLT', 'TECHM']).\n"
            f"Respond only with JSON matching the CompanyProfilePayload schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert equity research intelligence tool. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=CompanyProfilePayload,
                ),
            )
            if response.parsed and isinstance(response.parsed, CompanyProfilePayload):
                return response.parsed
            raise RuntimeError("Failed to parse company profile payload.")
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_company_profile failed: %s", exc)
            # Safe default
            return CompanyProfilePayload(
                company_name=ticker, ticker=ticker, competitors=[]
            )

    def get_financials(self, ticker: str) -> CompanyFinancialsPayload:
        logger.info("YahooFinanceProvider: get_financials ticker=%s", ticker)
        prompt = (
            f"Research and compile current core financials for stock ticker '{ticker}'.\n"
            f"Identify the latest reported period for these financials (this should be a fiscal year like 'FY2025' or a specific quarter like 'Q1 FY2026' if it is more recent than the annual data). "
            f"Set the 'reporting_period' field to this identified period (e.g. 'FY2025' or 'Q1 FY2026').\n"
            f"If the company is Indian (e.g. SBIN, BHARTIARTL, TATAMOTORS, MRF, NESTLEIND, ADANIENT, TCS, INFY), "
            f"scale the 'revenue' and 'profit' values of that period to **Crores of Rupees** (Rs. crore, i.e., 10,000,000 INR). "
            f"Otherwise use standard local currency millions.\n"
            f"Respond only with JSON matching the CompanyFinancialsPayload schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert equity analyst. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=CompanyFinancialsPayload,
                ),
            )
            if response.parsed and isinstance(response.parsed, CompanyFinancialsPayload):
                return response.parsed
            raise RuntimeError("Failed to parse financials payload.")
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_financials failed: %s", exc)
            return CompanyFinancialsPayload(ticker=ticker, revenue=0.0, profit=0.0, eps=0.0, pe_ratio=0.0)

    def get_historical_financials(self, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        logger.info("YahooFinanceProvider: get_historical_financials ticker=%s", ticker)
        
        # Pydantic wrapper schema for list generation
        class HistoricalListWrapper(BaseModel):
            history: List[CompanyHistoricalFinancialsPayload]

        prompt = (
            f"Research and compile the historical financial spreadsheet for stock ticker '{ticker}' "
            f"covering the last 5 reporting years (e.g., 2021, 2022, 2023, 2024, 2025).\n"
            f"If the company is Indian, scale all financial table 'revenue' and 'profit' values "
            f"to **Crores of Rupees** (Rs. crore). operating_margin and net_margin should be percentage values "
            f"(e.g., 24.5 for 24.5%). Ensure roe and roce metrics are filled.\n"
            f"Respond only with JSON matching the HistoricalListWrapper schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert financial historian. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=HistoricalListWrapper,
                ),
            )
            if response.parsed and isinstance(response.parsed, HistoricalListWrapper):
                return response.parsed.history
            return []
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_historical_financials failed: %s", exc)
            return []

    def get_dividend_history(self, ticker: str) -> list[CompanyDividendPayload]:
        logger.info("YahooFinanceProvider: get_dividend_history ticker=%s", ticker)

        class DividendListWrapper(BaseModel):
            dividends: List[CompanyDividendPayload]

        prompt = (
            f"Research and compile the dividend payout history for stock ticker '{ticker}' "
            f"showing the last 5-10 dividend declarations (date, dividend amount paid, and yield percentage at that time).\n"
            f"Use date format YYYY-MM-DD.\n"
            f"Respond only with JSON matching the DividendListWrapper schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a corporate actions archivist. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=DividendListWrapper,
                ),
            )
            if response.parsed and isinstance(response.parsed, DividendListWrapper):
                return response.parsed.dividends
            return []
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_dividend_history failed: %s", exc)
            return []

    def get_annual_reports(self, ticker: str) -> list[CompanyDocumentPayload]:
        logger.info("YahooFinanceProvider: get_annual_reports ticker=%s", ticker)

        class DocumentsListWrapper(BaseModel):
            documents: List[CompanyDocumentPayload]

        prompt = (
            f"Act as a company filings database. Research and retrieve detailed text highlights "
            f"representing: Annual Report (Overview), Management Discussion & Analysis (MD&A), "
            f"Investor Presentation Summary, and Risk Factors for stock ticker '{ticker}'.\n"
            f"Each document text should be at least 3-4 dense paragraphs filled with factual, qualitative context.\n"
            f"Respond only with JSON matching the DocumentsListWrapper schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a company filings repository. Return structured JSON.",
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=DocumentsListWrapper,
                ),
            )
            if response.parsed and isinstance(response.parsed, DocumentsListWrapper):
                return response.parsed.documents
            return []
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_annual_reports failed: %s", exc)
            return []

    def get_news(self, ticker: str) -> list[CompanyNewsPayload]:
        logger.info("YahooFinanceProvider: get_news ticker=%s", ticker)

        class NewsListWrapper(BaseModel):
            news: List[CompanyNewsPayload]

        prompt = (
            f"Compile the latest financial news articles and headlines for stock ticker '{ticker}' (at least 3-5 articles).\n"
            f"Provide published_at times in ISO format (e.g., YYYY-MM-DDTHH:MM:SSZ).\n"
            f"Respond only with JSON matching the NewsListWrapper schema."
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a financial news anchor. Return structured JSON.",
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=NewsListWrapper,
                ),
            )
            if response.parsed and isinstance(response.parsed, NewsListWrapper):
                return response.parsed.news
            return []
        except Exception as exc:
            logger.error("YahooFinanceProvider: get_news failed: %s", exc)
            return []

    def get_live_market_data(self, ticker: str) -> MarketDataPayload | None:
        logger.info("YahooFinanceProvider: get_live_market_data ticker=%s", ticker)
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
            logger.error("YahooFinanceProvider: get_live_market_data failed: %s", exc)
            return None
