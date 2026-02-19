"""
Pipeline runtime configuration.

Reads LLM connection parameters from environment variables.  If a .env file
is present at the project root, it is loaded automatically on first import.

Usage::

    from pipeline.settings import default_ollama_backend
    backend = default_ollama_backend()

All variables have safe defaults so the pipeline runs on a stock local Ollama
install with no configuration.  The only variable most users need to set is
OLLAMA_MODEL (to match whichever model they have pulled).
"""

from __future__ import annotations

import os

# Load .env file if present (no-op if missing or python-dotenv not installed)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def default_ollama_backend():
    """
    Build an OllamaBackend from environment variables.

    Environment variables (all optional — defaults shown):
        OLLAMA_BASE_URL    Base URL of the Ollama instance.
                           Default: http://localhost:11434
        OLLAMA_MODEL       Model tag as shown in ``ollama list``.
                           Default: qwen2.5:7b
        OLLAMA_TIMEOUT     Per-request timeout in seconds.
                           Default: 120.0
        OLLAMA_NUM_CTX     Context window fed to the model, in tokens.
                           Default: 8192
        OLLAMA_TEMPERATURE Sampling temperature. 0.0 = deterministic output.
                           Default: 0.0

    Returns:
        OllamaBackend configured from the current environment.
    """
    from pipeline.llm_backend import OllamaBackend

    return OllamaBackend(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b"),
        timeout=float(os.environ.get("OLLAMA_TIMEOUT", "600.0")),
        num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "8192")),
        temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0.0")),
    )
