"""NewsAPI provider — retry, rate-limit handling, free-plan fallback."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from newsapi import NewsApiClient
from newsapi.newsapi_exception import NewsAPIException

from app.models.chat import NewsArticle
from app.services.news.providers.base_provider import BaseNewsProvider, make_article_id, parse_iso_dt
from app.utils.exceptions import NewsServiceError

logger = logging.getLogger(__name__)

COMPANY_SEARCH_TERMS: dict[str, str] = {
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys",
    "RELIANCE": "Reliance Industries",
    "WIPRO": "Wipro",
    "HCLTECH": "HCL Technologies",
    "HDFC": "HDFC Bank",
    "ICICI": "ICICI Bank",
    "BAJFINANCE": "Bajaj Finance",
    "ADANI": "Adani Group",
    "MARUTI": "Maruti Suzuki",
}

_RETRY_WAITS = [1, 2, 4]


class NewsAPIProvider(BaseNewsProvider):
    """
    NewsAPI.org provider.
    Strategy: try get_everything (paid) → fallback to top-headlines (free).
    Retries up to 3 times with exponential backoff on transient errors.
    """

    def __init__(self, api_key: str) -> None:
        self._client = NewsApiClient(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "NewsAPI"

    def fetch_articles(self, company_ticker: str, max_articles: int, max_age_days: int) -> list[NewsArticle]:
        query = COMPANY_SEARCH_TERMS.get(company_ticker, company_ticker)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
        logger.info("NewsAPIProvider: fetching ticker=%s query=%r max=%d", company_ticker, query, max_articles)

        raw = self._fetch_with_retry(query, max_articles)
        return self._parse(raw, company_ticker, cutoff, max_articles)

    def _fetch_with_retry(self, query: str, max_articles: int) -> list[dict]:
        for attempt, wait in enumerate(_RETRY_WAITS, start=1):
            try:
                resp = self._client.get_everything(
                    q=query, language="en", sort_by="publishedAt",
                    page_size=min(max_articles, 100),
                )
                return resp.get("articles", [])
            except NewsAPIException as exc:
                msg = str(exc)
                if any(k in msg for k in ("401", "426", "apiKeyInvalid", "upgrade")):
                    logger.warning("NewsAPIProvider: paid plan unavailable (%s), using top-headlines.", exc)
                    return self._headlines_with_retry(query, max_articles)
                if attempt == len(_RETRY_WAITS):
                    raise NewsServiceError(f"NewsAPI failed after retries: {exc}") from exc
                logger.warning("NewsAPIProvider: attempt %d failed, retrying in %ds.", attempt, wait)
                time.sleep(wait)
            except Exception as exc:
                raise NewsServiceError(f"Unexpected NewsAPI error: {exc}") from exc
        return []

    def _headlines_with_retry(self, query: str, max_articles: int) -> list[dict]:
        for attempt, wait in enumerate(_RETRY_WAITS, start=1):
            try:
                resp = self._client.get_top_headlines(
                    q=query, language="en", page_size=min(max_articles, 100),
                )
                return resp.get("articles", [])
            except NewsAPIException as exc:
                if attempt == len(_RETRY_WAITS):
                    raise NewsServiceError(f"NewsAPI top-headlines failed: {exc}") from exc
                time.sleep(wait)
            except Exception as exc:
                raise NewsServiceError(f"Unexpected top-headlines error: {exc}") from exc
        return []

    def _parse(self, raw: list[dict], ticker: str, cutoff: datetime, max_articles: int) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for item in raw:
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not url or not title or "[Removed]" in title:
                continue
            published_at = parse_iso_dt(item.get("publishedAt"))
            if published_at < cutoff:
                continue
            content = (item.get("content") or item.get("description") or "").strip()
            if not content:
                continue
            articles.append(NewsArticle(
                article_id=make_article_id(url),
                title=title,
                content=content,
                source=(item.get("source") or {}).get("name") or "Unknown",
                author=item.get("author") or None,
                published_at=published_at,
                url=url,
                company=ticker,
            ))
            if len(articles) >= max_articles:
                break
        logger.info("NewsAPIProvider: parsed %d articles for %s.", len(articles), ticker)
        return articles
