"""
chat_service.py — Unified service layer orchestrator.
Integrates classifiers, planners, guardrails, memory, reranking, and programmatic metrics.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from google.genai import types

from app.models.chat import (
    ChatResponse, ExtractedQuery, HybridChatResponse,
    IntentType, MetricName, NewsResponse, RetrievalContext,
)
from app.services.ai_service import GeminiAIService
from app.services.context_builder import ContextBuilder, DISCLAIMER
from app.services.db_service import DBService
from app.services.hybrid_retrieval_service import HybridContext, HybridRetrievalService
from app.services.prompt_builder import PromptBuilder
from app.services.rag_service import RAGService

# Production updates (Features 1, 2, 3, 4, 5, 7, 8, 11, 12, 15)
from app.services.query_classifier import QueryClassifier, ClassifierIntent, LEGACY_INTENT_MAP
from app.planner.retrieval_planner import RetrievalPlanner, RetrievalPlan
from app.memory.session_memory import SessionMemory
from app.guardrails.input_guardrail import InputGuardrail
from app.guardrails.output_guardrail import OutputGuardrail
from app.ranking.search_reranker import SearchReranker
from app.utils.confidence_scorer import ConfidenceScorer
from app.utils.citation_formatter import CitationFormatter
from app.utils.metrics_logger import MetricsLogger

# New Data-Aware Imports (Problems 5, 8, 10)
from app.planner.missing_data_detector import MissingDataDetector, DataDimension

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        ai_service: GeminiAIService,
        db_service: DBService,
        context_builder: ContextBuilder,
        rag_service: RAGService,
        hybrid_retrieval_service: HybridRetrievalService,
        prompt_builder: PromptBuilder,
        query_classifier: QueryClassifier | None = None,
        retrieval_planner: RetrievalPlanner | None = None,
        session_memory: SessionMemory | None = None,
        input_guardrail: InputGuardrail | None = None,
        output_guardrail: OutputGuardrail | None = None,
        search_reranker: SearchReranker | None = None,
    ) -> None:
        self._ai = ai_service
        self._db = db_service
        self._ctx_builder = context_builder
        self._rag = rag_service
        self._hybrid = hybrid_retrieval_service
        self._prompt = prompt_builder
        
        # Injected production dependencies
        self._query_classifier = query_classifier or QueryClassifier(ai_service)
        self._retrieval_planner = retrieval_planner or RetrievalPlanner()
        self._session_memory = session_memory or SessionMemory()
        self._input_guardrail = input_guardrail or InputGuardrail(ai_service)
        self._output_guardrail = output_guardrail or OutputGuardrail()
        self._search_reranker = search_reranker or SearchReranker()
        self._detector = MissingDataDetector(
            news_collection_name=ai_service.settings.news_collection_name,
            doc_collection_name=ai_service.settings.chroma_collection_name
        )
        
        # Financial Reasoning Layer (Problem 5)
        from app.services.financial_reasoning_service import FinancialReasoningService
        self._reasoning = FinancialReasoningService()

    def _resolve_follow_up(self, question: str, session_id: str) -> str:
        """Resolve pronouns and coreferences using SessionMemory and Gemini rewrite instructions."""
        history = self._session_memory.format_for_prompt(session_id)
        if not history:
            return question

        prompt = (
            f"You are an assistant that resolves pronouns and coreferences in follow-up stock queries.\n"
            f"Given the conversation history, rewrite the user's follow-up query to be self-contained "
            f"by replacing pronouns (like 'its', 'their', 'this company') with the correct company name.\n"
            f"Do not answer the query; only rewrite it.\n\n"
            f"History:\n{history}\n\n"
            f"Follow-up Query: '{question}'\n\n"
            f"Rewritten Query (only output the rewritten query, nothing else):"
        )
        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                ),
            )
            rewritten = response.text.strip().strip("'\"")
            logger.info("ChatService: Resolved follow-up coreference. Original: %r -> Rewritten: %r", question, rewritten)
            return rewritten
        except Exception as exc:
            logger.error("ChatService: Follow-up coreference resolution failed: %s. Using original query.", exc)
            return question

    # ── Primary Path: SQLite + Docs + News ──────────────────────────────────────

    def answer_news(self, question: str, session_id: str | None = "default_session") -> NewsResponse:
        logger.info("ChatService.answer_news: question=%r session=%s", question, session_id)
        metrics = MetricsLogger(question)

        # 1. Input Guardrails
        is_safe, reject_msg = self._input_guardrail.evaluate(question)
        if not is_safe:
            metrics.log_intent("unsafe")
            metrics.finalize()
            return NewsResponse(
                answer=reject_msg,
                intent=IntentType.UNKNOWN, companies=[], metrics=[],
                financial_data={}, documents=[], news=[], sources=[],
                warnings=["Query blocked by safety guardrails"]
            )

        # 2. Query Intent Classification
        class_res = self._query_classifier.classify(question)

        # 3. Follow-up handling: coreference resolution
        if class_res.intent == ClassifierIntent.FOLLOW_UP:
            resolved_question = self._resolve_follow_up(question, session_id or "default_session")
            class_res = self._query_classifier.classify(resolved_question)
            question_to_search = resolved_question
        else:
            question_to_search = question

        metrics.log_intent(class_res.intent.value)
        legacy_intent = LEGACY_INTENT_MAP.get(class_res.intent, IntentType.UNKNOWN)

        # Determine required data types (Problem 5 & 10)
        required_dims = self._detector.determine_required_data(question_to_search, class_res.intent.value)

        # 4. Retrieval Planning
        plan = self._retrieval_planner.create_plan(class_res.intent)
        metrics.log_plan(plan.explanation)

        # 5. Short-circuit execution (Greetings / Capability / Gratitude / Goodbye / Help / Unsupported)
        if plan.short_circuit:
            logger.info(
                "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = YES | Reason: %s",
                class_res.intent.value, plan.explanation, "Greeting or unsupported command"
            )
            self._session_memory.add_message(session_id or "default_session", "user", question)
            self._session_memory.add_message(session_id or "default_session", "assistant", plan.short_circuit_response or "")
            metrics.record_confidence("High")
            metrics.finalize()
            return NewsResponse(
                answer=plan.short_circuit_response or "",
                intent=legacy_intent, companies=[], metrics=[],
                financial_data={}, documents=[], news=[], sources=[],
                warnings=[]
            )

        logger.info(
            "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = NO | Reason: Domain stock query",
            class_res.intent.value, plan.explanation
        )

        # 6. Intent extraction
        catalog = self._db.get_company_catalog()
        eq = self._ai.extract_query(question=question_to_search, company_catalog=catalog)
        eq.intent = legacy_intent

        # Run Company Detector for overrides & low-confidence clarification checks (Problem 5 & 8)
        from app.services.company_detector import CompanyDetector
        detector = CompanyDetector(self._ai)
        det_ticker, det_name, det_confidence = detector.detect(question_to_search)

        is_stock_intent = class_res.intent.value in {
            "financial_metric", "company_overview", "company_comparison", 
            "annual_report", "earnings_call", "filings", "latest_news", "hybrid_analysis"
        }
        if is_stock_intent and det_confidence < 0.7 and not eq.company_identifiers:
            clarification_msg = "I couldn't confidently identify which company you are asking about. Could you please specify the company name or ticker?"
            self._session_memory.add_message(session_id or "default_session", "user", question)
            self._session_memory.add_message(session_id or "default_session", "assistant", clarification_msg)
            metrics.finalize()
            return NewsResponse(
                answer=clarification_msg,
                intent=legacy_intent, companies=[], metrics=[],
                financial_data={}, documents=[], news=[], sources=[],
                warnings=[]
            )

        if det_ticker and det_confidence >= 0.7:
            if not eq.company_identifiers or det_ticker not in eq.company_identifiers:
                if len(eq.company_identifiers) <= 1:
                    eq.company_identifiers = [det_ticker]

        # 7. Execution routing with timing and missing data checks (Problem 8)
        t_start = time.perf_counter()
        ctx = self._retrieve_with_plan(question_to_search, eq, plan, metrics, required_dims)

        # 8. Rerank and filter Chroma chunks
        tickers = eq.company_identifiers or [c.ticker for c in ctx.companies]
        if ctx.document_chunks:
            ctx.document_chunks = self._search_reranker.rerank_documents(ctx.document_chunks, tickers)
            ctx.has_document_data = bool(ctx.document_chunks)
        if ctx.news_chunks:
            ctx.news_chunks = self._search_reranker.rerank_news(ctx.news_chunks, tickers)
            ctx.has_news_data = bool(ctx.news_chunks)

        if not ctx.has_sql_data and not ctx.has_document_data and not ctx.has_news_data:
            suggestions = self._suggest_similar_companies(question_to_search)
            suggestion_str = ", ".join(suggestions)
            logger.warning("ChatService: No contexts retrieved.")
            metrics.finalize()
            return NewsResponse(
                answer=(
                    f"This information is currently unavailable."
                ),
                intent=eq.intent, companies=[], metrics=list(eq.metrics),
                financial_data={}, documents=[], news=[], sources=[],
                warnings=suggestions,
            )

        eq = self._ensure_metrics(eq, ctx.sql_context)
        ctx.sql_context.requested_metrics = list(eq.metrics)

        # 9. Prompt Construction with Financial Reasoning updates (Problem 5)
        rc = self._reasoning.analyze(question_to_search, ctx)
        prompt = self._prompt.build(question=question_to_search, hybrid_context=ctx, reasoning_context=rc)
        metrics.record_prompt(prompt)

        # 10. LLM Answer generation
        t_llm = time.perf_counter()
        try:
            answer = self._ai.generate_hybrid_answer(prompt=prompt)
        except Exception as exc:
            logger.error("ChatService: LLM generation failed: %s", exc)
            answer = "I apologize, but I encountered an error while processing your request. Please try again shortly."
        metrics.record_llm((time.perf_counter() - t_llm) * 1000.0)

        # 11. Output Guardrails
        answer = self._output_guardrail.evaluate(answer)

        # 12. Programmatic Confidence Calculation & Injection
        confidence = ConfidenceScorer.compute(
            sql_found=ctx.has_sql_data,
            doc_count=len(ctx.document_chunks),
            news_count=len(ctx.news_chunks)
        )
        metrics.record_confidence(confidence)
        answer = ConfidenceScorer.inject_confidence(answer, confidence)

        # 13. Standardized Citation Formatting
        sources = CitationFormatter.get_sources_list(ctx.has_sql_data, ctx.document_chunks, ctx.news_chunks)

        reasoning_disclaimer = "This information is for educational purposes and should not be considered investment advice."
        if rc.intent != "unknown":
            if reasoning_disclaimer not in answer:
                answer = f"{answer}\n\n{reasoning_disclaimer}"
        elif DISCLAIMER not in answer:
            answer = f"{answer}\n\n{DISCLAIMER}"

        # 14. Update conversation memory
        self._session_memory.add_message(session_id or "default_session", "user", question)
        self._session_memory.add_message(session_id or "default_session", "assistant", answer)

        metrics.finalize()

        return NewsResponse(
            answer=answer,
            intent=eq.intent,
            companies=[c.ticker for c in ctx.companies],
            metrics=list(eq.metrics),
            financial_data=self._structured_data(ctx.companies),
            documents=ctx.document_chunks,
            news=ctx.news_chunks,
            sources=sources,
            warnings=ctx.sql_context.unavailable_identifiers,
        )

    # ── Legacy Hybrid (No news refresh) ───────────────────────────────────────

    def answer_hybrid(self, question: str, session_id: str | None = "default_session") -> HybridChatResponse:
        logger.info("ChatService.answer_hybrid: question=%r session=%s", question, session_id)
        metrics = MetricsLogger(question)

        # 1. Guardrail
        is_safe, reject_msg = self._input_guardrail.evaluate(question)
        if not is_safe:
            metrics.log_intent("unsafe")
            metrics.finalize()
            return HybridChatResponse(
                answer=reject_msg,
                intent=IntentType.UNKNOWN, companies=[], metrics=[],
                structured_data={}, retrieved_documents=[], sources=[],
                warnings=["Query blocked by safety guardrails"]
            )

        # 2. Classify
        class_res = self._query_classifier.classify(question)

        # 3. Follow-up handling
        if class_res.intent == ClassifierIntent.FOLLOW_UP:
            resolved_question = self._resolve_follow_up(question, session_id or "default_session")
            class_res = self._query_classifier.classify(resolved_question)
            question_to_search = resolved_question
        else:
            question_to_search = question

        metrics.log_intent(class_res.intent.value)
        legacy_intent = LEGACY_INTENT_MAP.get(class_res.intent, IntentType.UNKNOWN)

        # Determine required dimensions
        required_dims = self._detector.determine_required_data(question_to_search, class_res.intent.value)

        # 4. Plan
        plan = self._retrieval_planner.create_plan(class_res.intent)
        plan.query_news = False
        metrics.log_plan(plan.explanation)

        # 5. Short-circuit execution
        if plan.short_circuit:
            logger.info(
                "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = YES | Reason: %s",
                class_res.intent.value, plan.explanation, "Greeting or unsupported command"
            )
            self._session_memory.add_message(session_id or "default_session", "user", question)
            self._session_memory.add_message(session_id or "default_session", "assistant", plan.short_circuit_response or "")
            metrics.record_confidence("High")
            metrics.finalize()
            return HybridChatResponse(
                answer=plan.short_circuit_response or "",
                intent=legacy_intent, companies=[], metrics=[],
                structured_data={}, retrieved_documents=[], sources=[],
                warnings=[]
            )

        logger.info(
            "[ROUTING] Detected Intent: %s | Retrieval Plan: %s | Short-circuit = NO | Reason: Domain stock query",
            class_res.intent.value, plan.explanation
        )

        catalog = self._db.get_company_catalog()
        eq = self._ai.extract_query(question=question_to_search, company_catalog=catalog)
        eq.intent = legacy_intent

        # Run Company Detector for overrides & low-confidence clarification checks (Problem 5 & 8)
        from app.services.company_detector import CompanyDetector
        detector = CompanyDetector(self._ai)
        det_ticker, det_name, det_confidence = detector.detect(question_to_search)

        is_stock_intent = class_res.intent.value in {
            "financial_metric", "company_overview", "company_comparison", 
            "annual_report", "earnings_call", "filings", "latest_news", "hybrid_analysis"
        }
        if is_stock_intent and det_confidence < 0.7 and not eq.company_identifiers:
            clarification_msg = "I couldn't confidently identify which company you are asking about. Could you please specify the company name or ticker?"
            self._session_memory.add_message(session_id or "default_session", "user", question)
            self._session_memory.add_message(session_id or "default_session", "assistant", clarification_msg)
            metrics.finalize()
            return HybridResponse(
                answer=clarification_msg,
                intent=legacy_intent, companies=[], metrics=[],
                financial_data={}, documents=[], sources=[],
                warnings=[]
            )

        if det_ticker and det_confidence >= 0.7:
            if not eq.company_identifiers or det_ticker not in eq.company_identifiers:
                if len(eq.company_identifiers) <= 1:
                    eq.company_identifiers = [det_ticker]

        # 6. Retrieve
        ctx = self._retrieve_with_plan(question_to_search, eq, plan, metrics, required_dims)

        # 7. Rerank
        tickers = eq.company_identifiers or [c.ticker for c in ctx.companies]
        if ctx.document_chunks:
            ctx.document_chunks = self._search_reranker.rerank_documents(ctx.document_chunks, tickers)
            ctx.has_document_data = bool(ctx.document_chunks)

        if not ctx.has_sql_data and not ctx.has_document_data:
            suggestions = self._suggest_similar_companies(question_to_search)
            suggestion_str = ", ".join(suggestions)
            metrics.finalize()
            return HybridChatResponse(
                answer=(
                    f"This information is currently unavailable."
                ),
                intent=eq.intent, companies=[], metrics=list(eq.metrics),
                structured_data={}, retrieved_documents=[], sources=[],
                warnings=suggestions,
            )

        eq = self._ensure_metrics(eq, ctx.sql_context)
        ctx.sql_context.requested_metrics = list(eq.metrics)
        
        # Financial Reasoning Layer (Problem 5)
        rc = self._reasoning.analyze(question_to_search, ctx)
        prompt = self._prompt.build(question=question_to_search, hybrid_context=ctx, reasoning_context=rc)
        metrics.record_prompt(prompt)

        t_llm = time.perf_counter()
        try:
            answer = self._ai.generate_hybrid_answer(prompt=prompt)
        except Exception as exc:
            logger.error("ChatService: LLM generation failed: %s", exc)
            answer = "I apologize, but I encountered an error while processing your request."
        metrics.record_llm((time.perf_counter() - t_llm) * 1000.0)

        # Guardrail & Scorer
        answer = self._output_guardrail.evaluate(answer)
        confidence = ConfidenceScorer.compute(
            sql_found=ctx.has_sql_data,
            doc_count=len(ctx.document_chunks),
            news_count=0
        )
        metrics.record_confidence(confidence)
        answer = ConfidenceScorer.inject_confidence(answer, confidence)

        sources = CitationFormatter.get_sources_list(ctx.has_sql_data, ctx.document_chunks, [])

        reasoning_disclaimer = "This information is for educational purposes and should not be considered investment advice."
        if rc.intent != "unknown":
            if reasoning_disclaimer not in answer:
                answer = f"{answer}\n\n{reasoning_disclaimer}"
        elif DISCLAIMER not in answer:
            answer = f"{answer}\n\n{DISCLAIMER}"

        self._session_memory.add_message(session_id or "default_session", "user", question)
        self._session_memory.add_message(session_id or "default_session", "assistant", answer)

        metrics.finalize()

        return HybridChatResponse(
            answer=answer, intent=eq.intent,
            companies=[c.ticker for c in ctx.companies],
            metrics=list(eq.metrics),
            structured_data=self._structured_data(ctx.companies),
            retrieved_documents=ctx.document_chunks,
            sources=sources,
            warnings=ctx.sql_context.unavailable_identifiers,
        )

    # ── Legacy ─────────────────────────────────────────────────────────────────

    def answer_question(self, question: str) -> ChatResponse:
        """Fallback compatibility route."""
        return self.answer_news(question, "legacy_default")

    # ── Helper: execution router implementing retrieval planner ──────────────────

    def _retrieve_with_plan(
        self,
        question: str,
        extracted_query: ExtractedQuery,
        plan: RetrievalPlan,
        metrics: MetricsLogger,
        required_dims: list[DataDimension]
    ) -> HybridContext:
        """Routes execution to query only checked sources, timing each stage."""
        
        # 1. Resolve dynamic data seeding / retry checks first (Problem 8)
        resolved_ticker = None
        if self._hybrid._hybrid_retriever:
            try:
                resolved_ticker, canonical_name = self._hybrid._hybrid_retriever.ensure_company_data(
                    question,
                    required_dimensions=required_dims
                )
                if resolved_ticker:
                    resolved_ticker = resolved_ticker.upper()
                    if resolved_ticker not in extracted_query.company_identifiers:
                        extracted_query.company_identifiers.append(resolved_ticker)
            except Exception as exc:
                logger.warning("ChatService: Dynamic fetch failed: %s", exc)

        # 2. SQLite execution
        if plan.query_sqlite:
            t_start = time.perf_counter()
            sql_context = self._db.build_context(extracted_query)
            has_sql = bool(sql_context.companies)
            metrics.record_sqlite((time.perf_counter() - t_start) * 1000.0)
        else:
            logger.info("ChatService: Bypassing SQLite retrieval based on plan.")
            sql_context = RetrievalContext(companies=[], requested_metrics=[], unavailable_identifiers=[], analysis_notes=[])
            has_sql = False
            
        # 3. Document execution
        if plan.query_documents:
            t_start = time.perf_counter()
            doc_chunks = self._hybrid._doc_retrieval.retrieve(question)
            
            tickers = extracted_query.company_identifiers or [c.ticker for c in sql_context.companies]
            if tickers and doc_chunks:
                filtered = [c for c in doc_chunks if any(t.upper() in c.chunk_id.upper() or t.upper() in c.document.upper() for t in tickers)]
                if filtered:
                    doc_chunks = filtered
            metrics.record_vector((time.perf_counter() - t_start) * 1000.0)
        else:
            logger.info("ChatService: Bypassing Document vector retrieval based on plan.")
            doc_chunks = []

        # 4. News execution
        tickers = extracted_query.company_identifiers or [c.ticker for c in sql_context.companies]
        if plan.query_news and tickers:
            t_start = time.perf_counter()
            if self._hybrid._news_service:
                try:
                    self._hybrid._news_service.ensure_fresh_news(tickers)
                except Exception as exc:
                    logger.warning("ChatService: News fetch failed: %s", exc)
            
            news_chunks = self._hybrid._news_retrieval.retrieve(question, tickers)
            metrics.record_news((time.perf_counter() - t_start) * 1000.0)
        else:
            logger.info("ChatService: Bypassing News feed retrieval based on plan.")
            news_chunks = []

        return HybridContext(
            sql_context=sql_context,
            companies=sql_context.companies,
            document_chunks=doc_chunks,
            news_chunks=news_chunks,
            has_sql_data=has_sql,
            has_document_data=bool(doc_chunks),
            has_news_data=bool(news_chunks)
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _suggest_similar_companies(self, query: str) -> list[str]:
        import difflib
        catalog = self._db.get_company_catalog()
        words = [w.strip(",.?!()").upper() for w in query.split() if len(w) > 2]
        suggestions = []
        for word in words:
            tickers = [c["ticker"] for c in catalog]
            names = [c["company_name"] for c in catalog]
            
            ticker_matches = difflib.get_close_matches(word, tickers, n=2, cutoff=0.4)
            name_matches = difflib.get_close_matches(word, names, n=2, cutoff=0.4)
            
            suggestions.extend(ticker_matches)
            for m in name_matches:
                for c in catalog:
                    if c["company_name"] == m:
                        suggestions.append(c["ticker"])
                        
        suggestions = list(set(suggestions))
        if not suggestions:
            suggestions = [c["ticker"] for c in catalog[:3]]
        return suggestions

    @staticmethod
    def _ensure_metrics(eq: ExtractedQuery, ctx: RetrievalContext) -> ExtractedQuery:
        if eq.metrics:
            return eq
        if eq.intent in {IntentType.COMPANY_OVERVIEW, IntentType.COMPARE_COMPANIES}:
            eq.metrics = [MetricName.REVENUE, MetricName.PROFIT, MetricName.EPS, MetricName.PE_RATIO]
        if eq.intent == IntentType.RANKING and ctx.requested_metrics:
            eq.metrics = ctx.requested_metrics
        return eq

    @staticmethod
    def _structured_data(companies) -> dict[str, Any]:
        return {
            c.ticker: {
                "company_name": c.company_name,
                "revenue": c.revenue,
                "profit": c.profit,
                "eps": c.eps,
                "pe_ratio": c.pe_ratio,
            }
            for c in companies
        }

    @staticmethod
    def _doc_sources(ctx: HybridContext) -> list[str]:
        sources: list[str] = []
        if ctx.has_sql_data:
            sources.append("SQLite")
        for chunk in ctx.document_chunks:
            label = f"{chunk.document} (chunk {chunk.chunk_id.split('::')[-1]})"
            if label not in sources:
                sources.append(label)
        return sources

    @staticmethod
    def _news_sources(ctx: HybridContext) -> list[str]:
        sources = ChatService._doc_sources(ctx)
        seen: set[str] = set()
        for chunk in ctx.news_chunks:
            if chunk.article_id not in seen:
                label = f"{chunk.source} — {chunk.title[:60]}"
                if label not in sources:
                    sources.append(label)
                seen.add(chunk.article_id)
        return sources
