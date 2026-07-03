"""
news_service.py — Cache-first orchestrator.

Flow per ticker:
  1. Check NewsCache → is_hit?
  2. HIT  → log "Cache hit" → skip API call
  3. MISS → log "Cache miss" → fetch from provider → ingest → retrieve
"""
from __future__ import annotations

import logging

from app.config import Settings
from app.models.chat import NewsChunk
from app.services.news.news_cache import NewsCache, NewsFreshness
from app.services.news.news_ingestion import NewsIngestionService
from app.services.news.providers.base_provider import BaseNewsProvider
from app.utils.exceptions import NewsServiceError

logger = logging.getLogger(__name__)


class NewsService:
    """
    Single entry point for all news operations.
    Implements the intelligent cache-first pipeline.
    """

    def __init__(
        self,
        settings: Settings,
        provider: BaseNewsProvider,
        cache: NewsCache,
        ingestion: NewsIngestionService,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._cache = cache
        self._ingestion = ingestion

    def ensure_fresh_news(self, tickers: list[str]) -> dict[str, str]:
        """
        For each ticker:
          - Cache HIT  → skip API, log "Cache hit (freshness=HIGH/MEDIUM)"
          - Cache MISS → fetch → ingest → log "Stored N chunks"

        Returns {ticker: status_message} for logging.
        """
        statuses: dict[str, str] = {}
        for ticker in tickers:
            logger.info("Checking cache for ticker=%s...", ticker)
            status = self._cache.check(ticker)

            if status.is_hit:
                msg = f"Cache hit (freshness={status.freshness.value}, chunks={status.chunk_count})"
                logger.info("Cache hit for ticker=%s freshness=%s", ticker, status.freshness.value)
                statuses[ticker] = msg
                continue

            logger.info("Cache miss for ticker=%s (freshness=%s). Fetching latest news...",
                        ticker, status.freshness.value)
            try:
                articles = self._provider.fetch_articles(
                    company_ticker=ticker,
                    max_articles=self._settings.news_top_articles,
                    max_age_days=self._settings.news_max_age_days,
                )
                logger.info("Fetched %d articles for %s. Embedding...", len(articles), ticker)
                result = self._ingestion.ingest(articles, company=ticker)
                msg = f"Stored {result.chunks_added} chunks ({result.duplicates_skipped} duplicates skipped)"
                logger.info("Stored %d chunks for ticker=%s.", result.chunks_added, ticker)
                statuses[ticker] = msg
            except NewsServiceError as exc:
                logger.warning("News fetch failed for %s: %s", ticker, exc)
                statuses[ticker] = f"Fetch failed: {exc}"
            except Exception as exc:
                logger.warning("Unexpected news error for %s: %s", ticker, exc)
                statuses[ticker] = f"Error: {exc}"

        return statuses


class NewsServiceFactory:
    """
    Instantiates the correct BaseNewsProvider from settings.
    Add new providers here — zero changes to business logic.
    """

    @staticmethod
    def create_provider(settings: Settings) -> BaseNewsProvider:
        provider_name = settings.news_provider.lower()

        if provider_name == "newsapi":
            if not settings.has_news_api_key:
                raise NewsServiceError("NEWS_API_KEY missing. Add to .env.")
            from app.services.news.providers.newsapi_provider import NewsAPIProvider
            return NewsAPIProvider(api_key=settings.news_api_key)  # type: ignore[arg-type]

        if provider_name == "finnhub":
            if not settings.news_api_key:
                raise NewsServiceError("NEWS_API_KEY missing for Finnhub.")
            from app.services.news.providers.finnhub_provider import FinnhubNewsProvider
            return FinnhubNewsProvider(api_key=settings.news_api_key)  # type: ignore[arg-type]

        raise NewsServiceError(f"Unknown NEWS_PROVIDER={provider_name!r}. Supported: newsapi, finnhub.")

    @staticmethod
    def create_news_service(settings: Settings) -> NewsService | None:
        """Returns a fully wired NewsService, or None if no API key configured."""
        if not settings.has_news_api_key:
            return None
        try:
            provider = NewsServiceFactory.create_provider(settings)
            cache = NewsCache(settings)
            ingestion = NewsIngestionService(settings)
            return NewsService(settings=settings, provider=provider, cache=cache, ingestion=ingestion)
        except Exception as exc:
            logger.warning("NewsServiceFactory: could not create NewsService: %s", exc)
            return None
