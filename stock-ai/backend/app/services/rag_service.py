from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import Settings
from app.config import get_settings

logger = logging.getLogger(__name__)


class RAGService:
    """Ingests documents from documents_dir and retrieves relevant chunks from ChromaDB."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model_name
        )
        self._client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection_name,
            embedding_function=self._embedding_fn,
        )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self._ingest_new_documents()

    def retrieve(self, query: str) -> str:
        """Return top-k relevant chunks for the query as a single string."""
        results = self._collection.query(
            query_texts=[query],
            n_results=min(self.settings.retrieval_top_k, self._collection.count() or 1),
        )
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        return "\n\n".join(docs)

    def _ingest_new_documents(self) -> None:
        docs_dir = self.settings.documents_dir
        if not docs_dir.exists():
            logger.warning("documents_dir does not exist: %s", docs_dir)
            return

        existing_ids: set[str] = set(self._collection.get()["ids"])

        for file_path in docs_dir.iterdir():
            if file_path.suffix.lower() not in {".pdf", ".txt", ".md"}:
                continue
            text = self._extract_text(file_path)
            if not text.strip():
                continue
            chunks = self._splitter.split_text(text)
            new_ids, new_docs = [], []
            for i, chunk in enumerate(chunks):
                chunk_id = f"{file_path.name}::{i}"
                if chunk_id not in existing_ids:
                    new_ids.append(chunk_id)
                    new_docs.append(chunk)
            if new_ids:
                self._collection.add(ids=new_ids, documents=new_docs)
                logger.info("Ingested %d chunks from %s", len(new_ids), file_path.name)

    def _extract_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8", errors="ignore")


@lru_cache(maxsize=1)
def get_rag_service() -> RAGService:
    return RAGService(get_settings())
