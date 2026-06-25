"""LLM client factory.

All supported providers expose an OpenAI-compatible chat/completions API,
so we use a single AsyncOpenAI client regardless of the backend:
  - Groq     → api.groq.com/openai/v1
  - Gemini   → generativelanguage.googleapis.com/v1beta/openai/
  - OpenRouter → openrouter.ai/api/v1
  - Ollama   → localhost:11434/v1  (api_key="ollama")
"""
from __future__ import annotations

from openai import AsyncOpenAI


def build_client(provider: str, provider_cfg: dict) -> AsyncOpenAI:
    api_key = provider_cfg.get("api_key") or "no-key-set"
    base_url = provider_cfg.get("base_url")

    if provider == "ollama":
        api_key = provider_cfg.get("api_key") or "ollama"

    if not base_url:
        raise ValueError(
            f"Provider '{provider}' has no base_url in config.yaml providers section."
        )

    # api_key validated at call-time by the provider — a missing key gives a
    # clear 401 rather than crashing at graph-build time.
    return AsyncOpenAI(api_key=api_key, base_url=base_url)
