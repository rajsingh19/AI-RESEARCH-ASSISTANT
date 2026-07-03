"""Abstract base for all news providers. SOLID Open/Closed."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.models.chat import NewsArticle


def make_article_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


def parse_iso_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=timezone.utc)


class BaseNewsProvider(ABC):
    """
    Contract every news provider must satisfy.
    Add Polygon / Yahoo Finance / Alpha Vantage by subclassing this.
    Register in NewsServiceFactory — zero changes to business logic.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def fetch_articles(
        self,
        company_ticker: str,
        max_articles: int,
        max_age_days: int,
    ) -> list[NewsArticle]:
        """Return list[NewsArticle]. Empty list on no results. Never raise."""
