"""
session_memory.py — Thread-safe session-based conversation memory.
Keeps the last 10 messages (5 user-assistant turns) for conversational context.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


class SessionMemory:
    """Manages conversational history for multi-turn chatbot interactions."""

    def __init__(self, max_messages: int = 10) -> None:
        self.max_messages = max_messages
        self._memory: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._lock = Lock()

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message (user or assistant) to the session history."""
        session_key = session_id or "default_session"
        with self._lock:
            history = self._memory[session_key]
            history.append({"role": role, "content": content})
            # Enforce sliding window limit
            if len(history) > self.max_messages:
                self._memory[session_key] = history[-self.max_messages:]
            logger.info("SessionMemory: Added %s message for session=%s (current count: %d)",
                        role, session_key, len(self._memory[session_key]))

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        """Retrieve message history for a given session."""
        session_key = session_id or "default_session"
        with self._lock:
            return list(self._memory[session_key])

    def clear(self, session_id: str) -> None:
        """Clear memory history for a session."""
        session_key = session_id or "default_session"
        with self._lock:
            if session_key in self._memory:
                del self._memory[session_key]
            logger.info("SessionMemory: Cleared history for session=%s", session_key)

    def format_for_prompt(self, session_id: str) -> str:
        """Format the history as a text block to be injected into prompts."""
        history = self.get_history(session_id)
        if not history:
            return ""
        
        lines = []
        for msg in history:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role_label}: {msg['content']}")
        return "\n".join(lines)
