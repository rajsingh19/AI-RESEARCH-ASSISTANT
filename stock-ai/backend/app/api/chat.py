"""API router — DI wiring for all chat endpoints, including SSE streaming."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Any
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.config import get_settings
from app.database.database import get_db
from app.models.chat import ChatRequest, ChatResponse, HybridChatResponse, NewsResponse, IntentType
from app.models.conversation import Conversation, Message
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

    # Run Company Detector for overrides & low-confidence clarification checks (Problem 5 & 8)
    from app.services.company_detector import CompanyDetector
    detector = CompanyDetector(svc._ai)
    det_ticker, det_name, det_confidence = detector.detect(question_to_search)

    is_stock_intent = class_res.intent.value in {
        "financial_metric", "company_overview", "company_comparison", 
        "annual_report", "earnings_call", "filings", "latest_news", "hybrid_analysis"
    }
    if is_stock_intent and det_confidence < 0.7 and not eq.company_identifiers:
        clarification_msg = "I couldn't confidently identify which company you are asking about. Could you please specify the company name or ticker?"
        svc._session_memory.add_message(session_id, "user", question)
        svc._session_memory.add_message(session_id, "assistant", clarification_msg)
        return StreamingResponse(
            quick_reject_generator(
                clarification_msg,
                {"intent": legacy_intent, "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": []}
            ),
            media_type="text/event-stream"
        )

    if det_ticker and det_confidence >= 0.7:
        if not eq.company_identifiers or det_ticker not in eq.company_identifiers:
            if len(eq.company_identifiers) <= 1:
                eq.company_identifiers = [det_ticker]

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


# --- CONVERSATION HISTORY REDESIGN ENDPOINTS ---

class ConversationCreate(BaseModel):
    id: str | None = None
    title: str | None = "New Chat"


class MessageCreate(BaseModel):
    content: str | None = None
    question: str | None = None


@router.get("/api/conversations", summary="Get all conversations list")
def get_conversations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    from sqlalchemy import desc
    conversations = db.query(Conversation).order_by(desc(Conversation.updated_at)).all()
    return [
        {
            "id": conv.id,
            "title": conv.title,
            "createdAt": conv.created_at.isoformat(),
            "updatedAt": conv.updated_at.isoformat()
        }
        for conv in conversations
    ]


@router.get("/api/conversations/{id}", summary="Get conversation details by id")
def get_conversation(id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from fastapi import HTTPException
    conv = db.query(Conversation).filter(Conversation.id == id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    serialized_messages = []
    for msg in conv.messages:
        serialized_messages.append({
            "id": msg.id,
            "conversationId": msg.conversation_id,
            "role": msg.role,
            "content": msg.content,
            "answer": msg.content,  # for compatibility
            "timestamp": msg.timestamp.isoformat(),
            "intent": msg.intent,
            "companies": json.loads(msg.companies) if msg.companies else [],
            "metrics": json.loads(msg.metrics) if msg.metrics else [],
            "financial_data": json.loads(msg.financial_data) if msg.financial_data else {},
            "documents": json.loads(msg.documents) if msg.documents else [],
            "news": json.loads(msg.news) if msg.news else [],
            "sources": json.loads(msg.sources) if msg.sources else [],
            "warnings": json.loads(msg.warnings) if msg.warnings else []
        })
        
    return {
        "id": conv.id,
        "title": conv.title,
        "createdAt": conv.created_at.isoformat(),
        "updatedAt": conv.updated_at.isoformat(),
        "messages": serialized_messages
    }


@router.post("/api/conversations", summary="Create a new conversation")
def create_conversation(req: ConversationCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    conv_id = req.id or f"conv_{uuid.uuid4().hex[:12]}"
    existing = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if existing:
        return {
            "id": existing.id,
            "title": existing.title,
            "messages": []
        }
    
    new_conv = Conversation(
        id=conv_id,
        title=req.title or "New Chat",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    return {
        "id": new_conv.id,
        "title": new_conv.title,
        "messages": []
    }


@router.delete("/api/conversations/{id}", summary="Delete conversation by id")
def delete_conversation(id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from fastapi import HTTPException
    conv = db.query(Conversation).filter(Conversation.id == id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"status": "success", "message": "Conversation deleted successfully"}


def generate_chat_title(question: str, ai_service: GeminiAIService) -> str:
    prompt = (
        f"Given the user's first chat query: \"{question}\"\n"
        f"Generate a very short, clean title for the conversation (max 4-5 words, no quotes or prefix). "
        f"Example: 'Reliance vs TCS' or 'Nestle India Revenue'. Return only the clean title."
    )
    try:
        response = ai_service.client.models.generate_content(
            model=ai_service.settings.gemini_model,
            contents=prompt,
        )
        if response.text:
            cleaned_title = response.text.strip().replace('"', '').replace("'", "")
            if len(cleaned_title) > 50:
                cleaned_title = cleaned_title[:47] + "..."
            return cleaned_title
    except Exception:
        pass
    return question[:40] + "..." if len(question) > 40 else question


@router.post("/api/conversations/{id}/messages", summary="Add a user message and run query")
def add_message(
    id: str,
    req: MessageCreate,
    db: Session = Depends(get_db),
    svc: ChatService = Depends(get_chat_service)
) -> dict[str, Any]:
    from fastapi import HTTPException
    conv = db.query(Conversation).filter(Conversation.id == id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    question_content = req.content or req.question
    if not question_content or not question_content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty")
        
    # 1. Add user message
    user_msg = Message(
        conversation_id=id,
        role="user",
        content=question_content,
        timestamp=datetime.utcnow()
    )
    db.add(user_msg)
    db.commit()
    
    # 2. Check and generate title if it is the first user message
    user_msg_count = db.query(Message).filter(Message.conversation_id == id, Message.role == "user").count()
    if user_msg_count == 1:
        title = generate_chat_title(question_content, svc._ai)
        conv.title = title
        db.commit()
        
    # 3. Synchronize database messages to session memory store (for coreference resolution)
    session_memory_store.clear(id)
    db_messages = db.query(Message).filter(Message.conversation_id == id).order_by(Message.timestamp.asc()).all()
    for msg in db_messages:
        session_memory_store.add_message(id, msg.role, msg.content)
        
    # 4. Invoke answer generation pipeline
    res = svc.answer_news(question_content, id)
    
    # 5. Extract reports and news model dumps to safely serialize
    serialized_docs = []
    if res.documents:
        for d in res.documents:
            if hasattr(d, "model_dump"):
                serialized_docs.append(d.model_dump())
            else:
                serialized_docs.append(dict(d))
                
    serialized_news = []
    if res.news:
        for n in res.news:
            if hasattr(n, "model_dump"):
                serialized_news.append(n.model_dump())
            else:
                serialized_news.append(dict(n))
                
    # 6. Save assistant response
    assistant_msg = Message(
        conversation_id=id,
        role="assistant",
        content=res.answer,
        timestamp=datetime.utcnow(),
        intent=str(res.intent) if res.intent else None,
        companies=json.dumps(res.companies) if res.companies else "[]",
        metrics=json.dumps(res.metrics) if res.metrics else "[]",
        financial_data=json.dumps(res.financial_data) if res.financial_data else "{}",
        documents=json.dumps(serialized_docs),
        news=json.dumps(serialized_news),
        sources=json.dumps(res.sources) if res.sources else "[]",
        warnings=json.dumps(res.warnings) if res.warnings else "[]"
    )
    db.add(assistant_msg)
    
    # Update updated_at for grouping / sorting ordering
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assistant_msg)
    
    # 7. Return serialized assistant message dictionary
    return {
        "id": assistant_msg.id,
        "conversationId": assistant_msg.conversation_id,
        "role": assistant_msg.role,
        "content": assistant_msg.content,
        "answer": assistant_msg.content,  # for compatibility
        "timestamp": assistant_msg.timestamp.isoformat(),
        "intent": assistant_msg.intent,
        "companies": res.companies or [],
        "metrics": res.metrics or [],
        "financial_data": res.financial_data or {},
        "documents": serialized_docs,
        "news": serialized_news,
        "sources": res.sources or [],
        "warnings": res.warnings or []
    }


@router.post("/api/conversations/{id}/messages/stream", summary="Stream assistant response for a conversation session")
async def stream_conversation_message(
    id: str,
    req: MessageCreate,
    db: Session = Depends(get_db),
    svc: ChatService = Depends(get_chat_service),
    ai_service: GeminiAIService = Depends(get_ai_service)
) -> StreamingResponse:
    from fastapi import HTTPException
    conv = db.query(Conversation).filter(Conversation.id == id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    question_content = req.content or req.question
    if not question_content or not question_content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty")
        
    # 1. Add user message
    user_msg = Message(
        conversation_id=id,
        role="user",
        content=question_content,
        timestamp=datetime.utcnow()
    )
    db.add(user_msg)
    db.commit()
    
    # 2. Check and generate title if it is the first user message
    user_msg_count = db.query(Message).filter(Message.conversation_id == id, Message.role == "user").count()
    if user_msg_count == 1:
        title = generate_chat_title(question_content, svc._ai)
        conv.title = title
        db.commit()
        
    # 3. Synchronize database messages to session memory store (for coreference resolution)
    session_memory_store.clear(id)
    db_messages = db.query(Message).filter(Message.conversation_id == id).order_by(Message.timestamp.asc()).all()
    for msg in db_messages:
        session_memory_store.add_message(id, msg.role, msg.content)
        
    # 4. Load retrieval context
    class_res = svc._query_classifier.classify(question_content)
    plan = svc._retrieval_planner.create_plan(class_res.intent)
    legacy_intent = LEGACY_INTENT_MAP.get(class_res.intent, IntentType.UNKNOWN)
    required_dims = svc._detector.determine_required_data(question_content, class_res.intent.value)
    
    catalog = svc._db.get_company_catalog()
    eq = svc._ai.extract_query(question=question_content, company_catalog=catalog)
    eq.intent = legacy_intent
    
    from app.services.company_detector import CompanyDetector
    detector = CompanyDetector(svc._ai)
    det_ticker, det_name, det_confidence = detector.detect(question_content)
    
    is_stock_intent = class_res.intent.value in {
        "financial_metric", "company_overview", "company_comparison", 
        "annual_report", "earnings_call", "filings", "latest_news", "hybrid_analysis"
    }
    
    async def quick_reject_generator(message: str, metadata: dict) -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'token': message})}\n\n"
        yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
        yield "event: close\ndata: {}\n\n"
        # Also save to database
        assistant_msg = Message(
            conversation_id=id,
            role="assistant",
            content=message,
            timestamp=datetime.utcnow(),
            intent="unknown",
            companies="[]",
            metrics="[]",
            financial_data="{}",
            documents="[]",
            news="[]",
            sources="[]",
            warnings="[]"
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.utcnow()
        db.commit()

    if is_stock_intent and det_confidence < 0.7 and not eq.company_identifiers:
        clarification_msg = "I couldn't confidently identify which company you are asking about. Could you please specify the company name or ticker?"
        return StreamingResponse(
            quick_reject_generator(
                clarification_msg,
                {"intent": legacy_intent, "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": []}
            ),
            media_type="text/event-stream"
        )
        
    if det_ticker and det_confidence >= 0.7:
        if not eq.company_identifiers or det_ticker not in eq.company_identifiers:
            if len(eq.company_identifiers) <= 1:
                eq.company_identifiers = [det_ticker]
                
    # Synchronize database messages again to capture any session updates
    session_memory_store.clear(id)
    db_messages = db.query(Message).filter(Message.conversation_id == id).order_by(Message.timestamp.asc()).all()
    for msg in db_messages:
        session_memory_store.add_message(id, msg.role, msg.content)
        
    import time
    from app.utils.metrics_logger import MetricsLogger
    metrics = MetricsLogger(question_content)
    metrics.log_intent(class_res.intent.value)
    metrics.log_plan(plan.explanation)
    
    ctx = svc._retrieve_with_plan(question_content, eq, plan, metrics, required_dims)
    
    tickers = eq.company_identifiers or [c.ticker for c in ctx.companies]
    if ctx.document_chunks:
        ctx.document_chunks = svc._search_reranker.rerank_documents(ctx.document_chunks, tickers)
        ctx.has_document_data = bool(ctx.document_chunks)
    if ctx.news_chunks:
        ctx.news_chunks = svc._search_reranker.rerank_news(ctx.news_chunks, tickers)
        ctx.has_news_data = bool(ctx.news_chunks)
        
    if not ctx.has_sql_data and not ctx.has_document_data and not ctx.has_news_data:
        suggestions = svc._suggest_similar_companies(question_content)
        suggestion_str = ", ".join(suggestions)
        fallback_msg = f"I couldn't find any financial records or news for {', '.join(tickers) if tickers else 'the requested company'}. Did you mean: {suggestion_str}?"
        return StreamingResponse(
            quick_reject_generator(
                fallback_msg,
                {"intent": legacy_intent, "companies": [], "metrics": [], "financial_data": {},
                 "documents": [], "news": [], "sources": [], "warnings": []}
            ),
            media_type="text/event-stream"
        )
        
    eq = svc._ensure_metrics(eq, ctx.sql_context)
    ctx.sql_context.requested_metrics = list(eq.metrics)
    
    from app.services.financial_reasoning_service import FinancialReasoningService
    reasoning_engine = FinancialReasoningService()
    rc = reasoning_engine.analyze(question_content, ctx)
    prompt = svc._prompt.build(question=question_content, hybrid_context=ctx, reasoning_context=rc)
    metrics.record_prompt(prompt)
    
    confidence = ConfidenceScorer.compute(
        sql_found=ctx.has_sql_data,
        doc_count=len(ctx.document_chunks),
        news_count=len(ctx.news_chunks)
    )
    sources = CitationFormatter.get_sources_list(ctx.has_sql_data, ctx.document_chunks, ctx.news_chunks)
    
    serialized_docs = []
    if ctx.document_chunks:
        for d in ctx.document_chunks:
            serialized_docs.append(d.model_dump())
            
    serialized_news = []
    if ctx.news_chunks:
        for n in ctx.news_chunks:
            serialized_news.append(n.model_dump())
            
    meta_payload = {
        "intent": legacy_intent,
        "companies": [c.ticker for c in ctx.companies],
        "metrics": list(eq.metrics),
        "financial_data": svc._structured_data(ctx.companies),
        "documents": serialized_docs,
        "news": serialized_news,
        "sources": sources,
        "warnings": ctx.sql_context.unavailable_identifiers,
        "confidence": confidence
    }
    
    streamer = TokenStreamer(ai_service)
    
    # SSE stream generator wrapper that saves full message to SQLite on close
    async def database_saving_streamer() -> AsyncGenerator[str, None]:
        full_answer = []
        async for event in streamer.stream_response(prompt, meta_payload):
            yield event
            
            # Parse answer token blocks
            if event.startswith("data: "):
                try:
                    event_data = json.loads(event[6:-2])
                    if "token" in event_data:
                        full_answer.append(event_data["token"])
                except Exception:
                    pass
                    
        # Save assistant message to SQLite
        final_answer = "".join(full_answer)
        assistant_msg = Message(
            conversation_id=id,
            role="assistant",
            content=final_answer,
            timestamp=datetime.utcnow(),
            intent=str(legacy_intent),
            companies=json.dumps([c.ticker for c in ctx.companies]),
            metrics=json.dumps(list(eq.metrics)),
            financial_data=json.dumps(svc._structured_data(ctx.companies)),
            documents=json.dumps(serialized_docs),
            news=json.dumps(serialized_news),
            sources=json.dumps(sources),
            warnings=json.dumps(ctx.sql_context.unavailable_identifiers)
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.utcnow()
        db.commit()
        
    return StreamingResponse(
        database_saving_streamer(),
        media_type="text/event-stream"
    )


