"""
hybrid_retrieval_service.py — 3-source retrieval orchestrator.

Sources:
  1. SQLite          → structured financial metrics
  2. ChromaDB docs   → annual reports, filings, earnings transcripts
  3. ChromaDB news   → live news (cache-first via NewsService)

Rules:
  - SQL always runs first.
  - Document retrieval always runs.
  - News: check cache → HIT = retrieve only, MISS = fetch+ingest+retrieve.
  - Failure in any source never blocks the others.
  - No LLM calls here — pure data retrieval.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models.chat import CompanySnapshot, DocumentChunk, ExtractedQuery, NewsChunk, RetrievalContext
from app.services.db_service import DBService
from app.services.news.news_service import NewsService
from app.services.rag.retrieval_service import DocumentRetrievalService, NewsRetrievalService
from app.services.hybrid_retriever import HybridRetriever

logger = logging.getLogger(__name__)


@dataclass
class HybridContext:
    sql_context: RetrievalContext
    companies: list[CompanySnapshot] = field(default_factory=list)
    document_chunks: list[DocumentChunk] = field(default_factory=list)
    news_chunks: list[NewsChunk] = field(default_factory=list)
    has_sql_data: bool = False
    has_document_data: bool = False
    has_news_data: bool = False


class HybridRetrievalService:
    def __init__(
        self,
        db_service: DBService,
        document_retrieval: DocumentRetrievalService,
        news_retrieval: NewsRetrievalService,
        news_service: NewsService | None = None,
        hybrid_retriever: HybridRetriever | None = None,
    ) -> None:
        self._db = db_service
        self._doc_retrieval = document_retrieval
        self._news_retrieval = news_retrieval
        self._news_service = news_service
        self._hybrid_retriever = hybrid_retriever

    def retrieve(
        self,
        question: str,
        extracted_query: ExtractedQuery,
        refresh_news: bool = True,
    ) -> HybridContext:
        # ── 0. Dynamic Fetch & Embedding ──────────────────────────────────────
        resolved_ticker = None
        if self._hybrid_retriever:
            try:
                resolved_ticker, canonical_name = self._hybrid_retriever.ensure_company_data(question)
                if resolved_ticker:
                    resolved_ticker = resolved_ticker.upper()
                    # Ensure the resolved ticker is added to extraction identifiers
                    if resolved_ticker not in extracted_query.company_identifiers:
                        extracted_query.company_identifiers.append(resolved_ticker)
            except Exception as exc:
                logger.warning("HybridRetrieval: failed to run dynamic retrieval: %s", exc)

        # ── 1. SQLite ──────────────────────────────────────────────────────────
        logger.info("HybridRetrieval: SQL. intent=%s companies=%s",
                    extracted_query.intent, extracted_query.company_identifiers)
        sql_context = self._db.build_context(extracted_query)
        has_sql = bool(sql_context.companies)
        logger.info("HybridRetrieval: SQL done. found=%d", len(sql_context.companies))

        # ── 2. Document ChromaDB ───────────────────────────────────────────────
        logger.info("HybridRetrieval: document retrieval. query=%r", question)
        # Re-initialize collection if needed. DocumentRetrievalService gets top k document chunks.
        doc_chunks = self._doc_retrieval.retrieve(question)
        
        # If we have a resolved company ticker, let's filter chunks to avoid unrelated search noise
        tickers = extracted_query.company_identifiers or [c.ticker for c in sql_context.companies]
        if tickers and doc_chunks:
            # Match doc chunks by company ticker if stored in metadata or filenames
            filtered_chunks = []
            for chunk in doc_chunks:
                # File names look like TCS_Annual_Report.txt or TCS_Q4.pdf::3
                matches_ticker = any(t.upper() in chunk.chunk_id.upper() or t.upper() in chunk.document.upper() for t in tickers)
                if matches_ticker:
                    filtered_chunks.append(chunk)
            # If filtering left us with chunks, use them, otherwise keep original chunks to avoid empty documents
            if filtered_chunks:
                doc_chunks = filtered_chunks

        logger.info("HybridRetrieval: document retrieval done. chunks=%d", len(doc_chunks))

        # ── 3. News — cache-first ──────────────────────────────────────────────
        if refresh_news and self._news_service and tickers:
            logger.info("HybridRetrieval: ensuring fresh news for tickers=%s", tickers)
            try:
                statuses = self._news_service.ensure_fresh_news(tickers)
                for ticker, msg in statuses.items():
                    logger.info("HybridRetrieval: news status ticker=%s → %s", ticker, msg)
            except Exception as exc:
                logger.warning("HybridRetrieval: news pipeline failed: %s", exc)

        logger.info("HybridRetrieval: news retrieval. query=%r", question)
        news_chunks = self._news_retrieval.retrieve(
            query=question,
            company_filter=tickers if tickers else None,
        )
        logger.info("HybridRetrieval: news retrieval done. chunks=%d", len(news_chunks))

        # ── 4. Merge ───────────────────────────────────────────────────────────
        ctx = HybridContext(
            sql_context=sql_context,
            companies=sql_context.companies,
            document_chunks=doc_chunks,
            news_chunks=news_chunks,
            has_sql_data=has_sql,
            has_document_data=bool(doc_chunks),
            has_news_data=bool(news_chunks),
        )
        logger.info("HybridRetrieval: merged. sql=%s docs=%s news=%s", has_sql, bool(doc_chunks), bool(news_chunks))
        return ctx

