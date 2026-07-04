from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE_FILE = BASE_DIR / ".env.example"

load_dotenv(dotenv_path=ENV_FILE, override=False)
if not ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_EXAMPLE_FILE, override=False)


class SettingsError(RuntimeError):
    """Raised when application settings are invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    # ── App ────────────────────────────────────────────────────────────────────
    app_name: str
    app_version: str
    app_env: str
    debug: bool
    log_level: str
    port: int


    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str

    # ── Gemini ─────────────────────────────────────────────────────────────────
    gemini_api_key: str | None
    gemini_model: str
    gemini_temperature: float
    gemini_timeout_ms: int

    # ── RAG / ChromaDB ─────────────────────────────────────────────────────────
    documents_dir: Path
    chroma_persist_dir: Path
    chroma_collection_name: str
    embedding_model_name: str
    retrieval_top_k: int
    chunk_size: int
    chunk_overlap: int

    # ── Phase 9: News ──────────────────────────────────────────────────────────
    news_api_key: str | None          # NewsAPI.org key
    news_provider: str                # "newsapi" | "finnhub" — extensible
    news_collection_name: str         # separate ChromaDB collection for news
    news_top_articles: int            # how many articles to fetch per company
    news_max_age_days: int            # skip articles older than this
    news_cache_ttl_hours: int         # cache hit threshold (default 24h)

    # ── Configurable Providers (Feature 13) ────────────────────────────────────
    llm_provider: str                 # "gemini" | "openai" | "claude"
    openai_api_key: str | None
    openai_model: str
    embedding_provider: str            # "sentence-transformers" | "openai"
    vector_db_provider: str            # "chroma" | "pinecone" | "qdrant"
    financial_data_provider: str       # "yahoo" | "alphavantage" | "finnhub" | "polygon"
    alphavantage_api_key: str | None
    finnhub_api_key: str | None
    polygon_api_key: str | None
    news_retention_days: int           # cleanup threshold (default 30 days)

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def has_gemini_api_key(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_news_api_key(self) -> bool:
        return bool(self.news_api_key)

    @property
    def has_openai_api_key(self) -> bool:
        return bool(self.openai_api_key)



def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(
    value: str | None,
    *,
    default: float,
    name: str,
    min_value: float,
    max_value: float,
) -> float:
    if value is None:
        parsed = default
    else:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise SettingsError(f"{name} must be a valid float.") from exc

    if parsed < min_value or parsed > max_value:
        raise SettingsError(
            f"{name} must be between {min_value} and {max_value}."
        )
    return parsed


def _parse_int(
    value: str | None,
    *,
    default: int,
    name: str,
    min_value: int,
) -> int:
    if value is None:
        parsed = default
    else:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise SettingsError(f"{name} must be a valid integer.") from exc

    if parsed < min_value:
        raise SettingsError(f"{name} must be at least {min_value}.")
    return parsed


def _parse_path(value: str | None, *, default: Path) -> Path:
    if value is None:
        return default
    return Path(value).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = _get_env("APP_ENV", "development") or "development"
    debug = _parse_bool(_get_env("DEBUG"), default=app_env == "development")
    log_level = (_get_env("LOG_LEVEL", "INFO") or "INFO").upper()

    valid_log_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if log_level not in valid_log_levels:
        raise SettingsError(
            "LOG_LEVEL must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG."
        )

    database_url = _get_env("DATABASE_URL")
    if database_url is None:
        database_url = f"sqlite:///{BASE_DIR / 'stock.db'}"

    gemini_api_key = _get_env("GEMINI_API_KEY") or _get_env("GOOGLE_API_KEY")

    documents_dir = _parse_path(
        _get_env("DOCUMENTS_DIR"),
        default=BASE_DIR / "documents",
    )
    chroma_persist_dir = _parse_path(
        _get_env("CHROMA_PERSIST_DIR"),
        default=BASE_DIR / "chroma_db",
    )
    chunk_size = _parse_int(
        _get_env("CHUNK_SIZE"),
        default=800,
        name="CHUNK_SIZE",
        min_value=100,
    )
    chunk_overlap = _parse_int(
        _get_env("CHUNK_OVERLAP"),
        default=150,
        name="CHUNK_OVERLAP",
        min_value=0,
    )
    if chunk_overlap >= chunk_size:
        raise SettingsError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")

    retrieval_top_k = _parse_int(
        _get_env("RETRIEVAL_TOP_K"),
        default=4,
        name="RETRIEVAL_TOP_K",
        min_value=1,
    )

    # ── Phase 9: News settings ─────────────────────────────────────────────────
    news_provider = (_get_env("NEWS_PROVIDER", "newsapi") or "newsapi").lower()
    valid_providers = {"newsapi", "finnhub"}
    if news_provider not in valid_providers:
        raise SettingsError(
            f"NEWS_PROVIDER must be one of {valid_providers}. Got: {news_provider}"
        )

    news_top_articles = _parse_int(
        _get_env("NEWS_TOP_ARTICLES"),
        default=10,
        name="NEWS_TOP_ARTICLES",
        min_value=1,
    )
    news_max_age_days = _parse_int(
        _get_env("NEWS_MAX_AGE_DAYS"),
        default=7,
        name="NEWS_MAX_AGE_DAYS",
        min_value=1,
    )

    return Settings(
        app_name=_get_env("APP_NAME", "Stock Market Assistant API")
        or "Stock Market Assistant API",
        app_version=_get_env("APP_VERSION", "1.0.0") or "1.0.0",
        app_env=app_env,
        port=_parse_int(_get_env("PORT"), default=8000, name="PORT", min_value=1),
        debug=debug,
        log_level=log_level,
        database_url=database_url,
        gemini_api_key=gemini_api_key,
        gemini_model=_get_env("GEMINI_MODEL", "gemini-3.1-flash-lite")
        or "gemini-3.1-flash-lite",
        gemini_temperature=_parse_float(
            _get_env("GEMINI_TEMPERATURE"),
            default=0.2,
            name="GEMINI_TEMPERATURE",
            min_value=0.0,
            max_value=1.0,
        ),
        gemini_timeout_ms=_parse_int(
            _get_env("GEMINI_TIMEOUT_MS"),
            default=30000,
            name="GEMINI_TIMEOUT_MS",
            min_value=1000,
        ),
        documents_dir=documents_dir,
        chroma_persist_dir=chroma_persist_dir,
        chroma_collection_name=_get_env(
            "CHROMA_COLLECTION_NAME",
            "financial_documents",
        )
        or "financial_documents",
        embedding_model_name=_get_env(
            "EMBEDDING_MODEL_NAME",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        or "sentence-transformers/all-MiniLM-L6-v2",
        retrieval_top_k=retrieval_top_k,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # Phase 9
        news_api_key=_get_env("NEWS_API_KEY"),
        news_provider=news_provider,
        news_collection_name=_get_env("NEWS_COLLECTION_NAME", "financial_news")
        or "financial_news",
        news_top_articles=news_top_articles,
        news_max_age_days=news_max_age_days,
        news_cache_ttl_hours=_parse_int(
            _get_env("NEWS_CACHE_TTL_HOURS"),
            default=24,
            name="NEWS_CACHE_TTL_HOURS",
            min_value=1,
        ),
        # Configurable Providers (Feature 13)
        llm_provider=(_get_env("LLM_PROVIDER", "gemini") or "gemini").lower(),
        openai_api_key=_get_env("OPENAI_API_KEY"),
        openai_model=_get_env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        embedding_provider=(_get_env("EMBEDDING_PROVIDER", "sentence-transformers") or "sentence-transformers").lower(),
        vector_db_provider=(_get_env("VECTOR_DB_PROVIDER", "chroma") or "chroma").lower(),
        financial_data_provider=(_get_env("FINANCIAL_DATA_PROVIDER", "yahoo") or "yahoo").lower(),
        alphavantage_api_key=_get_env("ALPHAVANTAGE_API_KEY") or _get_env("ALPHA_VANTAGE_API_KEY"),
        finnhub_api_key=_get_env("FINNHUB_API_KEY"),
        polygon_api_key=_get_env("POLYGON_API_KEY"),
        news_retention_days=_parse_int(
            _get_env("NEWS_RETENTION_DAYS"),
            default=30,
            name="NEWS_RETENTION_DAYS",
            min_value=1,
        ),
    )
