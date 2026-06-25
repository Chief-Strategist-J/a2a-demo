"""Web search tool stub.

To enable:
1. Set enabled: true for web_search in config.yaml
2. Add BRAVE_API_KEY (or another search API key) to .env
3. Replace the stub implementation below with a real API call.
"""
from __future__ import annotations

import os

from shared.tools.registry import register


@register(
    name="web_search",
    description=(
        "Search the web for current, real-time information. "
        "Use when the user asks about recent events or facts that may have changed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up",
            }
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> str:
    brave_key = os.environ.get("BRAVE_API_KEY", "")
    if not brave_key:
        return (
            f"[web_search] Tool registered but BRAVE_API_KEY not set. "
            f"Query was: '{query}'. "
            "Add your Brave Search API key to .env to activate."
        )

    # --- Replace with real implementation ---
    # import httpx
    # resp = httpx.get(
    #     "https://api.search.brave.com/res/v1/web/search",
    #     params={"q": query, "count": 5},
    #     headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
    #     timeout=10,
    # )
    # results = resp.json().get("web", {}).get("results", [])
    # return "\n".join(f"- {r['title']}: {r['url']}\n  {r.get('description','')}" for r in results)
    return f"[web_search stub] Query: '{query}' — implement the API call above."
