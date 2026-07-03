"""
company_detector.py — Detects company names and tickers from user queries.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel
from google.genai import types

from app.services.company_registry import CompanyRegistry
from app.services.ai_service import GeminiAIService

logger = logging.getLogger(__name__)


class CompanyDetectionResult(BaseModel):
    company_name: str | None = None
    ticker: str | None = None


class CompanyDetector:
    def __init__(self, ai_service: GeminiAIService) -> None:
        self._ai = ai_service

    def detect(self, question: str) -> tuple[str | None, str | None]:
        """
        Detect company from a question.
        Returns:
            tuple (ticker, company_name) or (None, None) if none detected.
        """
        logger.info("CompanyDetector: detecting company in query=%r", question)
        
        # 1. local registry lookup (fast, case-insensitive)
        words = question.replace("?", " ").replace("!", " ").replace(".", " ").split()
        
        # Check single words
        for word in words:
            resolved = CompanyRegistry.lookup(word)
            if resolved:
                logger.info("CompanyDetector: resolved via single-word registry lookup → %s", resolved["ticker"])
                return resolved["ticker"], resolved["name"]
                
        # Check two-word phrases
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i+1]}"
            resolved = CompanyRegistry.lookup(phrase)
            if resolved:
                logger.info("CompanyDetector: resolved via two-word phrase registry lookup → %s", resolved["ticker"])
                return resolved["ticker"], resolved["name"]

        # 2. LLM-based detection (fallback/generalized search)
        logger.info("CompanyDetector: local lookup missed. Calling Gemini for company detection...")
        prompt = (
            f"Analyze the following stock market question and identify the company name "
            f"and stock ticker symbol referenced in it.\n\n"
            f"Question: \"{question}\"\n\n"
            f"Requirements:\n"
            f"1. Extract the canonical company name and a stock ticker symbol.\n"
            f"2. If it is an Indian company, use its NSE ticker (e.g. TATAMOTORS, SBIN, BHARTIARTL).\n"
            f"3. If no company or stock is mentioned, return null for both fields.\n"
            f"4. Do NOT format as markdown or anything other than JSON matching the response schema."
        )

        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You extract company names and stock ticker symbols from text. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=CompanyDetectionResult,
                ),
            )
            if response.parsed and isinstance(response.parsed, CompanyDetectionResult):
                res = response.parsed
                if res.ticker:
                    ticker = res.ticker.strip().upper()
                    name = res.company_name or ticker
                    logger.info("CompanyDetector: Gemini detected ticker=%s company=%s", ticker, name)
                    return ticker, name
            
            logger.warning("CompanyDetector: Gemini failed to return parsed detection result.")
        except Exception as exc:
            logger.exception("CompanyDetector: Gemini call failed during detection: %s", exc)

        return None, None
