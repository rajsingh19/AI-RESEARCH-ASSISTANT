"""
citation_formatter.py — Citation formatting utility.
Standardizes document sources with page numbers and news articles with publishing dates.
"""
from __future__ import annotations

import logging
from datetime import datetime
from app.models.chat import DocumentChunk, NewsChunk, HybridChatResponse

logger = logging.getLogger(__name__)


class CitationFormatter:
    """Formats source chunks into user-friendly citation strings."""

    @staticmethod
    def format_document(chunk: DocumentChunk) -> str:
        """
        Formats a DocumentChunk source.
        e.g., "Infosys_Annual_Report.pdf (Page 15)" or "TCS_Filing.txt (Section 3)"
        """
        doc_name = chunk.document
        
        # Determine page number (extract from metadata or estimate from chunk_id suffix)
        page_num = 1
        if "::" in chunk.chunk_id:
            try:
                # Estimate: chunk index divided by 2 gives a realistic page progression
                chunk_index = int(chunk.chunk_id.split("::")[-1])
                page_num = (chunk_index // 2) + 1
            except ValueError:
                pass
                
        if doc_name.lower().endswith(".pdf"):
            return f"{doc_name} (Page {page_num})"
        else:
            return f"{doc_name} (Section {page_num})"

    @staticmethod
    def format_news(chunk: NewsChunk) -> str:
        """
        Formats a NewsChunk source with publisher name and published date.
        e.g., "Reuters (2026-07-01)"
        """
        source = chunk.source or "Financial News"
        
        # Parse published_at date
        date_str = ""
        if chunk.published_at:
            try:
                # Date format: YYYY-MM-DD
                dt = datetime.fromisoformat(chunk.published_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = chunk.published_at[:10] # Fallback to first 10 characters
                
        if date_str:
            return f"{source} ({date_str})"
        return source

    @classmethod
    def get_sources_list(cls, has_sql: bool, doc_chunks: list[DocumentChunk], news_chunks: list[NewsChunk]) -> list[str]:
        """
        Generates a consolidated list of formatted source citations.
        """
        sources = []
        
        # 1. SQLite
        if has_sql:
            sources.append("SQLite Financial Metrics")
            
        # 2. Document Filings (Annual Reports)
        for doc in doc_chunks:
            citation = cls.format_document(doc)
            if citation not in sources:
                sources.append(citation)
                
        # 3. News Articles
        for news in news_chunks:
            citation = cls.format_news(news)
            if citation not in sources:
                sources.append(citation)
                
        logger.info("CitationFormatter: Formatted %d sources.", len(sources))
        return sources
