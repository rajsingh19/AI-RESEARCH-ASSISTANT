"""
search_reranker.py — Retrieval reranker.
Applies distance filters, recency boosting for news, and ticker metadata matching.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
import re

from app.models.chat import DocumentChunk, NewsChunk

logger = logging.getLogger(__name__)


class SearchReranker:
    """Filters, reranks, and scores retrieved vector chunks for optimal query matching."""

    def __init__(
        self,
        distance_threshold: float = 1.2,
        news_recency_penalty_per_day: float = 0.05
    ) -> None:
        self.distance_threshold = distance_threshold
        self.news_recency_penalty_per_day = news_recency_penalty_per_day

    def rerank_documents(self, chunks: list[DocumentChunk], tickers: list[str]) -> list[DocumentChunk]:
        """
        Rerank and filter annual report/filing chunks.
        
        Rules:
        1. Filter out chunks with relevance_score (distance) > distance_threshold.
        2. Boost chunks that contain the company ticker explicitly in the text content (+0.1 bonus).
        """
        logger.info("SearchReranker: Reranking %d document chunks with tickers=%s...", len(chunks), tickers)
        
        scored_chunks = []
        for chunk in chunks:
            # Lower score is more relevant (Chroma distance metric)
            score = chunk.relevance_score if chunk.relevance_score is not None else 1.0
            
            # Discard poor matches
            if score > self.distance_threshold:
                logger.debug("SearchReranker: Discarding document chunk %s (distance %s > threshold %s)",
                             chunk.chunk_id, score, self.distance_threshold)
                continue
                
            # Apply metadata/ticker containment boost
            if tickers:
                content_lower = chunk.content.lower()
                for ticker in tickers:
                    ticker_pattern = r"\b" + re.escape(ticker.lower()) + r"\b"
                    if re.search(ticker_pattern, content_lower):
                        # Give a 0.1 similarity bonus (subtract from distance score)
                        score -= 0.1
                        logger.debug("SearchReranker: Ticker match boost applied to doc chunk: %s", chunk.chunk_id)
                        break

            # Create a temp copy of the chunk with updated score
            chunk_copy = DocumentChunk(
                chunk_id=chunk.chunk_id,
                document=chunk.document,
                content=chunk.content,
                relevance_score=round(score, 4)
            )
            scored_chunks.append((score, chunk_copy))

        # Sort by score ascending (lowest distance first)
        scored_chunks.sort(key=lambda x: x[0])
        result = [item[1] for item in scored_chunks]
        logger.info("SearchReranker: Document rerank complete. Retained %d of %d chunks.", len(result), len(chunks))
        return result

    def rerank_news(self, chunks: list[NewsChunk], tickers: list[str]) -> list[NewsChunk]:
        """
        Rerank news chunks.
        
        Rules:
        1. Filter out chunks with distance > threshold.
        2. Apply recency decay: older news chunks get a penalty added to their distance.
        """
        logger.info("SearchReranker: Reranking %d news chunks...", len(chunks))
        now = datetime.now(tz=timezone.utc)
        
        scored_chunks = []
        for chunk in chunks:
            score = chunk.relevance_score if chunk.relevance_score is not None else 1.0
            
            if score > self.distance_threshold:
                continue

            # Calculate age in days
            try:
                published_at = datetime.fromisoformat(chunk.published_at.replace("Z", "+00:00"))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                age_days = (now - published_at).total_seconds() / 86400.0
            except Exception:
                age_days = 7.0 # Default penalty if unparseable

            # Apply recency penalty (older news gets higher distance)
            age_penalty = age_days * self.news_recency_penalty_per_day
            score += age_penalty
            logger.debug("SearchReranker: News age penalty: %s days -> +%s score for %s", 
                         round(age_days, 2), round(age_penalty, 3), chunk.chunk_id)

            # Metadata matches (ticker verification boost)
            if tickers and chunk.company.upper() in [t.upper() for t in tickers]:
                score -= 0.1 # Ticker relevance bonus

            chunk_copy = NewsChunk(
                chunk_id=chunk.chunk_id,
                article_id=chunk.article_id,
                title=chunk.title,
                source=chunk.source,
                author=chunk.author,
                published_at=chunk.published_at,
                url=chunk.url,
                company=chunk.company,
                content=chunk.content,
                relevance_score=round(score, 4)
            )
            scored_chunks.append((score, chunk_copy))

        scored_chunks.sort(key=lambda x: x[0])
        result = [item[1] for item in scored_chunks]
        logger.info("SearchReranker: News rerank complete. Retained %d of %d chunks.", len(result), len(chunks))
        return result
