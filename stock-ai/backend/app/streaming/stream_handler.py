"""
stream_handler.py — Handles Server-Sent Events (SSE) token streaming for real-time chat responses.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Any
from google.genai import types

from app.services.ai_service import GeminiAIService
from app.guardrails.output_guardrail import OutputGuardrail

logger = logging.getLogger(__name__)


class TokenStreamer:
    """Manages async token-by-token streaming from Gemini to the client using Server-Sent Events."""

    def __init__(self, ai_service: GeminiAIService) -> None:
        self._ai = ai_service
        self._output_guardrail = OutputGuardrail()

    async def stream_response(
        self,
        prompt: str,
        metadata: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronously stream answer tokens from Gemini.
        Applies safety post-processing (Output Guardrails) and appends metadata at the end.
        
        Args:
            prompt: Formatted prompt containing text contexts.
            metadata: Dict of structured data to yield at stream completion (citations, sql stats, etc.).
            
        Yields:
            FastAPI-compliant event stream chunks (Server-Sent Events).
        """
        logger.info("TokenStreamer: Initiating async content stream from Gemini...")
        
        config = types.GenerateContentConfig(
            temperature=self._ai.settings.gemini_temperature,
            max_output_tokens=800,
        )

        buffer = []
        try:
            # Call the async generate_content_stream endpoint from the google-genai client
            response_stream = await self._ai.client.aio.models.generate_content_stream(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=config
            )

            async for chunk in response_stream:
                token = chunk.text or ""
                if token:
                    # Apply light output guardrail replacements (e.g. BUY THIS STOCK NOW replacement)
                    sanitized_token = self._output_guardrail.evaluate(token)
                    buffer.append(sanitized_token)
                    
                    # Yield standard SSE token chunk
                    yield f"data: {json.dumps({'token': sanitized_token})}\n\n"

            # 1. Yield computed confidence & citation metadata in a special event
            logger.info("TokenStreamer: LLM stream finished. Sending consolidated metadata payload...")
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            
            # Send close event
            yield "event: close\ndata: {}\n\n"
            
        except Exception as exc:
            logger.exception("TokenStreamer: Error occurred during streaming: %s", exc)
            err_msg = "Error: I encountered a server error while streaming the response."
            yield f"data: {json.dumps({'token': err_msg})}\n\n"
            yield "event: close\ndata: {}\n\n"
