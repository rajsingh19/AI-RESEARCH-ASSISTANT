"""
news_cache.py — Freshness check against ChromaDB news collection.

Freshness policy:
  < 24 hours  → HIGH   → cache HIT  → skip NewsAPI call
  1–7 days    → MEDIUM → cache HIT  → skip NewsAPI call
  > 7 days    → LOW    → cache MISS → fetch fresh
  No data     → MISSING→ cache MISS → fetch fresh
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.config import Settings

logger = logging.getLogger(__name__)

_HIT_THRESHOLD_HOURS = 6


class NewsFreshness(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MISSING = "missing"


@dataclass
class CacheStatus:
    ticker: str
    freshness: NewsFreshness
    newest_article_at: datetime | None
    chunk_count: int
    is_hit: bool  # True = skip API call


class NewsCache:
    """
    Read-only freshness inspector over the ChromaDB news collection.
    Writing is done exclusively by NewsIngestionService.
    """

    def __init__(self, settings: Settings) -> None:
        embedding_fn = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model_name)
        client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self._collection = client.get_or_create_collection(
            name=settings.news_collection_name,
            embedding_function=embedding_fn,
        )

    def check(self, ticker: str) -> CacheStatus:
        """Check freshness for one ticker. Returns CacheStatus with is_hit flag."""
        logger.info("NewsCache: checking cache for ticker=%s", ticker)
        result = self._collection.get(where={"company": {"$eq": ticker}}, include=["metadatas"])
        metadatas = result.get("metadatas") or []

        if not metadatas:
            logger.info("NewsCache: MISS (no data) ticker=%s", ticker)
            return CacheStatus(ticker=ticker, freshness=NewsFreshness.MISSING,
                               newest_article_at=None, chunk_count=0, is_hit=False)

        newest: datetime | None = None
        for meta in metadatas:
            if not isinstance(meta, dict):
                continue
            try:
                dt = datetime.fromisoformat(meta.get("published_at", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if newest is None or dt > newest:
                    newest = dt
            except (ValueError, TypeError):
                continue

        now = datetime.now(tz=timezone.utc)
        freshness, is_hit = self._classify(newest, now)
        logger.info("NewsCache: ticker=%s freshness=%s newest=%s chunks=%d hit=%s",
                    ticker, freshness.value, newest, len(metadatas), is_hit)
        return CacheStatus(ticker=ticker, freshness=freshness,
                           newest_article_at=newest, chunk_count=len(metadatas), is_hit=is_hit)

    def check_many(self, tickers: list[str]) -> dict[str, CacheStatus]:
        return {t: self.check(t) for t in tickers}

    @staticmethod
    def _classify(newest: datetime | None, now: datetime) -> tuple[NewsFreshness, bool]:
        if newest is None:
            return NewsFreshness.MISSING, False
        age = now - newest
        if age <= timedelta(hours=_HIT_THRESHOLD_HOURS):
            return NewsFreshness.HIGH, True
        if age <= timedelta(days=7):
            return NewsFreshness.MEDIUM, True
        return NewsFreshness.LOW, False
