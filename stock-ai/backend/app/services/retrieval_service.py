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
from app.models.chat import DocumentChunk

logger = logging.getLogger(__name__)


class RetrievalService:
    """
    Vector store abstraction over ChromaDB.

    Responsibilities:
    - Ingest new documents from documents_dir on startup (idempotent).
    - Retrieve top-k relevant DocumentChunk objects for a query.

    Swap guide: to replace ChromaDB with Pinecone or Qdrant, only this
    class needs to change. The interface (retrieve -> list[DocumentChunk])
    stays identical.
    """

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

    # ── Public API ─────────────────────────────────────────────────────────────

    def retrieve(self, query: str) -> list[DocumentChunk]:
        """
        Query ChromaDB and return top-k DocumentChunk objects.

        Each chunk carries:
        - chunk_id  : "<filename>::<index>"
        - document  : source filename
        - content   : raw text
        - relevance_score: cosine distance (lower = more relevant)
        """
        total = self._collection.count()
        if total == 0:
            logger.warning("ChromaDB collection is empty. No documents ingested yet.")
            return []

        n_results = min(self.settings.retrieval_top_k, total)
        logger.info("Querying ChromaDB. query=%r top_k=%d", query, n_results)

        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "distances", "metadatas"],
        )

        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        chunks: list[DocumentChunk] = []
        for chunk_id, content, distance in zip(ids, docs, distances):
            # chunk_id format: "TCS_Q4.pdf::3"
            document_name = chunk_id.split("::")[0] if "::" in chunk_id else chunk_id
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document=document_name,
                    content=content,
                    relevance_score=round(distance, 4),
                )
            )

        logger.info("Retrieved %d chunks from ChromaDB.", len(chunks))
        return chunks

    # ── Ingestion ──────────────────────────────────────────────────────────────

    def _ingest_new_documents(self) -> None:
        """
        Scan documents_dir and ingest any files not yet in ChromaDB.
        Idempotent — already-ingested chunks are skipped by chunk_id check.
        """
        docs_dir = self.settings.documents_dir
        if not docs_dir.exists():
            logger.warning("documents_dir does not exist: %s", docs_dir)
            return

        existing_ids: set[str] = set(self._collection.get()["ids"])
        logger.info("ChromaDB has %d existing chunks.", len(existing_ids))

        for file_path in sorted(docs_dir.iterdir()):
            if file_path.suffix.lower() not in {".pdf", ".txt", ".md"}:
                continue

            text = self._extract_text(file_path)
            if not text.strip():
                logger.warning("Empty text extracted from %s, skipping.", file_path.name)
                continue

            chunks = self._splitter.split_text(text)
            new_ids: list[str] = []
            new_docs: list[str] = []
            new_metadatas: list[dict] = []

            for i, chunk in enumerate(chunks):
                chunk_id = f"{file_path.name}::{i}"
                if chunk_id in existing_ids:
                    continue
                new_ids.append(chunk_id)
                new_docs.append(chunk)
                new_metadatas.append({"source": file_path.name, "chunk_index": i})

            if new_ids:
                self._collection.add(
                    ids=new_ids,
                    documents=new_docs,
                    metadatas=new_metadatas,
                )
                logger.info(
                    "Ingested %d new chunks from '%s'.", len(new_ids), file_path.name
                )
            else:
                logger.debug("'%s' already fully ingested.", file_path.name)

    def _extract_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8", errors="ignore")


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    return RetrievalService(get_settings())
