"""API router — DI wiring for all chat endpoints, including SSE streaming."""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Any
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.database import get_db
from app.models.chat import ChatRequest, ChatResponse, HybridChatResponse, NewsResponse, IntentType
from app.services.ai_service import GeminiAIService, get_ai_service
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.db_service import DBService
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.news.news_service import NewsServiceFactory
from app.services.prompt_builder import PromptBuilder, get_prompt_builder
from app.services.rag.retrieval_service import (
    DocumentRetrievalService, NewsRetrievalService,
    get_document_retrieval_service, get_news_retrieval_service,
)
from app.services.rag_service import RAGService, get_rag_service

# Feature additions
from app.memory.session_memory import SessionMemory
from app.streaming.stream_handler import TokenStreamer
from app.services.query_classifier import ClassifierIntent, LEGACY_INTENT_MAP
from app.utils.confidence_scorer import ConfidenceScorer
from app.utils.citation_formatter import CitationFormatter

logger = logging.getLogger(__name__)
router = APIRouter()

# Instantiate Session Memory as a module-level singleton to persist history across HTTP requests
session_memory_store = SessionMemory()


def get_db_service(db: Session = Depends(get_db)) -> DBService:
    return DBService(db=db)


def get_chat_service(
    db_service: DBService = Depends(get_db_service),
    ai_service: GeminiAIService = Depends(get_ai_service),
    rag_service: RAGService = Depends(get_rag_service),
    doc_retrieval: DocumentRetrievalService = Depends(get_document_retrieval_service),
    news_retrieval: NewsRetrievalService = Depends(get_news_retrieval_service),
    prompt_builder: PromptBuilder = Depends(get_prompt_builder),
) -> ChatService:
    settings = get_settings()
    news_service = NewsServiceFactory.create_news_service(settings)

    from app.services.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever(
        settings=settings,
        ai_service=ai_service,
        db_session=db_service.db,
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

    return ChatService(
        ai_service=ai_service,
        db_service=db_service,
        context_builder=ContextBuilder(),
        rag_service=rag_service,
        hybrid_retrieval_service=hybrid,
        prompt_builder=prompt_builder,
        query_classifier=QueryClassifier(ai_service),
        retrieval_planner=RetrievalPlanner(),
        session_memory=session_memory_store,
        input_guardrail=InputGuardrail(ai_service),
        output_guardrail=OutputGuardrail(),
        search_reranker=SearchReranker(),
    )


@router.post("/chat", response_model=NewsResponse,
             summary="Phase 9 — SQLite + Docs + Cache-first Live News")
def chat(request: ChatRequest, svc: ChatService = Depends(get_chat_service)) -> NewsResponse:
    # Read/write from query parameters if frontend supplies session_id
    session_id = getattr(request, "session_id", "default_session") or "default_session"
    return svc.answer_news(request.question, session_id)


@router.post("/chat/hybrid", response_model=HybridChatResponse,
             summary="Phase 7 — SQLite + ChromaDB docs (no news)")
def chat_hybrid(request: ChatRequest, svc: ChatService = Depends(get_chat_service)) -> HybridChatResponse:
    session_id = getattr(request, "session_id", "default_session") or "default_session"
    return svc.answer_hybrid(request.question, session_id)


@router.post("/chat/news", response_model=NewsResponse,
             summary="Phase 9 — SQLite + Docs + Cache-first Live News")
def chat_news(request: ChatRequest, svc: ChatService = Depends(get_chat_service)) -> NewsResponse:
    session_id = getattr(request, "session_id", "default_session") or "default_session"
    return svc.answer_news(request.question, session_id)


@router.post("/chat/stream", summary="Feature 10 — Token streaming response via SSE")
async def chat_stream(
    request: ChatRequest,
    svc: ChatService = Depends(get_chat_service),
    ai_service: GeminiAIService = Depends(get_ai_service),
) -> StreamingResponse:
    """
    FastAPI streaming endpoint.
    Performs classifier, Planner, Guardrails, and Retrieval synchronously,
    then yields tokens chunk-by-chunk using Server-Sent Events (SSE).
    """
    logger.info("Streaming route triggered. Query: %r", request.question)
    session_id = getattr(request, "session_id", "default_session") or "default_session"
    question = request.question

    # Helper generator for quick greetings or guardrail rejections
    async def quick_reject_generator(message: str, metadata: dict) -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'token': message})}\n\n"
        yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
        yield "event: close\ndata: {}\n\n"

    # 1. Evaluate safety
    is_safe, reject_msg = svc._input_guardrail.evaluate(question)
    if not is_safe:
        return StreamingResponse(
            quick_reject_generator(
                reject_msg,
                {"intent": "unknown", "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": ["Query blocked by safety guardrails"]}
            ),
            media_type="text/event-stream"
        )

    # 2. Query Intent Classification
    class_res = svc._query_classifier.classify(question)

    # 3. Follow-up query resolution
    if class_res.intent == ClassifierIntent.FOLLOW_UP:
        resolved_question = svc._resolve_follow_up(question, session_id)
        class_res = svc._query_classifier.classify(resolved_question)
        question_to_search = resolved_question
    else:
        question_to_search = question

    # 4. Retrieval Planning
    plan = svc._retrieval_planner.create_plan(class_res.intent)
    legacy_intent = LEGACY_INTENT_MAP.get(class_res.intent, IntentType.UNKNOWN)
    required_dims = svc._detector.determine_required_data(question_to_search, class_res.intent.value)

    # Short-circuit trigger (Greeting / Capability / Thanks / Goodbye / Help / Unsupported)
    if plan.short_circuit:
        logger.info(
            "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = YES | Reason: %s",
            class_res.intent.value, plan.explanation, "Greeting or unsupported command"
        )
        svc._session_memory.add_message(session_id, "user", question)
        svc._session_memory.add_message(session_id, "assistant", plan.short_circuit_response or "")
        return StreamingResponse(
            quick_reject_generator(
                plan.short_circuit_response or "",
                {"intent": legacy_intent, "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": []}
            ),
            media_type="text/event-stream"
        )

    logger.info(
        "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = NO | Reason: Domain stock query",
        class_res.intent.value, plan.explanation
    )

    # 5. Ingestion & Retrieval
    catalog = svc._db.get_company_catalog()
    eq = svc._ai.extract_query(question=question_to_search, company_catalog=catalog)
    eq.intent = legacy_intent

    # Retrieve contexts based on plan
    import time
    from app.utils.metrics_logger import MetricsLogger
    metrics = MetricsLogger(question)
    metrics.log_intent(class_res.intent.value)
    metrics.log_plan(plan.explanation)

    ctx = svc._retrieve_with_plan(question_to_search, eq, plan, metrics, required_dims)

    # 6. Rerank
    tickers = eq.company_identifiers or [c.ticker for c in ctx.companies]
    if ctx.document_chunks:
        ctx.document_chunks = svc._search_reranker.rerank_documents(ctx.document_chunks, tickers)
        ctx.has_document_data = bool(ctx.document_chunks)
    if ctx.news_chunks:
        ctx.news_chunks = svc._search_reranker.rerank_news(ctx.news_chunks, tickers)
        ctx.has_news_data = bool(ctx.news_chunks)

    # No contexts fallback
    if not ctx.has_sql_data and not ctx.has_document_data and not ctx.has_news_data:
        suggestions = svc._suggest_similar_companies(question_to_search)
        suggestion_str = ", ".join(suggestions)
        metrics.finalize()
        return StreamingResponse(
            quick_reject_generator(
                f"I couldn't find any financial database records or documents matching your query. Did you mean one of these? {suggestion_str}",
                {"intent": legacy_intent, "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": suggestions}
            ),
            media_type="text/event-stream"
        )

    # 7. Format metrics, citations, and confidence
    eq = svc._ensure_metrics(eq, ctx.sql_context)
    ctx.sql_context.requested_metrics = list(eq.metrics)
    
    # Financial Reasoning Layer (Problem 5)
    from app.services.financial_reasoning_service import FinancialReasoningService
    reasoning_engine = FinancialReasoningService()
    rc = reasoning_engine.analyze(question_to_search, ctx)
    prompt = svc._prompt.build(question=question_to_search, hybrid_context=ctx, reasoning_context=rc)
    metrics.record_prompt(prompt)

    confidence = ConfidenceScorer.compute(
        sql_found=ctx.has_sql_data,
        doc_count=len(ctx.document_chunks),
        news_count=len(ctx.news_chunks)
    )
    sources = CitationFormatter.get_sources_list(ctx.has_sql_data, ctx.document_chunks, ctx.news_chunks)

    # Build final metadata dictionary
    meta_payload = {
        "intent": legacy_intent,
        "companies": [c.ticker for c in ctx.companies],
        "metrics": list(eq.metrics),
        "financial_data": svc._structured_data(ctx.companies),
        "documents": [doc.model_dump() for doc in ctx.document_chunks],
        "news": [news.model_dump() for news in ctx.news_chunks],
        "sources": sources,
        "warnings": ctx.sql_context.unavailable_identifiers,
        "confidence": confidence
    }

    # Instantiate TokenStreamer and stream response
    streamer = TokenStreamer(ai_service)
    
    # Save user query to memory
    svc._session_memory.add_message(session_id, "user", question)
    
    # Return StreamingResponse
    return StreamingResponse(
        streamer.stream_response(prompt, meta_payload),
        media_type="text/event-stream"
    )
