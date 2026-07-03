"""
news_ingestion.py — Pipeline: articles → clean → chunk → embed → ChromaDB.

Metadata stored per chunk:
  category, company, article_id, title, source, author,
  published_at, url, chunk_index, retrieved_at, embedding_model
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.models.chat import NewsArticle

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    company: str
    articles_fetched: int
    chunks_added: int
    duplicates_skipped: int


class NewsIngestionService:
    """
    Receives NewsArticle objects, deduplicates by article_id (SHA-256 of URL),
    cleans text, chunks, and stores in the ChromaDB news collection.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        embedding_fn = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model_name)
        client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self._collection = client.get_or_create_collection(
            name=settings.news_collection_name,
            embedding_function=embedding_fn,
        )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    def ingest(self, articles: list[NewsArticle], company: str) -> IngestionResult:
        """Deduplicate, clean, chunk, and store articles. Returns stats."""
        existing = self._existing_article_ids()
        chunks_added = 0
        duplicates_skipped = 0
        retrieved_at = datetime.now(tz=timezone.utc).isoformat()

        for article in articles:
            if article.article_id in existing:
                logger.debug("NewsIngestion: duplicate skipped. id=%s", article.article_id)
                duplicates_skipped += 1
                continue
            added = self._store(article, retrieved_at)
            chunks_added += added
            existing.add(article.article_id)

        result = IngestionResult(company=company, articles_fetched=len(articles),
                                 chunks_added=chunks_added, duplicates_skipped=duplicates_skipped)
        logger.info("NewsIngestion: company=%s fetched=%d added=%d skipped=%d",
                    company, result.articles_fetched, result.chunks_added, result.duplicates_skipped)
        return result

    def collection_count(self) -> int:
        return self._collection.count()

    def _store(self, article: NewsArticle, retrieved_at: str) -> int:
        clean = _clean_text(article.content)
        if not clean:
            return 0
        chunks = self._splitter.split_text(f"{article.title}\n\n{clean}")
        if not chunks:
            return 0

        ids, documents, metadatas = [], [], []
        for i, chunk in enumerate(chunks):
            ids.append(f"{article.article_id}::{i}")
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
                "retrieved_at": retrieved_at,
                "embedding_model": self._settings.embedding_model_name,
            })

        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("NewsIngestion: stored %d chunks for %r.", len(ids), article.title[:60])
        return len(ids)

    def _existing_article_ids(self) -> set[str]:
        result = self._collection.get(include=["metadatas"])
        return {
            m["article_id"]
            for m in (result.get("metadatas") or [])
            if isinstance(m, dict) and "article_id" in m
        }


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\+\d+ chars\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
