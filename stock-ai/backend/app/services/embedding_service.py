"""
embedding_service.py — Wrapper for semantic text embedding generation.
"""
from __future__ import annotations

from app.services.rag.embedding_service import get_embedding_function


class EmbeddingService:
    """Service wrapping sentence-transformer embedding functions for ChromaDB."""

    def __init__(self) -> None:
        self._embedding_fn = get_embedding_function()

    def get_function(self):
        """Return the callable embedding function matching ChromaDB API."""
        return self._embedding_fn
