"""
document_processor.py — Splits long company text filings and profile data into overlapping chunks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.company_fetcher import CompanyDataPayload

logger = logging.getLogger(__name__)


class DocumentProcessor:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def process(self, payload: CompanyDataPayload) -> list[dict]:
        """
        Process CompanyDataPayload sections into list of chunks with metadata.
        Returns:
            List of dicts: [
                {
                    "id": str,
                    "content": str,
                    "metadata": {
                        "company": str,
                        "category": str,
                        "source": str,
                        "chunk_index": int,
                        "retrieved_at": str
                    }
                }
            ]
        """
        ticker = payload.ticker.upper()
        retrieved_at = datetime.now(tz=timezone.utc).isoformat()
        
        # Define fields to chunk and their sources
        sections = [
            ("business_summary", "Profile & Overview", f"{ticker}_Business_Summary.txt"),
            ("annual_report_summary", "Annual Report Highlights", f"{ticker}_Annual_Report.txt"),
            ("quarterly_results_summary", "Quarterly Financial Results", f"{ticker}_Quarterly_Results.txt"),
            ("investor_presentation_notes", "Investor Call & Presentation Notes", f"{ticker}_Investor_Presentation.txt"),
            ("risk_factors", "Risk Factors", f"{ticker}_Risk_Factors.txt"),
            ("mda", "Management Discussion & Analysis", f"{ticker}_MDA.txt"),
        ]

        all_chunks = []
        for attr, category, filename in sections:
            text = getattr(payload, attr, None)
            if not text or not text.strip():
                continue
                
            # split text into chunks
            chunks = self._splitter.split_text(text)
            logger.info("DocumentProcessor: section=%s split into %d chunks", attr, len(chunks))
            
            for i, chunk in enumerate(chunks):
                chunk_id = f"{filename}::{i}"
                all_chunks.append({
                    "id": chunk_id,
                    "content": f"{category} for {payload.company_name} ({ticker}):\n\n{chunk}",
                    "metadata": {
                        "company": ticker,
                        "category": category,
                        "source": filename,
                        "chunk_index": i,
                        "retrieved_at": retrieved_at
                    }
                })
                
        return all_chunks
