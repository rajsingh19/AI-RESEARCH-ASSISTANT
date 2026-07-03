# documents/

Drop your financial source documents here. The RAG ingestion pipeline reads
every file in this directory, splits it into chunks, embeds them, and stores
the vectors in `../chroma_db/` under the collection `financial_documents`.

## Supported file types (common loaders)
- `.pdf`   — annual reports, earnings releases, prospectuses
- `.txt`   — plain-text filings, news summaries
- `.md`    — markdown research notes
- `.csv`   — structured financial tables (one document per row)

## Pipeline settings (from .env)
| Setting                 | Value                                    | What it controls                        |
|-------------------------|------------------------------------------|-----------------------------------------|
| `DOCUMENTS_DIR`         | `./documents`                            | This directory                          |
| `CHROMA_PERSIST_DIR`    | `./chroma_db`                            | Where ChromaDB persists vectors         |
| `CHROMA_COLLECTION_NAME`| `financial_documents`                    | ChromaDB collection name                |
| `EMBEDDING_MODEL_NAME`  | `sentence-transformers/all-MiniLM-L6-v2` | HuggingFace embedding model             |
| `CHUNK_SIZE`            | `800`                                    | Chars per chunk                         |
| `CHUNK_OVERLAP`         | `150`                                    | Overlap between consecutive chunks      |
| `RETRIEVAL_TOP_K`       | `4`                                      | Top chunks returned per query           |

## How the paths resolve at runtime
`config.py` calls `Path(value).expanduser().resolve()` on both
`DOCUMENTS_DIR` and `CHROMA_PERSIST_DIR`, so relative paths like `./documents`
are anchored to the `backend/` directory regardless of where you launch uvicorn.

Resolved absolute paths (verified):
- documents   → `/home/raj/MoneyLogix/stock-ai/backend/documents`
- chroma_db   → `/home/raj/MoneyLogix/stock-ai/backend/chroma_db`
