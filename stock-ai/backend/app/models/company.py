from __future__ import annotations

from sqlalchemy import Float, Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    revenue: Mapped[float] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float)
    eps: Mapped[float] = mapped_column(Float)
    pe_ratio: Mapped[float] = mapped_column(Float)

    # Expanded Metadata (Problem 2)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    headquarters: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ceo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    competitors: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Comma-separated list of tickers
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    listing_exchange: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CompanyFinancialHistory(Base):
    __tablename__ = "company_financial_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(50), ForeignKey("companies.ticker", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[float] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float)
    eps: Mapped[float] = mapped_column(Float)
    operating_margin: Mapped[float] = mapped_column(Float)
    net_margin: Mapped[float] = mapped_column(Float)
    roe: Mapped[float] = mapped_column(Float)
    roce: Mapped[float] = mapped_column(Float)
    dividend: Mapped[float] = mapped_column(Float)


class CompanyDividend(Base):
    __tablename__ = "company_dividends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(50), ForeignKey("companies.ticker", ondelete="CASCADE"), index=True)
    date: Mapped[str] = mapped_column(String(50))
    dividend: Mapped[float] = mapped_column(Float)
    # Using alias "yield" since yield is a python keyword
    dividend_yield: Mapped[float] = mapped_column("yield", Float)
