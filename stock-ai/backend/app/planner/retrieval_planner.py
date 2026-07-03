"""
retrieval_planner.py — Plan which data sources (SQLite, Document Collection, News Collection) to retrieve from.
Optimizes pipeline performance by disabling unused data fetchers and short-circuiting basic chat.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field

from app.services.query_classifier import ClassifierIntent

logger = logging.getLogger(__name__)


class RetrievalPlan(BaseModel):
    query_sqlite: bool = Field(description="True if SQLite database containing financial metrics should be queried")
    query_documents: bool = Field(description="True if ChromaDB documents (annual reports/filings) should be searched")
    query_news: bool = Field(description="True if ChromaDB news articles should be searched")
    short_circuit: bool = Field(default=False, description="True if query should return immediately with a pre-defined message")
    short_circuit_response: str | None = Field(default=None, description="Pre-defined message to return if short_circuit is True")
    explanation: str = Field(description="Brief reasoning for enabling/disabling respective retrievers")


class RetrievalPlanner:
    """Decides which retrieval subsystems to trigger based on user intent classification."""

    def __init__(self) -> None:
        pass

    def create_plan(self, intent: ClassifierIntent) -> RetrievalPlan:
        """
        Constructs a retrieval plan based on the classified intent.
        
        Args:
            intent: The classified ClassifierIntent enum.
            
        Returns:
            RetrievalPlan specifying the active components and short-circuit outcomes.
        """
        logger.info("RetrievalPlanner: Generating retrieval plan for intent: %s", intent)

        # Predefined Response Text
        assistant_capabilities = (
            "Hello! I'm your AI Stock Research Assistant. I can help you analyze companies, "
            "compare financial metrics, summarize annual reports, explain earnings calls, "
            "and answer questions using financial data and recent news."
        )
        thanks_response = "You're welcome! Let me know if you need any other financial analysis or stock updates."
        goodbye_response = "Goodbye! Have a great day, and feel free to reach out next time you need stock research."
        unsupported_response = "I'm designed to answer questions related to companies, financial metrics, annual reports, filings, and stock market news."

        # 1. Short-circuit routes (No retrievals, direct answers)
        if intent == ClassifierIntent.GREETING:
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=False,
                short_circuit=True,
                short_circuit_response=assistant_capabilities,
                explanation="Short-circuit: greeting."
            )

        elif intent in (ClassifierIntent.CAPABILITY, ClassifierIntent.HELP):
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=False,
                short_circuit=True,
                short_circuit_response=assistant_capabilities,
                explanation="Short-circuit: capabilities/help request."
            )

        elif intent == ClassifierIntent.THANKS:
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=False,
                short_circuit=True,
                short_circuit_response=thanks_response,
                explanation="Short-circuit: gratitude."
            )

        elif intent == ClassifierIntent.GOODBYE:
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=False,
                short_circuit=True,
                short_circuit_response=goodbye_response,
                explanation="Short-circuit: goodbye."
            )

        elif intent == ClassifierIntent.UNSUPPORTED:
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=False,
                short_circuit=True,
                short_circuit_response=unsupported_response,
                explanation="Short-circuit: unsupported domain topic."
            )

        # 2. Retrieval routes
        elif intent == ClassifierIntent.FINANCIAL_METRIC:
            return RetrievalPlan(
                query_sqlite=True,
                query_documents=False,
                query_news=False,
                explanation="Metrics request: querying SQLite only."
            )

        elif intent == ClassifierIntent.LATEST_NEWS:
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=False,
                query_news=True,
                explanation="News request: querying Chroma news collection only."
            )

        elif intent in (ClassifierIntent.ANNUAL_REPORT, ClassifierIntent.EARNINGS_CALL, ClassifierIntent.FILINGS):
            return RetrievalPlan(
                query_sqlite=False,
                query_documents=True,
                query_news=False,
                explanation="Filings request: querying Chroma document collection only."
            )

        # For comparison, general financial questions, company overview, follow_ups and hybrid: run hybrid (full search)
        else:
            return RetrievalPlan(
                query_sqlite=True,
                query_documents=True,
                query_news=True,
                explanation="Hybrid request: running all retrieval channels (SQLite + Documents + News)."
            )
