from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field


class CompanyDataPayload(BaseModel):
    """Legacy payload schema kept for absolute backward compatibility."""
    company_name: str = Field(description="Canonical full name of the company, e.g. State Bank of India")
    ticker: str = Field(description="Stock ticker symbol, e.g. SBIN")
    sector: str = Field(description="Sector classification, e.g. Financial Services")
    industry: str = Field(description="Industry classification, e.g. Public Sector Banks")
    revenue: float = Field(description="Annual revenue in Rs. crore (crores INR) for Indian stocks, or standard currency units for foreign stocks")
    profit: float = Field(description="Annual net profit in Rs. crore (crores INR) for Indian stocks, or standard currency units")
    eps: float = Field(description="Earnings per share")
    pe_ratio: float = Field(description="Price to earnings ratio")
    business_summary: str = Field(description="Detailed summary of the business operations, products, and core markets")
    annual_report_summary: str = Field(description="Detailed overview of the latest annual report, operations, and financial performance highlights")
    quarterly_results_summary: str = Field(description="Summary of the latest quarterly results, growth trends, margins, and management outlook")
    investor_presentation_notes: str = Field(description="Key takeaways from recent investor presentations and earnings calls")
    risk_factors: str = Field(description="Key risks faced by the business, regulatory concerns, competitive dynamics")
    mda: str = Field(description="Management Discussion & Analysis MD&A summary regarding market opportunities and operational hurdles")


# ── Fine-Grained Payload Schemas (Problem 7) ───────────────────────────────

class CompanyProfilePayload(BaseModel):
    company_name: str
    ticker: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    headquarters: str | None = None
    ceo: str | None = None
    competitors: list[str] = Field(default_factory=list, description="List of ticker symbols of direct competitor peers")
    website: str | None = None
    listing_exchange: str | None = None
    country: str | None = None
    business_summary: str | None = None


class CompanyFinancialsPayload(BaseModel):
    ticker: str
    revenue: float
    profit: float
    eps: float
    pe_ratio: float
    reporting_period: str = Field(default="FY2025", description="The reporting period of the fetched financials, e.g. 'FY2025' or 'Q1 FY2026'")


class CompanyHistoricalFinancialsPayload(BaseModel):
    year: int
    revenue: float
    profit: float
    eps: float
    operating_margin: float
    net_margin: float
    roe: float
    roce: float
    dividend: float


class CompanyDividendPayload(BaseModel):
    date: str
    dividend: float
    dividend_yield: float = Field(description="Yield percentage value, e.g. 1.5")


class CompanyDocumentPayload(BaseModel):
    document_name: str  # e.g., BHARTIARTL_Annual_Report.txt
    content: str


class CompanyNewsPayload(BaseModel):
    title: str
    source: str
    author: str | None = None
    published_at: str
    url: str | None = None
    content: str


class MarketDataPayload(BaseModel):
    current_price: float
    currency: str
    daily_change: float
    percentage_change: float
    day_high: float
    day_low: float
    previous_close: float
    market_status: str | None = None
    last_updated: str
    source: str


class FinancialDataProvider(ABC):
    """Abstract interface defining data acquisition for the Data-Aware system."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of the provider."""
        pass

    @abstractmethod
    def get_company_profile(self, ticker: str) -> CompanyProfilePayload:
        """Fetch general meta-profile info (CEO, competitors, sector, country)."""
        pass

    @abstractmethod
    def get_financials(self, ticker: str) -> CompanyFinancialsPayload:
        """Fetch current financial ratios (revenue, profit, eps, PE ratio)."""
        pass

    @abstractmethod
    def get_historical_financials(self, ticker: str) -> list[CompanyHistoricalFinancialsPayload]:
        """Fetch multi-year historical indicators (revenue, profit, roe, operating margin)."""
        pass

    @abstractmethod
    def get_dividend_history(self, ticker: str) -> list[CompanyDividendPayload]:
        """Fetch payment actions history (date, amount, yield)."""
        pass

    @abstractmethod
    def get_annual_reports(self, ticker: str) -> list[CompanyDocumentPayload]:
        """Fetch qualitative reports (Annual Report, MD&A, Risk Factors, presentations)."""
        pass

    @abstractmethod
    def get_news(self, ticker: str) -> list[CompanyNewsPayload]:
        """Fetch latest stock news articles."""
        pass

    @abstractmethod
    def get_live_market_data(self, ticker: str) -> MarketDataPayload | None:
        """Fetch real-time stock price and market metrics (current price, day high/low, changes)."""
        pass
