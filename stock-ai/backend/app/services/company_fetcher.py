"""
company_fetcher.py — Ingestion orchestrator.
Delegates to the configured FinancialDataProvider to update database tables.
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.ai_service import GeminiAIService
from app.providers.financial.base_provider import (
    FinancialDataProvider, CompanyDataPayload, CompanyProfilePayload,
    CompanyFinancialsPayload, CompanyHistoricalFinancialsPayload,
    CompanyDividendPayload, CompanyDocumentPayload, CompanyNewsPayload
)
from app.models.company import Company, CompanyFinancialHistory, CompanyDividend

logger = logging.getLogger(__name__)


class CompanyFetcher:
    """Orchestrates database ingestion by delegating requests to the configured FinancialDataProvider."""

    def __init__(self, ai_service: GeminiAIService, settings: Settings) -> None:
        self._ai = ai_service
        self._settings = settings
        self._provider = self._select_provider()

    def fetch(self, ticker: str, company_name: str | None = None) -> CompanyDataPayload:
        """
        Legacy orchestrator kept for absolute backward compatibility.
        Combines results from get_company_profile, get_financials, and get_annual_reports.
        """
        logger.info("CompanyFetcher: Running legacy fetch compat wrapper for %s...", ticker)
        profile = self._provider.get_company_profile(ticker)
        financials = self._provider.get_financials(ticker)
        docs = self._provider.get_annual_reports(ticker)

        # Map document contents by name to old summaries
        annual_sum = ""
        risk_sum = ""
        mda_sum = ""
        quarterly_sum = ""
        investor_sum = ""

        for doc in docs:
            name = doc.document_name.lower()
            if "annual" in name:
                annual_sum = doc.content
            elif "risk" in name:
                risk_sum = doc.content
            elif "mda" in name or "management" in name:
                mda_sum = doc.content
            elif "quarter" in name:
                quarterly_sum = doc.content
            elif "investor" in name or "presentation" in name:
                investor_sum = doc.content

        # Fill defaults if missing
        if not annual_sum:
            annual_sum = f"Annual report summary for {profile.company_name}."
        if not risk_sum:
            risk_sum = f"Risk factors analysis context for {profile.company_name}."
        if not mda_sum:
            mda_sum = f"Management Discussion & Analysis regarding {profile.company_name}."

        return CompanyDataPayload(
            company_name=profile.company_name,
            ticker=ticker,
            sector=profile.sector or "General",
            industry=profile.industry or "General Business",
            revenue=financials.revenue,
            profit=financials.profit,
            eps=financials.eps,
            pe_ratio=financials.pe_ratio,
            business_summary=profile.business_summary or f"Operations profile of {profile.company_name}.",
            annual_report_summary=annual_sum,
            quarterly_results_summary=quarterly_sum or "Quarterly statements notes.",
            investor_presentation_notes=investor_sum or "Conference Q&A summaries.",
            risk_factors=risk_sum,
            mda=mda_sum
        )

    # ── New Granular Ingestors (Problems 2, 3, 4, 6) ─────────────────────────

    def fetch_profile_and_metadata(self, db: Session, ticker: str, company_name: str | None = None) -> CompanyProfilePayload:
        """Fetch general metadata and CEO/competitors, upserting the Company row in SQLite."""
        logger.info("CompanyFetcher: Fetching profile metadata for %s...", ticker)
        payload = self._provider.get_company_profile(ticker)
        
        ticker_upper = ticker.upper()
        company = db.query(Company).filter(Company.ticker == ticker_upper).first()

        competitors_str = ",".join(payload.competitors) if payload.competitors else None

        if not company:
            company = Company(
                ticker=ticker_upper,
                company_name=payload.company_name,
                revenue=0.0,
                profit=0.0,
                eps=0.0,
                pe_ratio=0.0
            )
            db.add(company)

        # Update metadata columns
        company.sector = payload.sector
        company.industry = payload.industry
        company.market_cap = payload.market_cap
        company.headquarters = payload.headquarters
        company.ceo = payload.ceo
        company.competitors = competitors_str
        company.website = payload.website
        company.listing_exchange = payload.listing_exchange
        company.country = payload.country
        
        db.commit()
        db.refresh(company)
        logger.info("CompanyFetcher: Profile metadata updated successfully for %s.", ticker_upper)
        return payload

    def fetch_financials(self, db: Session, ticker: str) -> CompanyFinancialsPayload:
        """Fetch core PE ratios/EPS and update metrics in SQLite."""
        logger.info("CompanyFetcher: Fetching financials for %s...", ticker)
        payload = self._provider.get_financials(ticker)
        
        ticker_upper = ticker.upper()
        company = db.query(Company).filter(Company.ticker == ticker_upper).first()

        if not company:
            company = Company(
                ticker=ticker_upper,
                company_name=ticker_upper,
                revenue=0.0,
                profit=0.0,
                eps=0.0,
                pe_ratio=0.0
            )
            db.add(company)

        # Update metrics columns
        company.revenue = payload.revenue
        company.profit = payload.profit
        company.eps = payload.eps
        company.pe_ratio = payload.pe_ratio
        company.reporting_period = payload.reporting_period
        
        db.commit()
        logger.info("CompanyFetcher: Core financials updated successfully for %s.", ticker_upper)
        return payload

    def fetch_historical_financials(self, db: Session, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        """Fetch 5-year ratios history and overwrite SQLite rows."""
        logger.info("CompanyFetcher: Fetching historical financials for %s...", ticker)
        history = self._provider.get_historical_financials(ticker)
        
        ticker_upper = ticker.upper()
        
        # Overwrite previous entries
        db.query(CompanyFinancialHistory).filter(CompanyFinancialHistory.ticker == ticker_upper).delete()

        # Insert new rows
        for h in history:
            row = CompanyFinancialHistory(
                ticker=ticker_upper,
                year=h.year,
                revenue=h.revenue,
                profit=h.profit,
                eps=h.eps,
                operating_margin=h.operating_margin,
                net_margin=h.net_margin,
                roe=h.roe,
                roce=h.roce,
                dividend=h.dividend
            )
            db.add(row)
            
        db.commit()
        logger.info("CompanyFetcher: Saved %d historical rows for %s.", len(history), ticker_upper)
        
        # Auto-sync company current metrics with latest historical year record
        latest_hist = db.query(CompanyFinancialHistory).filter(
            CompanyFinancialHistory.ticker == ticker_upper
        ).order_by(CompanyFinancialHistory.year.desc()).first()
        if latest_hist:
            company = db.query(Company).filter(Company.ticker == ticker_upper).first()
            if company:
                company.revenue = latest_hist.revenue
                company.profit = latest_hist.profit
                company.eps = latest_hist.eps
                db.commit()
                logger.info("CompanyFetcher: Synchronized company table metrics with latest historical year %d for %s.", latest_hist.year, ticker_upper)
                
        return history

    def fetch_dividend_history(self, db: Session, ticker: str) -> list[CompanyDividendPayload]:
        """Fetch dividend payouts list and overwrite SQLite rows."""
        logger.info("CompanyFetcher: Fetching dividend history for %s...", ticker)
        dividends = self._provider.get_dividend_history(ticker)
        
        ticker_upper = ticker.upper()
        
        # Overwrite previous entries
        db.query(CompanyDividend).filter(CompanyDividend.ticker == ticker_upper).delete()

        # Insert new rows
        for d in dividends:
            row = CompanyDividend(
                ticker=ticker_upper,
                date=d.date,
                dividend=d.dividend,
                dividend_yield=d.dividend_yield
            )
            db.add(row)

        db.commit()
        logger.info("CompanyFetcher: Saved %d dividend declarations for %s.", len(dividends), ticker_upper)
        return dividends

    def fetch_annual_reports(self, ticker: str) -> list[CompanyDocumentPayload]:
        """Fetch qualitative reports (called by coordinator for vector indexing)."""
        return self._provider.get_annual_reports(ticker)

    def fetch_news(self, ticker: str) -> list[CompanyNewsPayload]:
        """Fetch news articles feed (called by news cache updater)."""
        return self._provider.get_news(ticker)

    # ── Internal factory ─────────────────────────────────────────────────────

    def _select_provider(self) -> FinancialDataProvider:
        provider_name = self._settings.financial_data_provider.lower()
        logger.info("CompanyFetcher: Initializing provider: %s", provider_name)

        if provider_name == "alphavantage":
            from app.providers.financial.alpha_vantage import AlphaVantageProvider
            return AlphaVantageProvider(
                ai_service=self._ai,
                api_key=self._settings.alphavantage_api_key
            )
        elif provider_name == "finnhub":
            from app.providers.financial.finnhub import FinnhubProvider
            return FinnhubProvider(
                ai_service=self._ai,
                api_key=self._settings.finnhub_api_key
            )
        elif provider_name == "polygon":
            from app.providers.financial.polygon import PolygonProvider
            return PolygonProvider(
                ai_service=self._ai,
                api_key=self._settings.polygon_api_key
            )
        else:
            from app.providers.financial.yahoo_finance import YahooFinanceProvider
            return YahooFinanceProvider(ai_service=self._ai)
