"""Web search tool using SearXNG (self-hosted) with DuckDuckGo fallback."""
import json
import logging
import time
import urllib.request

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8765/search?format=json"


def _search_searxng(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via self-hosted SearXNG instance."""
    try:
        url = f"{SEARXNG_URL}&q={urllib.request.quote(query)}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "cognitive-agent/1.0"}
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        results = data.get("results", [])[:max_results]
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            })
        return formatted
    except Exception as e:
        logger.debug("SearXNG search failed: %s", e)
    return None


def _search_ddgs(query: str, max_results: int = 5) -> list[dict]:
    """Fallback: DuckDuckGo search via ddgs library."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []
    for attempt in range(3):
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if results:
            break
        time.sleep(1.0)
    formatted = []
    for r in results:
        formatted.append({
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        })
    return formatted


def register_web_search_tool(registry):
    def handler(args=None, timeout=30):
        query = (args or {}).get("query", "")
        if not query:
            return json.dumps({"error": "No query provided"})
        max_results = int((args or {}).get("max_results", 5))

        results = _search_searxng(query, max_results)
        if results is None:
            results = _search_ddgs(query, max_results)

        return json.dumps(results, ensure_ascii=False)

    registry.register("web_search", {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via SearXNG (self-hosted multi-engine). Returns title, URL, and snippet for each result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {"type": "integer", "description": "Maximum number of results (default: 5)"},
                },
                "required": ["query"],
            },
        },
    }, handler, toolset="core")
