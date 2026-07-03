from __future__ import annotations

import logging
from functools import lru_cache

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.config import Settings
from app.config import get_settings
from app.models.chat import NewsChunk

logger = logging.getLogger(__name__)


class NewsRetrievalService:
    """
    Semantic search over the news ChromaDB collection.

    Returns list[NewsChunk] — each chunk carries full citation metadata
    (title, source, published_at, url) so the API response is fully citable.

    Swap guide: replace ChromaDB calls here to use Pinecone or Qdrant.
    The interface (retrieve -> list[NewsChunk]) stays identical.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model_name
        )
        client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self._collection = client.get_or_create_collection(
            name=settings.news_collection_name,
            embedding_function=embedding_fn,
        )

    def retrieve(
        self,
        query: str,
        company_filter: list[str] | None = None,
    ) -> list[NewsChunk]:
        """
        Query the news collection and return top-k NewsChunk objects.

        Args:
            query: The user's question or search string.
            company_filter: Optional list of tickers to restrict results to.
                            e.g. ["TCS", "INFY"]. None means no filter.

        Returns:
            List of NewsChunk sorted by relevance (most relevant first).
        """
        total = self._collection.count()
        if total == 0:
            logger.info("NewsRetrieval: news collection is empty.")
            return []

        n_results = min(self.settings.retrieval_top_k, total)
        logger.info(
            "NewsRetrieval: querying. query=%r top_k=%d company_filter=%s",
            query,
            n_results,
            company_filter,
        )

        # Build ChromaDB where filter if company tickers are specified
        where: dict | None = None
        if company_filter:
            if len(company_filter) == 1:
                where = {"company": {"$eq": company_filter[0]}}
            else:
                where = {"company": {"$in": company_filter}}

        query_kwargs: dict = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "distances", "metadatas"],
        }
        if where:
            query_kwargs["where"] = where

        results = self._collection.query(**query_kwargs)

        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        chunks: list[NewsChunk] = []
        for chunk_id, content, distance, meta in zip(ids, docs, distances, metadatas):
            if not isinstance(meta, dict):
                meta = {}
            chunks.append(
                NewsChunk(
                    chunk_id=chunk_id,
                    article_id=meta.get("article_id", ""),
                    title=meta.get("title", ""),
                    source=meta.get("source", ""),
                    author=meta.get("author") or None,
                    published_at=meta.get("published_at", ""),
                    url=meta.get("url", ""),
                    company=meta.get("company", ""),
                    content=content,
                    relevance_score=round(distance, 4),
                )
            )

        logger.info("NewsRetrieval: returned %d news chunks.", len(chunks))
        return chunks

    def count(self) -> int:
        return self._collection.count()


@lru_cache(maxsize=1)
def get_news_retrieval_service() -> NewsRetrievalService:
    return NewsRetrievalService(get_settings())
