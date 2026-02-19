"""
LLM Backend abstraction for Stage 5b.

Defines the LLMBackend protocol — a single complete() method that Stage 5b calls
for every field group.  All provider differences (HTTP format, auth, JSON mode)
are encapsulated inside each backend implementation.

Currently implemented:
  OllamaBackend — Ollama local inference via /api/generate (JSON mode enforced)

Adding a new provider means implementing the protocol with one method::

    class MyBackend:
        def complete(self, system_prompt: str, user_prompt: str) -> dict:
            ...

The typical split in practice:
  - OpenAI-compatible (Ollama /v1, OpenRouter, Groq, Together): one shared backend
  - Anthropic Claude: separate backend (different SDK, no native JSON mode)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMBackend(Protocol):
    """
    Protocol for LLM completion backends.

    A backend receives a system prompt and a user prompt, calls the underlying
    LLM, and returns a parsed JSON dict.  All provider differences — HTTP
    format, authentication, JSON mode enforcement, and retries — are
    encapsulated inside the implementation.

    Stage 5b calls complete() once per field group and expects a plain dict.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Send prompts to the LLM and return the parsed JSON response.

        Args:
            system_prompt: Role and instruction context sent as the system turn.
            user_prompt: Extraction task including the prospectus text.

        Returns:
            Parsed JSON dict from the model response.

        Raises:
            RuntimeError: On connection failure, HTTP error, or invalid JSON.
        """
        ...


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------


@dataclass
class OllamaBackend:
    """
    Ollama local inference backend.

    Calls /api/chat with JSON mode enforced (``format: json``), which
    constrains the model to emit only valid JSON tokens.  Works with any model
    served by Ollama: Qwen3-VL, Qwen2.5, Phi-3.5-mini, Mistral, Llama 3, etc.
    Thinking/reasoning models (Qwen3, QwQ, DeepSeek-R1) are handled correctly:
    chain-of-thought stays in message.thinking; message.content has clean JSON.

    Connection metadata:
        base_url    HTTP address of the running Ollama instance.
        model       Ollama model tag as shown in ``ollama list`` (e.g. ``qwen2.5:7b``).
        timeout     Per-request timeout in seconds.
        temperature Sampling temperature. 0.0 = fully deterministic output.
        num_ctx     Context window in tokens fed to the model.
    """

    base_url: str = "http://localhost:11434"
    model: str = "qwen3-vl:8b"
    timeout: float = 600.0
    temperature: float = 0.0
    num_ctx: int = 8192

    def complete(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Call Ollama's /api/chat endpoint with JSON mode enforced.

        Uses /api/chat (not /api/generate) so that thinking/reasoning models
        such as Qwen3 route their chain-of-thought into message.thinking and
        keep message.content clean for the actual JSON answer.
        ``think: false`` suppresses chain-of-thought tokens entirely, which
        speeds up extraction and avoids wasting context on reasoning traces
        for this deterministic task.

        Args:
            system_prompt: Role and instruction context.
            user_prompt: Extraction task with prospectus text.

        Returns:
            Parsed JSON dict from the model response.

        Raises:
            RuntimeError: On connection failure, HTTP error, or invalid JSON.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }

        url = f"{self.base_url}/api/chat"

        try:
            response = httpx.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. Is it running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama request timed out after {self.timeout}s. "
                f"Try increasing OLLAMA_TIMEOUT in .env."
            ) from exc

        data = response.json()
        raw_text = data.get("message", {}).get("content", "")

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Ollama returned invalid JSON: {raw_text[:500]}"
            ) from exc
