"""Sentence-transformer embedding function wrapper."""
from __future__ import annotations

from functools import lru_cache

from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.config import get_settings


@lru_cache(maxsize=1)
def get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    settings = get_settings()
    return SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model_name)
