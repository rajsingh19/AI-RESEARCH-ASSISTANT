"""Finnhub provider stub. Subclass BaseNewsProvider to activate."""
from __future__ import annotations

from app.models.chat import NewsArticle
from app.services.news.providers.base_provider import BaseNewsProvider


class FinnhubNewsProvider(BaseNewsProvider):
    """
    Finnhub.io news provider stub.
    To activate: pip install finnhub-python, implement fetch_articles(),
    set NEWS_PROVIDER=finnhub in .env.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Finnhub"

    def fetch_articles(self, company_ticker: str, max_articles: int, max_age_days: int) -> list[NewsArticle]:
        raise NotImplementedError(
            "FinnhubNewsProvider not implemented. Set NEWS_PROVIDER=newsapi in .env."
        )
