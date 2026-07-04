"""
company_detector.py — Detects company names and tickers from user queries with confidence metrics.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel, Field
from google.genai import types

from app.services.company_registry import CompanyRegistry
from app.services.ai_service import GeminiAIService

logger = logging.getLogger(__name__)


class CompanyDetectionResult(BaseModel):
    company_name: str | None = Field(default=None, description="The identified company name referenced in the question.")
    ticker: str | None = Field(default=None, description="Stock ticker symbol if known or extractable.")
    confidence: float = Field(default=1.0, description="Confidence level between 0.0 (no company mentioned or ambiguous) and 1.0 (highly confident identification).")
    reasoning: str = Field(default="", description="Brief rationale for the detection result.")


class CompanyDetector:
    def __init__(self, ai_service: GeminiAIService) -> None:
        self._ai = ai_service

    def detect(self, question: str) -> tuple[str | None, str | None, float]:
        """
        Detect company from a question.
        
        Returns:
            tuple: (ticker, company_name, confidence)
        """
        logger.info("CompanyDetector: detecting company in query=%r", question)
        
        # 1. Local registry lookup (fast match)
        # Clean special chars to isolate words
        cleaned_words = re.sub(r"[^\w\s]", " ", question).split()
        
        # Check single words and two-word phrases first
        for word in cleaned_words:
            if len(word) > 2:
                resolved = CompanyRegistry.lookup(word, enable_live=False)
                if resolved:
                    logger.info("CompanyDetector: resolved via single-word registry lookup → %s", resolved["ticker"])
                    return resolved["ticker"], resolved["name"], 1.0
                    
        for i in range(len(cleaned_words) - 1):
            phrase = f"{cleaned_words[i]} {cleaned_words[i+1]}"
            resolved = CompanyRegistry.lookup(phrase, enable_live=False)
            if resolved:
                logger.info("CompanyDetector: resolved via two-word phrase registry lookup → %s", resolved["ticker"])
                return resolved["ticker"], resolved["name"], 1.0

        # 2. LLM-based detection fallback (extract company name and parse)
        logger.info("CompanyDetector: local lookup missed. Calling Gemini for company detection...")
        prompt = (
            f"Analyze this query and identify the company name referenced in it.\n\n"
            f"Question: \"{question}\"\n\n"
            f"Requirements:\n"
            f"1. Extract the company name (e.g. 'Haldiram', 'Nestle India').\n"
            f"2. Extract its stock ticker symbol if known.\n"
            f"3. Assign a confidence score from 0.0 to 1.0:\n"
            f"   - 1.0: Company name is explicitly mentioned (e.g. 'Haldiram', 'Infosys', 'Airtel').\n"
            f"   - 0.0: No company is mentioned, or query contains only pronouns/vague references (e.g. 'is this stock cheap?', 'how is its revenue?').\n"
            f"4. Do NOT format as markdown or anything other than JSON matching the response schema."
        )

        try:
            response = self._ai.client.models.generate_content(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You extract company names and stock symbols. Return structured JSON.",
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=CompanyDetectionResult,
                ),
            )
            if response.parsed and isinstance(response.parsed, CompanyDetectionResult):
                res = response.parsed
                confidence = res.confidence
                
                if res.company_name and confidence >= 0.7:
                    comp_name = res.company_name.strip()
                    ticker = res.ticker.strip().upper() if res.ticker else None
                    
                    # Search registry dynamically (live search enabled!)
                    resolved = CompanyRegistry.lookup(comp_name, enable_live=True)
                    if resolved:
                        logger.info("CompanyDetector: Gemini extraction matched registry → %s", resolved["ticker"])
                        return resolved["ticker"], resolved["name"], confidence
                    
                    # If not found in registry (e.g. private or unlisted like Haldiram), register dynamically
                    clean_ticker = ticker or re.sub(r"[^A-Z]", "", comp_name.upper())[:10]
                    resolved_details = {
                        "ticker": clean_ticker,
                        "name": comp_name,
                        "search_term": comp_name,
                        "yahoo_ticker": f"{clean_ticker}.NS"
                    }
                    CompanyRegistry.register_dynamic(clean_ticker, resolved_details)
                    logger.info("CompanyDetector: Dynamically resolved and registered unlisted company → %s (%s)", comp_name, clean_ticker)
                    return clean_ticker, comp_name, confidence
                
                logger.info("CompanyDetector: Gemini returned low confidence (%f) or null company.", confidence)
                return None, None, confidence
            
            logger.warning("CompanyDetector: Gemini failed to return parsed detection result.")
        except Exception as exc:
            logger.exception("CompanyDetector: Gemini call failed during detection: %s", exc)

        return None, None, 0.0
import re
