"""
confidence_scorer.py — Programmatic confidence level calculator.
Determines confidence (High/Medium/Low) based on factual sources found in retrieval.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """Calculates factual coverage and overrides LLM self-assessments."""

    @staticmethod
    def compute(sql_found: bool, doc_count: int, news_count: int) -> str:
        """
        Compute confidence rating programmatically based on retrieval parameters.
        Returns:
            "High" | "Medium" | "Low"
        """
        score = 0
        if sql_found:
            score += 50
        
        # Doc chunks add up to 30 points (10 per chunk)
        score += min(doc_count * 10, 30)
        
        # News chunks add up to 20 points (10 per chunk)
        score += min(news_count * 10, 20)

        logger.info("ConfidenceScorer: Computed coverage score=%d (SQL=%s, docs=%d, news=%d)",
                    score, sql_found, doc_count, news_count)

        if score >= 80:
            return "High"
        elif score >= 40:
            return "Medium"
        else:
            return "Low"

    @staticmethod
    def inject_confidence(answer: str, confidence_level: str) -> str:
        """
        Inject/overwrite the ### Confidence Level section in the LLM's answer
        with the programmatic rating.
        """
        pattern = r"(### Confidence Level\s*)([^\n]*)(.*)"
        match = re.search(pattern, answer, re.DOTALL)
        
        explanation_map = {
            "High": "High (Programmatic verification: Both structured financial records and detailed filings are fully present).",
            "Medium": "Medium (Programmatic verification: Partial data retrieved. Some financial statements or reports are missing).",
            "Low": "Low (Programmatic verification: Crucial metrics or filings are unavailable in the source context)."
        }
        
        explanation = explanation_map.get(confidence_level, confidence_level)

        if match:
            # Reconstruct the answer by replacing the content after the heading
            prefix = answer[:match.start(2)]
            # We want to replace the first line of content and keep the rest of the text (like disclaimer)
            rest = match.group(3)
            # Split the rest by lines to replace only the first line of explanation
            lines = rest.split("\n", 1)
            remaining_lines = lines[1] if len(lines) > 1 else ""
            
            # Formulate the updated block
            updated_answer = f"{prefix}{explanation}\n{remaining_lines}"
            logger.info("ConfidenceScorer: Successfully injected programmatic confidence level: %s", confidence_level)
            return updated_answer
            
        # Fallback: if heading not found, append it before the disclaimer
        disclaimer_marker = "This information is based on the available"
        if disclaimer_marker in answer:
            parts = answer.split(disclaimer_marker, 1)
            updated_answer = (
                f"{parts[0].strip()}\n\n"
                f"### Confidence Level\n{explanation}\n\n"
                f"{disclaimer_marker}{parts[1]}"
            )
            return updated_answer

        return f"{answer}\n\n### Confidence Level\n{explanation}"
