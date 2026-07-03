#!/usr/bin/env python3
"""
verify_hybrid.py — Integration and verification script for the upgraded Hybrid Retrieval Architecture.

Usage:
    cd backend
    python verify_hybrid.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings
from app.database.database import SessionLocal, engine, Base
from app.models.company import Company
from app.services.ai_service import get_ai_service
from app.services.hybrid_retriever import HybridRetriever
from app.services.chat_service import ChatService
from app.services.db_service import DBService
from app.services.rag_service import RAGService
from app.services.rag.retrieval_service import get_document_retrieval_service, get_news_retrieval_service
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.news.news_service import NewsServiceFactory
from app.services.prompt_builder import get_prompt_builder
from app.services.context_builder import ContextBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("verify_hybrid")


def verify_all():
    logger.info("Initializing configuration and database connection...")
    settings = get_settings()
    db_session = SessionLocal()
    
    try:
        # 1. Clean up any previous test runs for BHARTIARTL or TATAMOTORS to ensure clean cache-miss state
        logger.info("Cleaning up previous test companies from database...")
        db_session.query(Company).filter(Company.ticker.in_(["BHARTIARTL", "TATAMOTORS"])).delete()
        db_session.commit()

        ai_service = get_ai_service()
        
        # Instantiate services
        logger.info("Creating HybridRetriever orchestrator...")
        hybrid_retriever = HybridRetriever(
            settings=settings,
            ai_service=ai_service,
            db_session=db_session
        )

        # Ensure vector service is clean for BHARTIARTL
        hybrid_retriever._vector_service.delete_company_documents("BHARTIARTL")

        # 2. Test Cache Miss on new company ("What is the revenue of Airtel?")
        logger.info("=========================================")
        logger.info("STEP 1: Testing Cache Miss for 'Airtel'...")
        logger.info("=========================================")
        ticker, name = hybrid_retriever.ensure_company_data("What is the revenue of Airtel?")
        
        assert ticker == "BHARTIARTL", f"Expected ticker 'BHARTIARTL', got '{ticker}'"
        assert name is not None, "Expected valid company name"
        logger.info("Successfully detected company: Ticker=%s, Name=%s", ticker, name)

        # 3. Verify SQLite DB entry was created
        company_db = db_session.query(Company).filter(Company.ticker == "BHARTIARTL").first()
        assert company_db is not None, "Failed to write company details to SQLite"
        assert company_db.revenue > 0, "Expected positive revenue figure in SQLite"
        assert company_db.profit != 0, "Expected profit figure in SQLite"
        logger.info("SQLite verification passed! Company row: %r, Revenue=%s Cr", company_db.company_name, company_db.revenue)

        # 4. Verify ChromaDB documents exist
        exists, newest_at = hybrid_retriever._vector_service.check_company_exists("BHARTIARTL")
        assert exists is True, "ChromaDB documents were not stored successfully"
        assert newest_at is not None, "ChromaDB documents are missing a 'retrieved_at' timestamp"
        logger.info("ChromaDB verification passed! Documents cached at: %s", newest_at)

        # 5. Test Cache Hit (No duplicate fetching on subsequent query)
        logger.info("=========================================")
        logger.info("STEP 2: Testing Cache Hit for 'Airtel'...")
        logger.info("=========================================")
        # We can temporarily mock fetcher to ensure it is not called during cache hit
        original_fetch = hybrid_retriever._fetcher.fetch
        
        def mock_fetch(t, n=None):
            raise AssertionError("Fetcher was called during a cache-hit condition!")
            
        hybrid_retriever._fetcher.fetch = mock_fetch
        
        try:
            hit_ticker, hit_name = hybrid_retriever.ensure_company_data("What is Airtel's business summary?")
            assert hit_ticker == "BHARTIARTL"
            logger.info("Cache hit verified! Reused existing database and vector entries.")
        finally:
            # Restore fetcher
            hybrid_retriever._fetcher.fetch = original_fetch

        # 6. Test ChatService rendering & prompt headings
        logger.info("=========================================")
        logger.info("STEP 3: Testing Chat Response Formats...")
        logger.info("=========================================")
        db_service = DBService(db=db_session)
        doc_retrieval = get_document_retrieval_service()
        news_retrieval = get_news_retrieval_service()
        news_service = NewsServiceFactory.create_news_service(settings)
        prompt_builder = get_prompt_builder()

        hybrid_retrieval_service = HybridRetrievalService(
            db_service=db_service,
            document_retrieval=doc_retrieval,
            news_retrieval=news_retrieval,
            news_service=news_service,
            hybrid_retriever=hybrid_retriever
        )
        
        chat_service = ChatService(
            ai_service=ai_service,
            db_service=db_service,
            context_builder=ContextBuilder(),
            rag_service=RAGService(settings),
            hybrid_retrieval_service=hybrid_retrieval_service,
            prompt_builder=prompt_builder
        )

        response = chat_service.answer_news("What is the business summary and net profit of Airtel?")
        logger.info("Final Chat Response Answer Generated:\n%s", response.answer)
        
        # Verify required structural sections are printed in response markdown
        headings = [
            "### Summary",
            "### Financial Metrics",
            "### Supporting Evidence",
            "### Source Citations",
            "### Recent News",
            "### Confidence Level"
        ]
        
        for heading in headings:
            assert heading in response.answer, f"Answer missing mandatory section heading: {heading}"
            
        logger.info("Heading formatting checks passed! All structural sections are present.")
        
        # Verify structured outputs
        assert "BHARTIARTL" in response.financial_data, "Response missing BHARTIARTL metrics"
        assert len(response.documents) > 0, "Response failed to retrieve annual report/profile document chunks"
        logger.info("Financial data snap: %r", response.financial_data["BHARTIARTL"])
        logger.info("Document chunks retrieved: %d", len(response.documents))
        
        logger.info("=========================================")
        logger.info("ALL INTEGRATION VERIFICATIONS PASSED SUCCESSFULLY!")
        logger.info("=========================================")

    finally:
        db_session.close()


if __name__ == "__main__":
    verify_all()
