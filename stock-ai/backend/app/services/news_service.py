from __future__ import annotations

import hashlib
import logging
from abc import ABC
from abc import abstractmethod
from datetime import datetime
from datetime import timezone

from newsapi import NewsApiClient
from newsapi.newsapi_exception import NewsAPIException

from app.config import Settings
from app.models.chat import NewsArticle
from app.utils.exceptions import NewsServiceError

logger = logging.getLogger(__name__)

# Company name search terms — maps ticker to human-readable search query
COMPANY_SEARCH_TERMS: dict[str, str] = {
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys",
    "RELIANCE": "Reliance Industries",
    "WIPRO": "Wipro",
    "HCLTECH": "HCL Technologies",
}


def _make_article_id(url: str) -> str:
    """Deterministic dedup key — SHA256 of the article URL."""
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_dt(value: str | None) -> datetime:
    """Parse ISO 8601 string from NewsAPI into a timezone-aware datetime."""
    if not value:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=timezone.utc)


# ── Provider abstraction ───────────────────────────────────────────────────────

class BaseNewsProvider(ABC):
    """
    Abstract base for all news providers.

    To add Finnhub, Alpha Vantage, or Polygon.io:
    1. Create a subclass of BaseNewsProvider.
    2. Implement fetch_articles().
    3. Register it in NewsServiceFactory.
    """

    @abstractmethod
    def fetch_articles(
        self,
        company_ticker: str,
        max_articles: int,
        max_age_days: int,
    ) -> list[NewsArticle]:
        """
        Fetch recent news articles for a company.

        Args:
            company_ticker: Ticker symbol, e.g. "TCS".
            max_articles: Maximum number of articles to return.
            max_age_days: Skip articles older than this many days.

        Returns:
            List of NewsArticle objects. Empty list if none found.
        """


# ── NewsAPI implementation ─────────────────────────────────────────────────────

class NewsAPIProvider(BaseNewsProvider):
    """
    Fetches news from NewsAPI.org.

    Uses the company's full name as the search query for better results
    than using ticker symbols (which NewsAPI doesn't understand natively).
    """

    def __init__(self, api_key: str) -> None:
        self._client = NewsApiClient(api_key=api_key)

    def fetch_articles(
        self,
        company_ticker: str,
        max_articles: int,
        max_age_days: int,
    ) -> list[NewsArticle]:
        search_query = COMPANY_SEARCH_TERMS.get(company_ticker, company_ticker)
        logger.info(
            "NewsAPIProvider: fetching articles. ticker=%s query=%r max=%d",
            company_ticker,
            search_query,
            max_articles,
        )

        try:
            response = self._client.get_everything(
                q=search_query,
                language="en",
                sort_by="publishedAt",
                page_size=min(max_articles, 100),
            )
        except NewsAPIException as exc:
            # Free plan does not support get_everything — fall back to top-headlines
            logger.warning(
                "NewsAPIProvider: get_everything failed (%s), falling back to top-headlines.",
                exc,
            )
            try:
                response = self._client.get_top_headlines(
                    q=search_query,
                    language="en",
                    page_size=min(max_articles, 100),
                )
            except NewsAPIException as exc2:
                logger.error("NewsAPI top-headlines also failed: %s", exc2)
                raise NewsServiceError(f"NewsAPI request failed: {exc2}") from exc2
            except Exception as exc2:
                logger.exception("Unexpected error in top-headlines fallback.")
                raise NewsServiceError("Unexpected news fetch failure.") from exc2
        except Exception as exc:
            logger.exception("Unexpected error fetching news from NewsAPI.")
            raise NewsServiceError("Unexpected news fetch failure.") from exc

        raw_articles = response.get("articles", [])
        logger.info(
            "NewsAPIProvider: received %d raw articles for %s.",
            len(raw_articles),
            company_ticker,
        )

        cutoff = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=max_age_days)

        articles: list[NewsArticle] = []
        for raw in raw_articles:
            url = raw.get("url") or ""
            if not url:
                continue

            title = raw.get("title") or ""
            # NewsAPI sometimes returns "[Removed]" for deleted articles
            if "[Removed]" in title:
                continue

            published_at = _parse_dt(raw.get("publishedAt"))
            if published_at < cutoff:
                logger.debug("Skipping old article: %s (%s)", title, published_at)
                continue

            # Prefer full content; fall back to description
            content = raw.get("content") or raw.get("description") or ""
            if not content.strip():
                continue

            source_name = (raw.get("source") or {}).get("name") or "Unknown"
            author = raw.get("author") or None

            articles.append(
                NewsArticle(
                    article_id=_make_article_id(url),
                    title=title,
                    content=content,
                    source=source_name,
                    author=author,
                    published_at=published_at,
                    url=url,
                    company=company_ticker,
                )
            )

        logger.info(
            "NewsAPIProvider: %d valid articles after filtering for %s.",
            len(articles),
            company_ticker,
        )
        return articles[:max_articles]


# ── Finnhub stub — plug in later ───────────────────────────────────────────────

class FinnhubNewsProvider(BaseNewsProvider):
    """
    Stub for Finnhub news provider.
    Install finnhub-python and implement fetch_articles() to activate.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def fetch_articles(
        self,
        company_ticker: str,
        max_articles: int,
        max_age_days: int,
    ) -> list[NewsArticle]:
        raise NotImplementedError(
            "FinnhubNewsProvider is not yet implemented. "
            "Set NEWS_PROVIDER=newsapi in .env to use NewsAPI."
        )


# ── Factory ────────────────────────────────────────────────────────────────────

class NewsServiceFactory:
    """
    Returns the correct BaseNewsProvider based on settings.news_provider.

    Adding a new provider:
    1. Create a subclass of BaseNewsProvider.
    2. Add a branch here.
    3. Set NEWS_PROVIDER=<name> in .env.
    """

    @staticmethod
    def create(settings: Settings) -> BaseNewsProvider:
        provider = settings.news_provider.lower()

        if provider == "newsapi":
            if not settings.has_news_api_key:
                raise NewsServiceError(
                    "NEWS_API_KEY is missing. Add it to .env to use the news feature."
                )
            return NewsAPIProvider(api_key=settings.news_api_key)  # type: ignore[arg-type]

        if provider == "finnhub":
            if not settings.news_api_key:
                raise NewsServiceError(
                    "NEWS_API_KEY is missing for Finnhub provider."
                )
            return FinnhubNewsProvider(api_key=settings.news_api_key)  # type: ignore[arg-type]

        raise NewsServiceError(
            f"Unknown news provider: {provider!r}. "
            "Supported: 'newsapi', 'finnhub'."
        )
