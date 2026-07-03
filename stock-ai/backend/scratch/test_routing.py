"""
test_routing.py — Verify query classification, follow-ups, and short-circuit response logic.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_routing")

# Add project root to python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.database.database import SessionLocal
from app.services.ai_service import get_ai_service
from app.services.db_service import DBService
from app.services.context_builder import ContextBuilder
from app.services.rag_service import RAGService
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.prompt_builder import get_prompt_builder
from app.services.news.news_service import NewsServiceFactory
from app.services.rag.retrieval_service import (
    get_document_retrieval_service, get_news_retrieval_service
)
from app.services.chat_service import ChatService
from app.services.query_classifier import ClassifierIntent, QueryClassifier, ClassificationResponse
from app.planner.retrieval_planner import RetrievalPlanner


def call_with_retry(func, *args, max_retries: int = 5, initial_backoff: float = 5.0, **kwargs):
    """Wrapper that retries Gemini calls on rate limits (429)."""
    backoff = initial_backoff
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                logger.warning("Gemini rate limit hit (429). Retrying in %s seconds...", backoff)
                time.sleep(backoff)
                backoff *= 1.5
            else:
                raise exc
    raise RuntimeError("Exceeded maximum retries for Gemini call due to rate limits.")


def test_routing() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        # 1. Resolve DI pipeline
        db_service = DBService(db=db)
        ai_service = get_ai_service()
        rag_service = RAGService(settings)
        doc_retrieval = get_document_retrieval_service()
        news_retrieval = get_news_retrieval_service()
        prompt_builder = get_prompt_builder()
        
        news_service = NewsServiceFactory.create_news_service(settings)
        
        from app.services.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever(
            settings=settings,
            ai_service=ai_service,
            db_session=db,
        )
        
        hybrid = HybridRetrievalService(
            db_service=db_service,
            document_retrieval=doc_retrieval,
            news_retrieval=news_retrieval,
            news_service=news_service,
            hybrid_retriever=retriever,
        )
        
        chat_service = ChatService(
            ai_service=ai_service,
            db_service=db_service,
            context_builder=ContextBuilder(),
            rag_service=rag_service,
            hybrid_retrieval_service=hybrid,
            prompt_builder=prompt_builder
        )

        classifier = chat_service._query_classifier
        planner = chat_service._retrieval_planner
        memory = chat_service._session_memory

        logger.info("=========================================")
        logger.info("RUNNING ROUTING & SHORT-CIRCUIT TESTS")
        logger.info("=========================================")

        # Test cases: (query, expected_intent, expects_short_circuit, expect_keyword_in_answer)
        test_cases = [
            ("Hello", ClassifierIntent.GREETING, True, "Stock Research Assistant"),
            ("Hi", ClassifierIntent.GREETING, True, "Stock Research Assistant"),
            ("Who are you?", ClassifierIntent.CAPABILITY, True, "Stock Research Assistant"),
            ("What can you do?", ClassifierIntent.CAPABILITY, True, "Stock Research Assistant"),
            ("Help", ClassifierIntent.HELP, True, "Stock Research Assistant"),
            ("Thank you", ClassifierIntent.THANKS, True, "welcome"),
            ("Bye", ClassifierIntent.GOODBYE, True, "Goodbye"),
            ("Who won IPL?", ClassifierIntent.UNSUPPORTED, True, "designed to answer"),
            ("What is today's weather?", ClassifierIntent.UNSUPPORTED, True, "designed to answer"),
            ("Revenue of TCS", ClassifierIntent.FINANCIAL_METRIC, False, "TCS"),
            ("Latest news on Infosys", ClassifierIntent.LATEST_NEWS, False, "Infosys"),
            ("Summarize TCS annual report", ClassifierIntent.ANNUAL_REPORT, False, "TCS"),
            ("Compare TCS and Infosys", ClassifierIntent.COMPANY_COMPARISON, False, "TCS"),
        ]

        for query, expected_intent, expects_sc, keyword in test_cases:
            logger.info("-----------------------------------------")
            logger.info("Testing Query: %r", query)
            
            # Rate limit mitigation: sleep 4.5 seconds between requests
            time.sleep(4.5)

            # Step 1: Check Classifier with retries
            res = call_with_retry(classifier.classify, query)
            logger.info("Detected Intent: %s (Expected: %s)", res.intent.value, expected_intent.value)
            
            # Step 2: Check Plan
            plan = planner.create_plan(res.intent)
            logger.info("Plan Explanation: %s", plan.explanation)
            logger.info("Short-circuit Status: %s (Expected: %s)", plan.short_circuit, expects_sc)
            assert plan.short_circuit == expects_sc, f"Plan short-circuit status wrong for {query}"

            # Step 3: Run Service Orchestrator with retries
            resp = call_with_retry(chat_service.answer_news, query, session_id="test_session")
            logger.info("Response Snippet: %r", resp.answer[:120])
            assert keyword.lower() in resp.answer.lower(), f"Response missing expected keyword {keyword!r} for query {query!r}"

        # Test Case 11: Follow-up resolution
        logger.info("-----------------------------------------")
        logger.info("Testing Follow-up pronoun resolution: 'What is its profit?' after querying 'TCS'")
        
        # Seed conversation memory with context about TCS
        memory.clear("follow_up_session")
        memory.add_message("follow_up_session", "user", "What is the revenue of TCS?")
        memory.add_message("follow_up_session", "assistant", "TCS reported a revenue of Rs. 240,893 crore.")
        
        follow_up_query = "What is its profit?"
        
        time.sleep(4.5)
        # Test classifier detects follow-up
        res_follow = call_with_retry(classifier.classify, follow_up_query)
        logger.info("Raw Follow-up intent detected: %s (Expected: follow_up)", res_follow.intent.value)
        assert res_follow.intent == ClassifierIntent.FOLLOW_UP, "Query should be classified as a follow-up"
        
        time.sleep(4.5)
        # Verify resolution rewriting
        resolved = call_with_retry(chat_service._resolve_follow_up, follow_up_query, "follow_up_session")
        logger.info("Resolved coreference: %r", resolved)
        assert "tcs" in resolved.lower(), "Coreference resolution failed to resolve 'its' to 'TCS'"
        
        time.sleep(4.5)
        # Route resolved query
        resp_resolved = call_with_retry(chat_service.answer_news, follow_up_query, session_id="follow_up_session")
        logger.info("Follow-up response snippet: %r", resp_resolved.answer[:120])
        assert "tcs" in resp_resolved.answer.lower() or "profit" in resp_resolved.answer.lower(), "Response failed to process resolved follow-up"

        logger.info("=========================================")
        logger.info("ALL ROUTING TESTS COMPLETED SUCCESSFULLY!")
        logger.info("=========================================")

    finally:
        db.close()


if __name__ == "__main__":
    test_routing()
