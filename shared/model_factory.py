from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


class ModelChain:
    def __init__(self, entries: list[tuple[dict, list[AsyncOpenAI]]]):
        self._entries = entries

    @classmethod
    def from_mock(cls, mock_client: Any, model_cfg: dict | None = None) -> "ModelChain":
        cfg = model_cfg or {
            "provider": "mock",
            "model_id": "mock-model",
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        return cls([(cfg, [mock_client])])

    @property
    def primary_label(self) -> str:
        if self._entries:
            m = self._entries[0][0]
            return f"{m['provider']}/{m['model_id']}"
        return "none configured"

    @property
    def chain_labels(self) -> list[str]:
        return [f"{m['provider']}/{m['model_id']}" for m, _ in self._entries]

    async def call(
        self,
        messages: list,
        extra_kwargs: dict | None = None,
    ) -> tuple[Any, dict]:
        extra = extra_kwargs or {}
        last_exc: Exception | None = None

        for model_cfg, clients in self._entries:
            for client in clients:
                try:
                    response = await client.chat.completions.create(
                        model=model_cfg["model_id"],
                        messages=messages,
                        temperature=model_cfg.get("temperature", 0.1),
                        max_tokens=model_cfg.get("max_tokens", 1024),
                        **extra,
                    )
                    return response, model_cfg
                except Exception as exc:
                    log.warning(
                        "[chain] %s/%s failed: %s — trying next",
                        model_cfg["provider"],
                        model_cfg["model_id"],
                        exc,
                    )
                    last_exc = exc

        raise last_exc or RuntimeError("ModelChain: all models exhausted with no success")


def build_chain(
    model_chain_ids: list[str],
    models_registry: dict,
    providers: dict,
) -> ModelChain:
    entries = []

    for mid in model_chain_ids:
        if mid not in models_registry:
            log.warning("[chain] model '%s' not found in models registry — skipping", mid)
            continue

        mcfg = models_registry[mid]
        mcfg_dict = mcfg.model_dump() if hasattr(mcfg, "model_dump") else dict(mcfg)

        provider_name = mcfg_dict["provider"]
        pcfg = providers.get(provider_name)
        if pcfg is None:
            log.warning("[chain] provider '%s' not in providers section — skipping '%s'", provider_name, mid)
            continue

        base_url = pcfg.get("base_url") if isinstance(pcfg, dict) else getattr(pcfg, "base_url", None)
        if not base_url:
            log.warning("[chain] provider '%s' has no base_url — skipping '%s'", provider_name, mid)
            continue

        api_keys = mcfg_dict.get("api_keys") or []
        valid_keys = [k for k in api_keys if k and k.strip()]

        if not valid_keys:
            log.warning(
                "[chain] model '%s' (%s/%s) has no valid api_keys in .env — skipping",
                mid, provider_name, mcfg_dict["model_id"],
            )
            continue

        clients = [AsyncOpenAI(api_key=k, base_url=base_url) for k in valid_keys]
        entries.append((mcfg_dict, clients))

    if not entries:
        raise ValueError(
            "ModelChain: no usable models found. "
            "Add at least one api_key in config.yaml and the matching env var in .env"
        )

    log.info("[chain] built: %s", " → ".join(f"{m['provider']}/{m['model_id']}" for m, _ in entries))
    return ModelChain(entries)
