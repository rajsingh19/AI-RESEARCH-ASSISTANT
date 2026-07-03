"""
metrics_logger.py — Latency, token-counting, and processing stage metric tracker.
Gathers pipeline telemetry for production-grade profiling.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class MetricsLogger:
    """Tracks latency metrics, stages, and token counts for equity queries."""

    def __init__(self, query: str) -> None:
        self.query = query
        self.start_time = time.perf_counter()
        
        self.intent: str | None = None
        self.plan: str | None = None
        self.sqlite_duration: float = 0.0
        self.vector_duration: float = 0.0
        self.news_duration: float = 0.0
        
        self.prompt_size_chars: int = 0
        self.prompt_token_count: int = 0
        self.llm_duration: float = 0.0
        self.confidence: str | None = None

    def log_intent(self, intent: str) -> None:
        self.intent = intent
        logger.info("[METRICS] Query Intent classified: %s", intent)

    def log_plan(self, plan: str) -> None:
        self.plan = plan
        logger.info("[METRICS] Retrieval Plan generated: %s", plan)

    def record_sqlite(self, duration_ms: float) -> None:
        self.sqlite_duration = duration_ms
        logger.info("[METRICS] SQLite Retrieval completed in %s ms", round(duration_ms, 2))

    def record_vector(self, duration_ms: float) -> None:
        self.vector_duration = duration_ms
        logger.info("[METRICS] Vector Retrieval completed in %s ms", round(duration_ms, 2))

    def record_news(self, duration_ms: float) -> None:
        self.news_duration = duration_ms
        logger.info("[METRICS] News Retrieval completed in %s ms", round(duration_ms, 2))

    def record_prompt(self, prompt: str) -> None:
        self.prompt_size_chars = len(prompt)
        # Approximate tokens using standard word-multiplier (roughly 4 characters per token)
        self.prompt_token_count = max(len(prompt) // 4, 1)
        logger.info("[METRICS] Prompt size: %d characters (~%d tokens)",
                    self.prompt_size_chars, self.prompt_token_count)

    def record_llm(self, duration_ms: float) -> None:
        self.llm_duration = duration_ms
        logger.info("[METRICS] LLM generation completed in %s ms", round(duration_ms, 2))

    def record_confidence(self, confidence: str) -> None:
        self.confidence = confidence
        logger.info("[METRICS] Programmatic Confidence score: %s", confidence)

    def finalize(self) -> None:
        """Log the complete request profile summary."""
        total_duration_ms = (time.perf_counter() - self.start_time) * 1000.0
        logger.info(
            "\n=========================================\n"
            "   TELEMETRY PROFILE SUMMARY             \n"
            "=========================================\n"
            "Query       : %r\n"
            "Intent      : %s\n"
            "Plan        : %s\n"
            "SQLite Dur  : %s ms\n"
            "Vector Dur  : %s ms\n"
            "News Dur    : %s ms\n"
            "Prompt Size : %d chars (~%d tokens)\n"
            "LLM Latency : %s ms\n"
            "Confidence  : %s\n"
            "Total Dur   : %s ms\n"
            "=========================================",
            self.query,
            self.intent or "N/A",
            self.plan or "N/A",
            round(self.sqlite_duration, 2),
            round(self.vector_duration, 2),
            round(self.news_duration, 2),
            self.prompt_size_chars,
            self.prompt_token_count,
            round(self.llm_duration, 2),
            self.confidence or "N/A",
            round(total_duration_ms, 2)
        )
