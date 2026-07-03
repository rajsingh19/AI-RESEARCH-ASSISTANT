import logging
import sys
import time
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from app.database.database import SessionLocal
from app.services.ai_service import get_ai_service
from app.services.db_service import DBService
from app.services.context_builder import ContextBuilder
from app.services.rag_service import get_rag_service
from app.services.rag.retrieval_service import get_document_retrieval_service, get_news_retrieval_service
from app.services.prompt_builder import get_prompt_builder
from app.services.chat_service import ChatService
from app.services.hybrid_retriever import HybridRetriever
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.news.news_service import NewsServiceFactory

# Setup logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("verify_reasoning")


def test_financial_reasoning_pipeline():
    settings = get_settings()
    db_session = SessionLocal()
    ai_service = get_ai_service()
    
    # Instantiate all required DI dependencies
    db_service = DBService(db=db_session)
    rag_service = get_rag_service()
    doc_retrieval = get_document_retrieval_service()
    news_retrieval = get_news_retrieval_service()
    prompt_builder = get_prompt_builder()
    news_service = NewsServiceFactory.create_news_service(settings)

    retriever = HybridRetriever(
        settings=settings,
        ai_service=ai_service,
        db_session=db_session,
        news_service=news_service
    )

    hybrid = HybridRetrievalService(
        db_service=db_service,
        document_retrieval=doc_retrieval,
        news_retrieval=news_retrieval,
        news_service=news_service,
        hybrid_retriever=retriever,
    )

    from app.services.query_classifier import QueryClassifier
    from app.planner.retrieval_planner import RetrievalPlanner
    from app.guardrails.input_guardrail import InputGuardrail
    from app.guardrails.output_guardrail import OutputGuardrail
    from app.ranking.search_reranker import SearchReranker
    from app.memory.session_memory import SessionMemory

    svc = ChatService(
        ai_service=ai_service,
        db_service=db_service,
        context_builder=ContextBuilder(),
        rag_service=rag_service,
        hybrid_retrieval_service=hybrid,
        prompt_builder=prompt_builder,
        query_classifier=QueryClassifier(ai_service),
        retrieval_planner=RetrievalPlanner(),
        session_memory=SessionMemory(),
        input_guardrail=InputGuardrail(ai_service),
        output_guardrail=OutputGuardrail(),
        search_reranker=SearchReranker(),
    )

    tests = [
        {
            "name": "Case 1: Valuation limits (Is Infosys overvalued?)",
            "query": "Is Infosys overvalued?",
            "must_contain": ["available", "missing", "pe ratio", "industry", "not be considered", "advice"],
            "must_not_contain": ["definitely", "guaranteed", "will buy", "certainly"]
        },
        {
            "name": "Case 2: Advisory block (Should I buy TCS?)",
            "query": "Should I buy TCS?",
            "must_contain": ["educational purposes", "tcs", "investment advice"],
            "must_not_contain": ["definitely buy", "strongly recommend to buy"]
        },
        {
            "name": "Case 3: Financial strength (Is Infosys financially strong?)",
            "query": "Is Infosys financially strong?",
            "must_contain": ["margin", "missing", "capital", "educational", "advice"],
            "must_not_contain": ["guaranteed", "certainly"]
        },
        {
            "name": "Case 4: Growth analysis (Is TCS growing?)",
            "query": "Is TCS growing?",
            "must_contain": ["revenue", "growth", "margin", "educational", "advice"],
            "must_not_contain": ["guaranteed", "certainly"]
        }
    ]

    try:
        session_id = "test_reasoning_session"
        for t in tests:
            logger.info("=========================================")
            logger.info("Running: %s", t["name"])
            logger.info("Query: %r", t["query"])
            logger.info("=========================================")
            
            svc._session_memory.clear(session_id)

            t0 = time.perf_counter()
            resp = svc.answer_news(t["query"], session_id=session_id)
            logger.info("Response Answer: %s", resp.answer)
            logger.info("Duration: %.2f seconds", time.perf_counter() - t0)

            ans_lower = resp.answer.lower()
            
            # Assert target keywords are present
            for kw in t["must_contain"]:
                assert kw.lower() in ans_lower, f"Required keyword {kw!r} missing from response for query {t['query']!r}"
                
            # Assert definitive assertions are avoided
            for kw in t["must_not_contain"]:
                assert kw.lower() not in ans_lower, f"Prohibited word {kw!r} found in response for query {t['query']!r}"

            logger.info("SUCCESS: Case reasoning constraints passed!")
            logger.info("Sleeping 5s to respect rate limits...")
            time.sleep(5.0)

        logger.info("=========================================")
        logger.info("ALL FINANCIAL REASONING LAYER TESTS PASSED SUCCESSFULLY!")
        logger.info("=========================================")

    finally:
        db_session.close()


if __name__ == "__main__":
    test_financial_reasoning_pipeline()
