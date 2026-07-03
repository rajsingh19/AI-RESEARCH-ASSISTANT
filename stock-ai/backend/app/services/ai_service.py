from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings
from app.config import get_settings
from app.models.chat import ExtractedQuery
from app.models.chat import RetrievalContext
from app.utils.exceptions import AIServiceError
from app.utils.exceptions import ConfigurationError


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.txt"
FINANCIAL_CONTEXT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "financial_context_prompt.txt"
)


class GeminiAIService:
    """Handles all Gemini interactions for extraction and answer generation."""

    def __init__(
        self,
        settings: Settings,
        system_prompt: str,
        financial_context_prompt: str,
    ) -> None:
        if not settings.has_gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is missing. Add it to backend/.env before using /chat."
            )

        self.settings = settings
        self.system_prompt = system_prompt
        self.financial_context_prompt = financial_context_prompt
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms),
        )
        
        # Wrap generate_content to automatically handle 429 Rate Limits/Resource Exhaustion
        original_generate = self.client.models.generate_content

        def generate_content_with_retry(*args, **kwargs):
            import time
            max_retries = 5
            backoff = 3.0
            for attempt in range(max_retries):
                try:
                    return original_generate(*args, **kwargs)
                except Exception as exc:
                    exc_str = str(exc)
                    if any(term in exc_str.lower() for term in ["429", "resource_exhausted", "timeout", "timed out", "503", "500", "unavailable"]):
                        logger.warning("Gemini API rate limit, timeout or 503 service unavailable hit. Retrying in %s seconds...", backoff)
                        time.sleep(backoff)
                        backoff *= 1.5
                    else:
                        raise exc
            raise RuntimeError("Exceeded maximum internal retries for Gemini call due to rate limits.")

        self.client.models.generate_content = generate_content_with_retry

    def extract_query(
        self,
        question: str,
        company_catalog: list[dict[str, str]],
    ) -> ExtractedQuery:
        catalog_text = json.dumps(company_catalog, indent=2)
        extraction_prompt = (
            "Extract the user's intent from the stock question.\n"
            "Return only structured JSON matching the schema.\n"
            "Use ticker symbols from the supported catalog for company_identifiers.\n"
            "If the user asks for a broad comparison like highest profit without naming "
            "companies, set requires_all_companies=true.\n"
            "Supported companies:\n"
            f"{catalog_text}\n\n"
            f"User question: {question}"
        )

        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=extraction_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You extract structured intent for a stock-market assistant. "
                        "Do not answer the question. Only return valid JSON."
                    ),
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=ExtractedQuery,
                ),
            )
        except genai_errors.ClientError as exc:
            logger.exception("Gemini request failed during intent extraction.")
            raise AIServiceError(
                "Gemini could not analyze the user question right now."
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error during intent extraction.")
            raise AIServiceError("Unexpected Gemini extraction failure.") from exc

        if response.parsed is None or not isinstance(response.parsed, ExtractedQuery):
            logger.error(
                "Gemini returned an unparsable extraction response: %s",
                response.text,
            )
            raise AIServiceError("Gemini returned invalid structured output.")

        return response.parsed

    def generate_hybrid_answer(self, prompt: str) -> str:
        """
        Send a fully-built hybrid prompt to Gemini and return the answer.

        The prompt already contains both the structured SQL section and the
        document chunks section — built by PromptBuilder. This method only
        handles the Gemini API call and error handling.
        """
        logger.info("AIService: sending hybrid prompt to Gemini.")
        logger.debug("AIService: hybrid prompt:\n%s", prompt)
        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.settings.gemini_temperature,
                    max_output_tokens=800,
                ),
            )
        except genai_errors.ClientError as exc:
            logger.exception("Gemini hybrid request failed.")
            raise AIServiceError("Gemini could not generate a hybrid answer.") from exc
        except Exception as exc:
            logger.exception("Unexpected error during hybrid answer generation.")
            raise AIServiceError("Unexpected Gemini hybrid failure.") from exc

        answer = (response.text or "").strip()
        if not answer:
            raise AIServiceError("Gemini returned an empty hybrid answer.")
        logger.info("AIService: hybrid answer generated successfully.")
        return answer

    def generate_rag_answer(
        self,
        question: str,
        rag_context: str,
    ) -> str:
        prompt = (
            f"Use the following document context to answer the question.\n\n"
            f"Document Context:\n{rag_context}\n\n"
            f"Question: {question.strip()}\n\n"
            "Answer based only on the context above. "
            "If the answer is not in the context, say it is not available."
        )
        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=self.settings.gemini_temperature,
                    max_output_tokens=500,
                ),
            )
        except genai_errors.ClientError as exc:
            logger.exception("Gemini RAG request failed.")
            raise AIServiceError("Gemini could not generate a RAG answer.") from exc
        except Exception as exc:
            logger.exception("Unexpected error during RAG answer generation.")
            raise AIServiceError("Unexpected Gemini RAG failure.") from exc

        answer = (response.text or "").strip()
        if not answer:
            raise AIServiceError("Gemini returned an empty RAG answer.")
        return answer

    def generate_grounded_answer(
        self,
        question: str,
        financial_context: str,
    ) -> str:
        prompt = self.financial_context_prompt.format(
            financial_context=financial_context,
            question=question.strip(),
        )
        logger.info("Sending grounded financial context to Gemini.")
        logger.debug("Grounded financial prompt: %s", prompt)

        try:
            response = self.client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=self.settings.gemini_temperature,
                    max_output_tokens=500,
                ),
            )
        except genai_errors.ClientError as exc:
            logger.exception("Gemini request failed during answer generation.")
            raise AIServiceError(
                "Gemini could not generate the final grounded answer."
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error during answer generation.")
            raise AIServiceError("Unexpected Gemini answer-generation failure.") from exc

        answer = (response.text or "").strip()
        if not answer:
            raise AIServiceError("Gemini returned an empty answer.")
        logger.info("Gemini grounded answer generated successfully.")
        logger.debug("Gemini grounded answer: %s", answer)
        return answer


@lru_cache(maxsize=1)
def get_ai_service() -> GeminiAIService:
    settings = get_settings()
    try:
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
        financial_context_prompt = FINANCIAL_CONTEXT_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip()
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "Required prompt file is missing."
        ) from exc
    return GeminiAIService(
        settings=settings,
        system_prompt=system_prompt,
        financial_context_prompt=financial_context_prompt,
    )
