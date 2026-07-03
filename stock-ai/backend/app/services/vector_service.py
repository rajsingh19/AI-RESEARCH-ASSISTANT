"""
vector_service.py — Inserts and clears document vectors from the ChromaDB collection.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from app.config import Settings
from app.services.rag.chroma_client import get_chroma_client
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class VectorService:
    """Manages insertions, lookups, and deletions in the ChromaDB document collection."""

    def __init__(self, settings: Settings, embedding_service: EmbeddingService) -> None:
        self._settings = settings
        self._client = get_chroma_client()
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection_name,
            embedding_function=embedding_service.get_function(),
        )

    def check_company_exists(self, ticker: str) -> tuple[bool, datetime | None]:
        """
        Check if company document chunks exist in ChromaDB and return the retrieval timestamp.
        Returns:
            tuple: (exists_bool, newest_retrieved_at_datetime)
        """
        ticker_upper = ticker.strip().upper()
        logger.info("VectorService: checking document cache status for ticker=%s", ticker_upper)
        
        try:
            # Query Chroma for chunks matching company = ticker_upper
            result = self._collection.get(
                where={"company": ticker_upper},
                include=["metadatas"],
                limit=100
            )
            metadatas = result.get("metadatas") or []
            
            if not metadatas:
                logger.info("VectorService: cache MISS (no documents) ticker=%s", ticker_upper)
                return False, None

            newest: datetime | None = None
            for meta in metadatas:
                if not isinstance(meta, dict):
                    continue
                retrieved_str = meta.get("retrieved_at")
                if retrieved_str:
                    try:
                        dt = datetime.fromisoformat(retrieved_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if newest is None or dt > newest:
                            newest = dt
                    except (ValueError, TypeError):
                        continue

            logger.info("VectorService: cache HIT ticker=%s newest_chunk_at=%s", ticker_upper, newest)
            return True, newest
        except Exception as exc:
            logger.warning("VectorService: error checking Chroma status: %s", exc)
            return False, None

    def store_chunks(self, chunks: list[dict]) -> None:
        """Store list of chunks with metadata in ChromaDB."""
        if not chunks:
            return
            
        ids = [c["id"] for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]
        
        logger.info("VectorService: storing %d document chunks in collection=%s", len(ids), self._settings.chroma_collection_name)
        try:
            self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
            logger.info("VectorService: successfully stored all chunks.")
        except Exception as exc:
            logger.exception("VectorService: failed to write chunks to ChromaDB.")
            raise RuntimeError("Failed to insert documents into vector database.") from exc

    def delete_company_documents(self, ticker: str) -> None:
        """Clear all chunks associated with a company ticker in ChromaDB documents collection."""
        ticker_upper = ticker.strip().upper()
        logger.info("VectorService: deleting existing documents for ticker=%s", ticker_upper)
        try:
            self._collection.delete(where={"company": ticker_upper})
            logger.info("VectorService: successfully deleted documents.")
        except Exception as exc:
            logger.exception("VectorService: failed to delete documents from ChromaDB.")
            raise RuntimeError(f"Failed to clear documents from vector database for {ticker_upper}.") from exc
