"""
news_refresher.py — Asynchronous background task for hourly news refresh and data purging.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.database import SessionLocal
from app.models.company import Company
from app.services.news.news_service import NewsService
from app.services.rag.chroma_client import get_chroma_client

logger = logging.getLogger(__name__)


class NewsRefresher:
    """Manages background news indexing, deduplication, and TTL retention pruning."""

    def __init__(self, settings: Settings, news_service: NewsService | None) -> None:
        self._settings = settings
        self._news_service = news_service
        self._client = get_chroma_client()
        # Chroma collection for news
        self._collection = self._client.get_or_create_collection(
            name=settings.news_collection_name
        )

    async def start_loop(self) -> None:
        """Start the infinite background worker loop running every hour."""
        if not self._news_service:
            logger.warning("NewsRefresher: NewsService not configured (missing key). Background refresher disabled.")
            return

        logger.info("NewsRefresher: Starting hourly background news refresh loop.")
        while True:
            try:
                await self.refresh_all_companies()
                self.purge_expired_news()
            except Exception as exc:
                logger.error("NewsRefresher: Background cycle encountered error: %s", exc)

            # Sleep for 1 hour (3600 seconds)
            logger.info("NewsRefresher: Sleeping for 1 hour until next refresh cycle.")
            await asyncio.sleep(3600)

    async def refresh_all_companies(self) -> None:
        """Fetch and index latest news for all companies present in the SQLite database."""
        logger.info("NewsRefresher: Starting news refresh for all companies in database...")
        db: Session = SessionLocal()
        try:
            companies = db.query(Company).all()
            tickers = [c.ticker for c in companies]
            if not tickers:
                logger.info("NewsRefresher: No companies found in database to refresh.")
                return

            logger.info("NewsRefresher: Refreshing tickers: %s", tickers)
            
            # Perform news fetch in a separate thread pool to avoid blocking the main async event loop
            loop = asyncio.get_running_loop()
            statuses = await loop.run_in_executor(
                None,
                self._news_service.ensure_fresh_news,
                tickers
            )
            
            for ticker, status in statuses.items():
                logger.info("NewsRefresher: Ticker %s refresh status: %s", ticker, status)
        finally:
            db.close()

    def purge_expired_news(self) -> int:
        """Delete news documents from ChromaDB that are older than news_retention_days."""
        retention_days = self._settings.news_retention_days
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        logger.info("NewsRefresher: Pruning news articles published before %s (retention limit: %d days)...",
                    cutoff, retention_days)

        deleted_count = 0
        try:
            # Retrieve metadata for all news articles
            result = self._collection.get(include=["metadatas"])
            metadatas = result.get("metadatas") or []
            ids = result.get("ids") or []

            expired_ids = []
            for chunk_id, meta in zip(ids, metadatas):
                if not isinstance(meta, dict):
                    continue
                published_at_str = meta.get("published_at")
                if published_at_str:
                    try:
                        # Handle timezone offset parsing
                        dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        
                        if dt < cutoff:
                            expired_ids.append(chunk_id)
                    except (ValueError, TypeError):
                        continue

            if expired_ids:
                logger.info("NewsRefresher: Deleting %d expired news chunks...", len(expired_ids))
                # Delete from ChromaDB in batches of 100 to avoid query size limits
                batch_size = 100
                for i in range(0, len(expired_ids), batch_size):
                    batch = expired_ids[i:i+batch_size]
                    self._collection.delete(ids=batch)
                deleted_count = len(expired_ids)
                logger.info("NewsRefresher: Successfully deleted %d expired news chunks.", deleted_count)
            else:
                logger.info("NewsRefresher: No expired news chunks found to prune.")
        except Exception as exc:
            logger.error("NewsRefresher: Pruning execution failed: %s", exc)

        return deleted_count
