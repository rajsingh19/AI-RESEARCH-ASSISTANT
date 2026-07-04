"""
stream_handler.py — Handles Server-Sent Events (SSE) token streaming for real-time chat responses with inline guardrails.
"""
from __future__ import annotations

import json
import logging
import time
import re
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
        logger.info("Streaming Started")
        start_time = time.perf_counter()
        
        config = types.GenerateContentConfig(
            temperature=self._ai.settings.gemini_temperature,
            max_output_tokens=800,
        )

        first_token_logged = False
        total_tokens = 0
        
        # Real-time prefix buffering system for the specific guardrail phrase
        target_phrase = "buy this stock now"
        holding_buffer = ""

        try:
            # Call the async generate_content_stream endpoint from the google-genai client
            response_stream = await self._ai.client.aio.models.generate_content_stream(
                model=self._ai.settings.gemini_model,
                contents=prompt,
                config=config
            )

            async for chunk in response_stream:
                token = chunk.text or ""
                if not token:
                    continue

                if not first_token_logged:
                    first_token_time = (time.perf_counter() - start_time) * 1000.0
                    logger.info("First Token Time: %.2f ms", first_token_time)
                    first_token_logged = True

                total_tokens += 1
                holding_buffer += token
                
                # Check prefix match constraints
                lower_holding = holding_buffer.lower()
                if target_phrase.startswith(lower_holding):
                    if lower_holding == target_phrase:
                        # Replace matched advice statement with compliant warning
                        sanitized = "This assistant cannot provide investment recommendations."
                        yield f"data: {json.dumps({'token': sanitized})}\n\n"
                        holding_buffer = ""
                    else:
                        # Wait for subsequent chunks to resolve the match
                        continue
                elif lower_holding in target_phrase:
                    # Check substring match case
                    continue
                else:
                    # Flush the buffer contents since no match is imminent
                    if target_phrase in lower_holding:
                        sanitized = re.sub(
                            r"(?i)buy\s+this\s+stock\s+now",
                            "This assistant cannot provide investment recommendations.",
                            holding_buffer
                        )
                        yield f"data: {json.dumps({'token': sanitized})}\n\n"
                    else:
                        yield f"data: {json.dumps({'token': holding_buffer})}\n\n"
                    holding_buffer = ""

            # Flush any remaining held token buffer
            if holding_buffer:
                lower_holding = holding_buffer.lower()
                if target_phrase in lower_holding:
                    sanitized = re.sub(
                        r"(?i)buy\s+this\s+stock\s+now",
                        "This assistant cannot provide investment recommendations.",
                        holding_buffer
                    )
                    yield f"data: {json.dumps({'token': sanitized})}\n\n"
                else:
                    yield f"data: {json.dumps({'token': holding_buffer})}\n\n"

            # 1. Yield computed confidence & citation metadata in a special event
            logger.info("TokenStreamer: LLM stream finished. Sending consolidated metadata payload...")
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            
            # Send close event
            yield "event: close\ndata: {}\n\n"
            
            # Logging Telemetry Metrics
            latency = (time.perf_counter() - start_time) * 1000.0
            tokens_per_second = (total_tokens / (latency / 1000.0)) if latency > 0 else 0
            logger.info("Tokens Per Second: %.2f", tokens_per_second)
            logger.info("Total Tokens: %d", total_tokens)
            logger.info("Latency: %.2f ms", latency)
            logger.info("Streaming Completed")
            
        except Exception as exc:
            logger.exception("TokenStreamer: Error occurred during streaming: %s", exc)
            err_msg = "Error: I encountered a server error while streaming the response."
            yield f"data: {json.dumps({'token': err_msg})}\n\n"
            yield "event: close\ndata: {}\n\n"
