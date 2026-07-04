"""
hybrid_retriever.py — Coordinates company detection, caching checks, dynamic fetching, indexing, and SQLite updates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.company import Company
from app.services.company_detector import CompanyDetector
from app.services.company_registry import CompanyRegistry
from app.services.company_fetcher import CompanyFetcher
from app.services.document_processor import DocumentProcessor
from app.services.vector_service import VectorService
from app.services.embedding_service import EmbeddingService

# New Data-Aware Imports (Problems 1, 5, 8, 10)
from app.planner.missing_data_detector import MissingDataDetector, DataDimension

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Orchestrates dynamic data collection and ensures documents are indexed in ChromaDB before retrieval."""

    def __init__(
        self,
        settings: Settings,
        ai_service,
        db_session: Session,
        news_service: Any | None = None,
    ) -> None:
        self._settings = settings
        self._ai = ai_service
        self._db = db_session
        self._news_service = news_service
        
        self._detector = CompanyDetector(ai_service)
        self._fetcher = CompanyFetcher(ai_service, settings)
        self._processor = DocumentProcessor(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap
        )
        self._embedding = EmbeddingService()
        self._vector_service = VectorService(settings, self._embedding)
        self._detector_engine = MissingDataDetector(
            news_collection_name=settings.news_collection_name,
            doc_collection_name=settings.news_collection_name
        )

    def ensure_company_data(
        self,
        question: str,
        force_refresh: bool = False,
        required_dimensions: list[DataDimension] | None = None
    ) -> tuple[str | None, str | None]:
        """
        Detects if a company is mentioned. If it is, checks ChromaDB cache and SQLite tables.
        If missing required dimensions or older than 7 days, dynamically triggers targeted
        fetch operations for profile metadata, current financials, historical sheets, dividends, and news.
        
        Returns:
            tuple: (detected_ticker, canonical_name) or (None, None)
        """
        # 1. Detect company (Problem 5 & 8)
        ticker, name, confidence = self._detector.detect(question)
        if not ticker:
            logger.info("HybridRetriever: no company detected in query.")
            return None, None
            
        ticker = ticker.upper()
        logger.info("HybridRetriever: detected ticker=%s, name=%s, confidence=%s", ticker, name, confidence)

        if not force_refresh:
            force_refresh = self._is_refresh_requested(question)
            if force_refresh:
                logger.info("HybridRetriever: explicit refresh requested in query.")

        # 2. Determine target dimensions to check
        if required_dimensions is None:
            # Fallback to general hybrid checklist if not specified
            required_dimensions = [
                DataDimension.CURRENT_METRICS,
                DataDimension.METADATA,
                DataDimension.HISTORICAL_METRICS,
                DataDimension.DIVIDEND_HISTORY,
                DataDimension.FILINGS
            ]

        # 3. Check if company exists in SQLite at all (Cold Start)
        company_exists = self._db.query(Company).filter(Company.ticker == ticker).first() is not None
        
        # Check Chroma document cache status
        docs_exist, newest_chunk_at = self._vector_service.check_company_exists(ticker)
        is_expired = False
        if docs_exist and newest_chunk_at:
            age = datetime.now(tz=timezone.utc) - newest_chunk_at
            if age > timedelta(days=7):
                logger.info("HybridRetriever: document cache expired for ticker=%s (age=%s). Triggering refresh.", ticker, age)
                is_expired = True

        # If company doesn't exist in SQLite or Chroma cache is expired/forced: fetch everything
        if not company_exists or is_expired or force_refresh:
            logger.info("HybridRetriever: Cold start or expired cache for %s. Requesting all dimensions.", ticker)
            missing = [
                DataDimension.CURRENT_METRICS,
                DataDimension.METADATA,
                DataDimension.HISTORICAL_METRICS,
                DataDimension.DIVIDEND_HISTORY,
                DataDimension.FILINGS,
                DataDimension.NEWS
            ]
        else:
            # Run Missing Data Detector to identify gaps (Problem 5 & 8)
            missing = self._detector_engine.detect_missing_dimensions(self._db, ticker, required_dimensions)

        # 4. If missing dimensions detected, execute dynamic retry retrieval (Problem 8 & 10)
        if missing:
            logger.info("[DETECTION] Query: %s | Company: %s | Confidence: %f | Source: %s",
                        question, name or ticker, confidence, "Live Fetch")
            logger.info("[METRICS] Detected Intent: data_aware_query | Required Data Types: %s | Missing Data: %s",
                        [d.value for d in required_dimensions], [d.value for d in missing])
            
            provider_name = self._fetcher._provider.provider_name
            logger.info("[METRICS] Provider Invoked: %s", provider_name)

            try:
                records_added_log = []

                # A. Fetch general metadata profile if missing
                if DataDimension.METADATA in missing:
                    self._fetcher.fetch_profile_and_metadata(self._db, ticker, name)
                    records_added_log.append("Company Metadata Profile")

                # B. Fetch core current financials if missing
                if DataDimension.CURRENT_METRICS in missing:
                    self._fetcher.fetch_financials(self._db, ticker)
                    records_added_log.append("Current Financial Metrics")

                # C. Fetch 5-year historical financial statement sheets if missing
                if DataDimension.HISTORICAL_METRICS in missing:
                    hist_rows = self._fetcher.fetch_historical_financials(self._db, ticker)
                    records_added_log.append(f"{len(hist_rows)} Historical Financial Rows")

                # D. Fetch dividend payouts history if missing
                if DataDimension.DIVIDEND_HISTORY in missing:
                    div_rows = self._fetcher.fetch_dividend_history(self._db, ticker)
                    records_added_log.append(f"{len(div_rows)} Dividend History Entries")

                # E. Fetch qualitative annual report files if missing
                if DataDimension.FILINGS in missing:
                    payload = self._fetcher.fetch(ticker, name)
                    chunks = self._processor.process(payload)
                    if docs_exist or is_expired or force_refresh:
                        self._vector_service.delete_company_documents(ticker)
                    self._vector_service.store_chunks(chunks)
                    records_added_log.append(f"{len(chunks)} Vector Document Chunks")

                # F. Fetch news feed if missing
                if DataDimension.NEWS in missing and self._news_service:
                    self._news_service.ensure_fresh_news([ticker])
                    records_added_log.append("News feed chunks")

                logger.info("[METRICS] Records Added: %s | Retry Executed = YES | Retrieval Successful = YES",
                            ", ".join(records_added_log))
                
                # Fetch canonical name to return
                comp = self._db.query(Company).filter(Company.ticker == ticker).first()
                canonical_name = comp.company_name if comp else name
                return ticker, canonical_name

            except Exception as exc:
                logger.exception("HybridRetriever: Dynamic fetching failed for %s", ticker)
                return ticker, name
        else:
            logger.info("[DETECTION] Query: %s | Company: %s | Confidence: %f | Source: %s",
                        question, name or ticker, confidence, "Vector DB / Cache Hit")
            logger.info("HybridRetriever: cache hit, reusing existing vectors for ticker=%s.", ticker)
            return ticker, name

    @staticmethod
    def _is_refresh_requested(query: str) -> bool:
        """Detect if user query explicitly demands fresh/latest information."""
        keywords = {
            "refresh", "update", "latest", "recent", "today", "current",
            "latest news", "latest filings", "new report", "latest data", "new information"
        }
        normalized = query.lower()
        return any(kw in normalized for kw in keywords)
