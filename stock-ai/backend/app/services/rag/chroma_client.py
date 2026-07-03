"""Singleton ChromaDB PersistentClient — shared across all services."""
from __future__ import annotations

from functools import lru_cache

import chromadb

from app.config import Settings, get_settings


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.PersistentClient:
    settings = get_settings()
    return chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
