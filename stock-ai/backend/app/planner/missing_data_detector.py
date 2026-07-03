"""
missing_data_detector.py — Resolves required data layers and inspects storage backends for missing elements.
"""
from __future__ import annotations

import logging
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models.company import Company, CompanyFinancialHistory, CompanyDividend
from app.services.rag.chroma_client import get_chroma_client

logger = logging.getLogger(__name__)


class DataDimension(str, Enum):
    CURRENT_METRICS = "current_metrics"
    METADATA = "metadata"
    HISTORICAL_METRICS = "historical_metrics"
    DIVIDEND_HISTORY = "dividend_history"
    FILINGS = "filings"
    NEWS = "news"


class MissingDataDetector:
    """Identifies which financial fields are required and checks if they exist in SQLite or ChromaDB."""

    def __init__(self, news_collection_name: str = "financial_news", doc_collection_name: str = "financial_documents") -> None:
        self._chroma = get_chroma_client()
        self._news_collection_name = news_collection_name
        self._doc_collection_name = doc_collection_name

    def determine_required_data(self, query: str, intent_str: str) -> list[DataDimension]:
        """
        Determines the needed financial dimensions based on intent and query keywords.
        """
        required = set()
        normalized = query.lower()

        # 1. Map based on classifier intent categories
        if intent_str == "financial_metric":
            required.add(DataDimension.CURRENT_METRICS)
        elif intent_str == "company_overview":
            required.add(DataDimension.METADATA)
            required.add(DataDimension.CURRENT_METRICS)
            required.add(DataDimension.NEWS)
        elif intent_str == "company_comparison":
            required.add(DataDimension.METADATA)
            required.add(DataDimension.CURRENT_METRICS)
        elif intent_str == "latest_news":
            required.add(DataDimension.NEWS)
        elif intent_str in ("annual_report", "earnings_call", "filings"):
            required.add(DataDimension.FILINGS)
        elif intent_str == "hybrid_analysis":
            required.add(DataDimension.CURRENT_METRICS)
            required.add(DataDimension.METADATA)
            required.add(DataDimension.FILINGS)
            required.add(DataDimension.NEWS)

        # 2. Semantic query keyword analysis (Problem 5)
        historical_keywords = {"growth", "history", "years", "historical", "trend", "past", "track record", "over last"}
        if any(kw in normalized for kw in historical_keywords):
            required.add(DataDimension.HISTORICAL_METRICS)

        dividend_keywords = {"dividend", "yield", "payout", "dividends"}
        if any(kw in normalized for kw in dividend_keywords):
            required.add(DataDimension.DIVIDEND_HISTORY)

        competitor_keywords = {"competitor", "competitors", "peers", "rival", "rivals", "industry comparison", "peer"}
        if any(kw in normalized for kw in competitor_keywords):
            required.add(DataDimension.METADATA)

        metadata_profile_keywords = {"ceo", "headquarters", "exchange", "website", "country", "ceo of", "founder"}
        if any(kw in normalized for kw in metadata_profile_keywords):
            required.add(DataDimension.METADATA)

        # Default fallback: always require core current financials
        if not required:
            required.add(DataDimension.CURRENT_METRICS)

        result = list(required)
        logger.info("MissingDataDetector: Required dimensions for query %r (intent=%s) -> %s",
                    query, intent_str, [d.value for d in result])
        return result

    def detect_missing_dimensions(self, db: Session, ticker: str, required: list[DataDimension]) -> list[DataDimension]:
        """
        Inspects SQLite and ChromaDB to verify if required data exists for the ticker.
        Returns:
            list[DataDimension] of missing dimensions.
        """
        ticker_upper = ticker.upper()
        missing = []

        # Load company row from SQLite
        company = db.query(Company).filter(Company.ticker == ticker_upper).first()

        for dimension in required:
            if dimension == DataDimension.CURRENT_METRICS:
                # Missing if company row does not exist or has zero/null financials
                if not company or company.revenue == 0.0 or company.profit == 0.0:
                    missing.append(DataDimension.CURRENT_METRICS)

            elif dimension == DataDimension.METADATA:
                # Missing if company row has empty sector, CEO or competitors fields
                if not company or not company.sector or not company.ceo or not company.competitors:
                    missing.append(DataDimension.METADATA)

            elif dimension == DataDimension.HISTORICAL_METRICS:
                # Check history count in SQLite
                count = db.query(func.count(CompanyFinancialHistory.id)).filter(
                    CompanyFinancialHistory.ticker == ticker_upper
                ).scalar()
                if count == 0:
                    missing.append(DataDimension.HISTORICAL_METRICS)

            elif dimension == DataDimension.DIVIDEND_HISTORY:
                # Check dividend payout logs in SQLite
                count = db.query(func.count(CompanyDividend.id)).filter(
                    CompanyDividend.ticker == ticker_upper
                ).scalar()
                if count == 0:
                    missing.append(DataDimension.DIVIDEND_HISTORY)

            elif dimension == DataDimension.FILINGS:
                # Check Chroma filings vector index (presence of matching metadata documents)
                try:
                    collection = self._chroma.get_collection(name=self._doc_collection_name)
                    # Query for any metadata matching ticker source ID prefix
                    result = collection.get(where={"source": {"$like": f"%{ticker_upper}%"}}, limit=1)
                    if not result or not result.get("ids"):
                        missing.append(DataDimension.FILINGS)
                except Exception:
                    missing.append(DataDimension.FILINGS)

            elif dimension == DataDimension.NEWS:
                # Check Chroma news vector index (presence of matching metadata tickers)
                try:
                    collection = self._chroma.get_collection(name=self._news_collection_name)
                    result = collection.get(where={"company": ticker_upper}, limit=1)
                    if not result or not result.get("ids"):
                        missing.append(DataDimension.NEWS)
                except Exception:
                    missing.append(DataDimension.NEWS)

        logger.info("MissingDataDetector: Ticker=%s | Missing dimensions -> %s",
                    ticker_upper, [d.value for d in missing])
        return missing
