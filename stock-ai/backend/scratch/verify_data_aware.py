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

# Setup logging to console so we can check structured outputs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("verify_data_aware")


def test_data_aware_pipeline():
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

    # List of queries to verify each data-aware retrieval dimension
    tests = [
        {
            "name": "Case 1: Cold start fetching for SBI (Missing metrics/metadata)",
            "query": "SBI overview",
            "keywords": ["SBI", "State Bank", "revenue", "sector"]
        },
        {
            "name": "Case 2: Competitor search for TCS (Inject metadata)",
            "query": "What about its competitors?",  # Relies on session memory context
            "setup_session": True,
            "session_turns": [("user", "Tell me about TCS"), ("assistant", "TCS is a global IT services firm.")],
            "keywords": ["competitor", "INFY", "WIPRO", "HCL"]
        },
        {
            "name": "Case 3: Historical margins for TCS (Fetch 5-year financials)",
            "query": "margins, ROE, ROCE, and revenue growth of TCS over the last 5 years",
            "keywords": ["TCS", "growth", "margins", "ROE", "ROCE", "revenue"]
        },
        {
            "name": "Case 4: Dividends payout for INFY (Fetch dividends yields)",
            "query": "Dividend history of INFY",
            "keywords": ["INFY", "dividend", "yield", "payout"]
        }
    ]

    try:
        for t in tests:
            logger.info("=========================================")
            logger.info("Running: %s", t["name"])
            logger.info("Query: %r", t["query"])
            logger.info("=========================================")
            
            # Setup session history if required for follow-up testing
            session_id = "test_data_aware_session"
            if t.get("setup_session"):
                svc._session_memory.clear(session_id)
                for role, msg in t["session_turns"]:
                    svc._session_memory.add_message(session_id, role, msg)
            else:
                svc._session_memory.clear(session_id)

            # Execution
            t0 = time.perf_counter()
            resp = svc.answer_news(t["query"], session_id=session_id)
            logger.info("Response Answer: %s", resp.answer)
            logger.info("Structured Data: %s", resp.financial_data)
            logger.info("Duration: %.2f seconds", time.perf_counter() - t0)

            # Assertions
            ans_lower = resp.answer.lower()
            for kw in t["keywords"]:
                assert kw.lower() in ans_lower, f"Expected keyword {kw!r} missing from response for query {t['query']!r}"

            logger.info("SUCCESS: Case verified!")
            # Delay to avoid hitting rate limits
            logger.info("Sleeping 5s to respect rate limits...")
            time.sleep(5.0)

        logger.info("=========================================")
        logger.info("ALL DATA-AWARE PIPELINE TESTS PASSED SUCCESSFULLY!")
        logger.info("=========================================")

    finally:
        db_session.close()


if __name__ == "__main__":
    test_data_aware_pipeline()
