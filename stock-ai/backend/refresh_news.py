#!/usr/bin/env python3
"""
refresh_news.py — Run this to fetch and store latest news for all companies.

Usage:
    cd backend
    source venv/bin/activate
    python refresh_news.py

    # Specific tickers only:
    python refresh_news.py --tickers TCS INFY

    # Dry run (fetch only, no ChromaDB write):
    python refresh_news.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure app package is importable when run from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings
from app.services.news_ingestion_service import NewsIngestionService
from app.services.news_service import COMPANY_SEARCH_TERMS
from app.services.news_service import NewsServiceFactory
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh financial news in ChromaDB.")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(COMPANY_SEARCH_TERMS.keys()),
        help="Ticker symbols to refresh. Defaults to all known companies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch articles but do not write to ChromaDB.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)

    if not settings.has_news_api_key:
        logger.error(
            "NEWS_API_KEY is not set in .env. "
            "Add your NewsAPI key to use this script."
        )
        sys.exit(1)

    provider = NewsServiceFactory.create(settings)

    if args.dry_run:
        logger.info("DRY RUN — articles will be fetched but NOT stored.")
        for ticker in args.tickers:
            articles = provider.fetch_articles(
                company_ticker=ticker,
                max_articles=settings.news_top_articles,
                max_age_days=settings.news_max_age_days,
            )
            logger.info("DRY RUN: %s — %d articles fetched.", ticker, len(articles))
            for article in articles:
                logger.info("  [%s] %s — %s", article.published_at.date(), article.source, article.title)
        return

    ingestion_service = NewsIngestionService(settings=settings, news_provider=provider)

    logger.info("Starting news refresh for tickers: %s", args.tickers)
    total_added = 0

    for ticker in args.tickers:
        try:
            result = ingestion_service.ingest_for_company(ticker)
            logger.info(
                "%-12s fetched=%-3d added=%-3d skipped=%d",
                ticker,
                result.articles_fetched,
                result.chunks_added,
                result.duplicates_skipped,
            )
            total_added += result.chunks_added
        except Exception as exc:
            logger.error("Failed to refresh news for %s: %s", ticker, exc)

    total_in_db = ingestion_service.collection_count()
    logger.info(
        "News refresh complete. chunks_added=%d total_in_collection=%d",
        total_added,
        total_in_db,
    )


if __name__ == "__main__":
    main()
