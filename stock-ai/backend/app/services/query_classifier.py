"""
query_classifier.py — Analyzes and classifies the user's query intent.
Optimizes retrieval paths to reduce latency and API overhead.
"""
from __future__ import annotations

import logging
from enum import Enum
from pydantic import BaseModel, Field
from google.genai import types

from app.services.ai_service import GeminiAIService
from app.models.chat import IntentType

logger = logging.getLogger(__name__)


class ClassifierIntent(str, Enum):
    GREETING = "greeting"
    CAPABILITY = "capability"
    THANKS = "thanks"
    GOODBYE = "goodbye"
    HELP = "help"
    FINANCIAL_METRIC = "financial_metric"
    COMPANY_OVERVIEW = "company_overview"
    COMPANY_COMPARISON = "company_comparison"
    ANNUAL_REPORT = "annual_report"
    EARNINGS_CALL = "earnings_call"
    FILINGS = "filings"
    LATEST_NEWS = "latest_news"
    HYBRID_ANALYSIS = "hybrid_analysis"
    FOLLOW_UP = "follow_up"
    UNSUPPORTED = "unsupported"


class ClassificationResponse(BaseModel):
    intent: ClassifierIntent = Field(description="The primary intent category classified from the query")
    reasoning: str = Field(description="Short rationale explaining the classification choice")


# Mapping table from the new detailed ClassifierIntents to legacy models.IntentType enums
LEGACY_INTENT_MAP = {
    ClassifierIntent.GREETING: IntentType.UNKNOWN,
    ClassifierIntent.CAPABILITY: IntentType.UNKNOWN,
    ClassifierIntent.THANKS: IntentType.UNKNOWN,
    ClassifierIntent.GOODBYE: IntentType.UNKNOWN,
    ClassifierIntent.HELP: IntentType.UNKNOWN,
    ClassifierIntent.FINANCIAL_METRIC: IntentType.COMPANY_METRIC,
    ClassifierIntent.COMPANY_OVERVIEW: IntentType.COMPANY_OVERVIEW,
    ClassifierIntent.COMPANY_COMPARISON: IntentType.COMPARE_COMPANIES,
    ClassifierIntent.ANNUAL_REPORT: IntentType.UNKNOWN,
    ClassifierIntent.EARNINGS_CALL: IntentType.UNKNOWN,
    ClassifierIntent.FILINGS: IntentType.UNKNOWN,
    ClassifierIntent.LATEST_NEWS: IntentType.COMPANY_METRIC,
    ClassifierIntent.HYBRID_ANALYSIS: IntentType.UNKNOWN,
    ClassifierIntent.FOLLOW_UP: IntentType.UNKNOWN,
    ClassifierIntent.UNSUPPORTED: IntentType.UNKNOWN
}


class QueryClassifier:
    """Classifies user inquiries to route them to the most cost-efficient retrievers."""

    def __init__(self, ai_service: GeminiAIService) -> None:
        self._ai = ai_service

    def classify(self, query: str) -> ClassificationResponse:
        """
        Classify the query intent using structured LLM classification.
        
        Args:
            query: The user's question text.
            
        Returns:
            ClassificationResponse with the classified intent and reason.
        """
        logger.info("QueryClassifier: Classifying intent for query: %r", query)

        # 1. Fast local checks for basic greetings & capability terms
        normalized = query.strip().lower().rstrip("?!.")
        greetings = {"hello", "hi", "hey", "good morning", "good afternoon", "good evening"}
        goodbyes = {"bye", "goodbye", "see you", "bye bye", "talk to you later"}
        thanks = {"thanks", "thank you", "thank you so much", "thx", "appreciate it"}
        help_terms = {"help", "help me", "sos"}
        
        if normalized in greetings:
            return ClassificationResponse(intent=ClassifierIntent.GREETING, reasoning="Local keyword match: greeting")
        if normalized in goodbyes:
            return ClassificationResponse(intent=ClassifierIntent.GOODBYE, reasoning="Local keyword match: goodbye")
        if normalized in thanks:
            return ClassificationResponse(intent=ClassifierIntent.THANKS, reasoning="Local keyword match: thanks")
        if normalized in help_terms:
            return ClassificationResponse(intent=ClassifierIntent.HELP, reasoning="Local keyword match: help")

        # 2. LLM-based classification for semantic coverage
        prompt = (
            f"Analyze the user query below and classify it into exactly ONE of these intents:\n"
            f"- greeting: simple salutations, casual chat, small talk (e.g. 'Hello', 'Hi')\n"
            f"- capability: asking who you are or what you can do (e.g. 'Who are you?', 'What can you do?')\n"
            f"- thanks: expressing gratitude (e.g. 'Thank you', 'Thanks')\n"
            f"- goodbye: parting salutations (e.g. 'Bye', 'See you')\n"
            f"- help: asking for help or documentation (e.g. 'Help')\n"
            f"- financial_metric: seeking specific numbers/stats/ratios (e.g. 'Revenue of TCS', 'EPS of Infosys')\n"
            f"- company_overview: general company description/profile (e.g. 'Business summary of Airtel')\n"
            f"- company_comparison: comparing two or more companies (e.g. 'Compare TCS and Infosys')\n"
            f"- annual_report: summarizing 10-K/annual filings (e.g. 'Summarize TCS annual report')\n"
            f"- earnings_call: transcripts, conference calls (e.g. 'TCS earnings call summary')\n"
            f"- filings: filings lookup, documents index (e.g. 'Show me corporate filings')\n"
            f"- latest_news: recent news/headlines (e.g. 'Latest news on TCS')\n"
            f"- hybrid_analysis: general combination of multiple financial topics, stock recommendations, or investment evaluation questions (e.g. 'Should I buy TCS?', 'Is Infosys a good investment?')\n"
            f"- follow_up: questions containing coreferences like 'its', 'their', 'this' (e.g. 'What about its profit?', 'What are their risks?')\n"
            f"- unsupported: queries completely unrelated to stocks, companies, finance, annual reports, or filings (e.g. 'Who won IPL?', 'What is the weather today?', movies, politics)\n\n"
            f"User Query: \"{query}\"\n\n"
            f"Respond only with JSON matching the ClassificationResponse schema."
        )

        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are an expert query classifier for a financial assistant. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=ClassificationResponse,
                ),
            )

            if response.parsed and isinstance(response.parsed, ClassificationResponse):
                logger.info("QueryClassifier: Classified query intent as: %s", response.parsed.intent)
                return response.parsed

            logger.warning("QueryClassifier: Classifier returned invalid layout. Defaulting to UNSUPPORTED.")
        except Exception as exc:
            logger.error("QueryClassifier: LLM classification failed: %s. Running local fallback classifier.", exc)
            fallback_intent = self._fallback_classify(query)
            return ClassificationResponse(
                intent=fallback_intent,
                reasoning="Local fallback rule match due to LLM exception."
            )

        return ClassificationResponse(
            intent=ClassifierIntent.UNSUPPORTED,
            reasoning="Fallback default due to classification failure."
        )

    def _fallback_classify(self, query: str) -> ClassifierIntent:
        normalized = query.lower()
        
        # Check coreferences first
        follow_up_terms = {"its", "their", "they", "this company", "what about"}
        if any(term in normalized for term in follow_up_terms):
            return ClassifierIntent.FOLLOW_UP

        # Check news
        if "news" in normalized or "recent" in normalized:
            return ClassifierIntent.LATEST_NEWS

        # Check filings
        if any(term in normalized for term in {"annual report", "filings", "10-k", "annual"}):
            return ClassifierIntent.ANNUAL_REPORT

        # Check comparison
        if any(term in normalized for term in {"compare", "versus", "vs", "comparison"}):
            return ClassifierIntent.COMPANY_COMPARISON

        # Valuation, Growth, and Strength queries
        valuation_keywords = {"undervalued", "overvalued", "expensive", "cheap", "valuation", "pricing", "attractive", "fair value", "buy", "sell", "should i"}
        growth_keywords = {"growth", "growing", "expansion", "trend", "grow"}
        strength_keywords = {"strong", "weak", "health", "profitable", "profitability", "margins", "roe", "roce"}
        
        if any(kw in normalized for kw in valuation_keywords):
            return ClassifierIntent.HYBRID_ANALYSIS
        if any(kw in normalized for kw in growth_keywords):
            return ClassifierIntent.FINANCIAL_METRIC
        if any(kw in normalized for kw in strength_keywords):
            return ClassifierIntent.FINANCIAL_METRIC

        # Check if any company resolved in registry, default to company_overview
        words = normalized.replace("?", " ").replace("!", " ").replace(".", " ").split()
        from app.services.company_registry import CompanyRegistry
        for w in words:
            resolved = CompanyRegistry.lookup(w)
            if resolved:
                return ClassifierIntent.COMPANY_OVERVIEW

        return ClassifierIntent.UNSUPPORTED
