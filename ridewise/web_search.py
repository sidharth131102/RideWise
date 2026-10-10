"""Optional Tavily web search. Returns ([], reason) on any failure or when off.
Never used for transactional questions (enforced by the orchestrator)."""
from __future__ import annotations

from .config import settings
from .contracts import WebHit


def search(query: str, k: int = 3) -> tuple[list[WebHit], str | None]:
    if not settings.web_search_enabled:
        return [], "web search is disabled"
    if not settings.tavily_api_key:
        return [], "no Tavily API key configured"
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        res = client.search(query, max_results=k, search_depth="basic")
        hits = [WebHit(title=r.get("title", ""), url=r.get("url", ""),
                       snippet=r.get("content", "")[:300]) for r in res.get("results", [])]
        return hits, None
    except Exception as e:  # noqa: BLE001
        return [], f"web search failed: {e}"
