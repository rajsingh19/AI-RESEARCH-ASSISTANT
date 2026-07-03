"""
retrieval_service.py — Document + News retrieval from ChromaDB.

DocumentRetrievalService: annual reports, filings, PDFs.
NewsRetrievalService: live news chunks with full citation metadata.
Both return typed models (DocumentChunk, NewsChunk) — never raw dicts.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import Settings, get_settings
from app.models.chat import DocumentChunk, NewsChunk
from app.services.rag.chroma_client import get_chroma_client
from app.services.rag.embedding_service import get_embedding_function

logger = logging.getLogger(__name__)


class DocumentRetrievalService:
    """
    Ingests PDFs/TXT/MD from documents_dir on startup (idempotent).
    Retrieves top-k DocumentChunk objects for a query.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        client = get_chroma_client()
        self._collection = client.get_or_create_collection(
            name=settings.chroma_collection_name,
            embedding_function=get_embedding_function(),
        )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self._ingest_new_documents()

    def retrieve(self, query: str) -> list[DocumentChunk]:
        total = self._collection.count()
        if total == 0:
            logger.warning("DocumentRetrieval: collection empty.")
            return []
        n = min(self._settings.retrieval_top_k, total)
        logger.info("DocumentRetrieval: querying top_k=%d query=%r", n, query)
        results = self._collection.query(
            query_texts=[query], n_results=n,
            include=["documents", "distances", "metadatas"],
        )
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        chunks = []
        for chunk_id, content, dist in zip(ids, docs, distances):
            doc_name = chunk_id.split("::")[0] if "::" in chunk_id else chunk_id
            chunks.append(DocumentChunk(
                chunk_id=chunk_id, document=doc_name,
                content=content, relevance_score=round(dist, 4),
            ))
        logger.info("DocumentRetrieval: returned %d chunks.", len(chunks))
        return chunks

    def _ingest_new_documents(self) -> None:
        docs_dir = self._settings.documents_dir
        if not docs_dir.exists():
            return
        existing: set[str] = set(self._collection.get()["ids"])
        for file_path in sorted(docs_dir.iterdir()):
            if file_path.suffix.lower() not in {".pdf", ".txt", ".md"}:
                continue
            text = self._extract_text(file_path)
            if not text.strip():
                continue
            chunks = self._splitter.split_text(text)
            new_ids, new_docs, new_meta = [], [], []
            for i, chunk in enumerate(chunks):
                cid = f"{file_path.name}::{i}"
                if cid in existing:
                    continue
                new_ids.append(cid)
                new_docs.append(chunk)
                new_meta.append({"source": file_path.name, "chunk_index": i})
            if new_ids:
                self._collection.add(ids=new_ids, documents=new_docs, metadatas=new_meta)
                logger.info("DocumentRetrieval: ingested %d chunks from %s.", len(new_ids), file_path.name)

    @staticmethod
    def _extract_text(path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8", errors="ignore")


class NewsRetrievalService:
    """
    Semantic search over the ChromaDB news collection.
    Supports optional company_filter for ticker-scoped queries.
    Ranks by relevance score (lower distance = more relevant).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        client = get_chroma_client()
        self._collection = client.get_or_create_collection(
            name=settings.news_collection_name,
            embedding_function=get_embedding_function(),
        )

    def retrieve(self, query: str, company_filter: list[str] | None = None) -> list[NewsChunk]:
        total = self._collection.count()
        if total == 0:
            logger.info("NewsRetrieval: collection empty.")
            return []

        n = min(self._settings.retrieval_top_k, total)
        logger.info("NewsRetrieval: querying top_k=%d filter=%s query=%r", n, company_filter, query)

        where: dict | None = None
        if company_filter:
            where = ({"company": {"$eq": company_filter[0]}} if len(company_filter) == 1
                     else {"company": {"$in": company_filter}})

        kwargs: dict = {
            "query_texts": [query], "n_results": n,
            "include": ["documents", "distances", "metadatas"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        chunks = []
        for chunk_id, content, dist, meta in zip(ids, docs, distances, metadatas):
            if not isinstance(meta, dict):
                meta = {}
            chunks.append(NewsChunk(
                chunk_id=chunk_id,
                article_id=meta.get("article_id", ""),
                title=meta.get("title", ""),
                source=meta.get("source", ""),
                author=meta.get("author") or None,
                published_at=meta.get("published_at", ""),
                url=meta.get("url", ""),
                company=meta.get("company", ""),
                content=content,
                relevance_score=round(dist, 4),
            ))

        # Sort by published_at descending (newest first) for freshness priority
        chunks.sort(key=lambda c: c.published_at, reverse=True)
        logger.info("NewsRetrieval: returned %d chunks.", len(chunks))
        return chunks

    def count(self) -> int:
        return self._collection.count()


@lru_cache(maxsize=1)
def get_document_retrieval_service() -> DocumentRetrievalService:
    return DocumentRetrievalService(get_settings())


@lru_cache(maxsize=1)
def get_news_retrieval_service() -> NewsRetrievalService:
    return NewsRetrievalService(get_settings())
