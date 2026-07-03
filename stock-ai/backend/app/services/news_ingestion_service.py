from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.models.chat import NewsArticle
from app.services.news_service import BaseNewsProvider

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Stats returned after a news ingestion run."""

    company: str
    articles_fetched: int
    chunks_added: int
    duplicates_skipped: int


class NewsIngestionService:
    """
    Ingestion pipeline: NewsAPI → clean → chunk → embed → ChromaDB.

    Uses a dedicated ChromaDB collection (settings.news_collection_name)
    separate from the annual reports collection. This keeps news chunks
    filterable and prevents them from diluting document retrieval.

    Metadata stored per chunk:
        category     : "news"
        company      : ticker symbol
        article_id   : SHA256 of URL (dedup key)
        title        : article headline
        source       : publisher name
        author       : author name or ""
        published_at : ISO 8601 string
        url          : original article URL
        chunk_index  : position of this chunk within the article
    """

    def __init__(
        self,
        settings: Settings,
        news_provider: BaseNewsProvider,
    ) -> None:
        self.settings = settings
        self.news_provider = news_provider

        embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model_name
        )
        client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self._collection = client.get_or_create_collection(
            name=settings.news_collection_name,
            embedding_function=embedding_fn,
        )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def ingest_for_company(self, ticker: str) -> IngestionResult:
        """
        Fetch and ingest latest news for one company.

        Steps:
        1. Fetch articles from the news provider.
        2. Skip articles already in ChromaDB (by article_id).
        3. Clean article text.
        4. Split into chunks.
        5. Store chunks with full metadata.

        Returns IngestionResult with stats.
        """
        logger.info("NewsIngestion: starting ingestion for ticker=%s", ticker)

        articles = self.news_provider.fetch_articles(
            company_ticker=ticker,
            max_articles=self.settings.news_top_articles,
            max_age_days=self.settings.news_max_age_days,
        )
        logger.info(
            "NewsIngestion: fetched %d articles for %s.", len(articles), ticker
        )

        existing_article_ids = self._get_existing_article_ids()
        chunks_added = 0
        duplicates_skipped = 0

        for article in articles:
            if article.article_id in existing_article_ids:
                logger.debug(
                    "NewsIngestion: skipping duplicate article_id=%s title=%r",
                    article.article_id,
                    article.title,
                )
                duplicates_skipped += 1
                continue

            added = self._ingest_article(article)
            chunks_added += added
            existing_article_ids.add(article.article_id)

        result = IngestionResult(
            company=ticker,
            articles_fetched=len(articles),
            chunks_added=chunks_added,
            duplicates_skipped=duplicates_skipped,
        )
        logger.info(
            "NewsIngestion: complete for %s. fetched=%d added=%d skipped=%d",
            ticker,
            result.articles_fetched,
            result.chunks_added,
            result.duplicates_skipped,
        )
        return result

    def ingest_for_companies(self, tickers: list[str]) -> list[IngestionResult]:
        """Ingest news for multiple companies. Returns one result per ticker."""
        return [self.ingest_for_company(ticker) for ticker in tickers]

    def collection_count(self) -> int:
        """Return total number of news chunks currently stored."""
        return self._collection.count()

    # ── Private helpers ────────────────────────────────────────────────────────

    def _ingest_article(self, article: NewsArticle) -> int:
        """
        Clean, chunk, and store one article. Returns number of chunks added.
        """
        clean_text = self._clean_text(article.content)
        if not clean_text:
            logger.warning(
                "NewsIngestion: empty content after cleaning. article_id=%s",
                article.article_id,
            )
            return 0

        # Prepend title so every chunk carries context about what it's from
        full_text = f"{article.title}\n\n{clean_text}"
        chunks = self._splitter.split_text(full_text)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{article.article_id}::{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "category": "news",
                "company": article.company,
                "article_id": article.article_id,
                "title": article.title,
                "source": article.source,
                "author": article.author or "",
                "published_at": article.published_at.isoformat(),
                "url": article.url,
                "chunk_index": i,
            })

        if ids:
            self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
            logger.info(
                "NewsIngestion: stored %d chunks for article %r.",
                len(ids),
                article.title,
            )

        return len(ids)

    def _get_existing_article_ids(self) -> set[str]:
        """
        Return the set of article_ids already stored in the news collection.
        Used for deduplication — we check article_id, not chunk_id.
        """
        result = self._collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []
        return {
            m["article_id"]
            for m in metadatas
            if isinstance(m, dict) and "article_id" in m
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        """
        Remove noise from article text:
        - Strip HTML tags
        - Collapse whitespace
        - Remove NewsAPI truncation marker "[+N chars]"
        """
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\[\+\d+ chars\]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
