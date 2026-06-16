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
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
                },
                "required": ["query"],
            },
        },
    }, handler, toolset="core")


def _search_tavily(query: str, max_results: int = 5, api_key: str = "") -> list[dict]:
    """Search via Tavily API (AI-optimized search)."""
    if not api_key:
        return []
    try:
        import urllib.request as _ur
        req = _ur.Request(
            "https://api.tavily.com/search",
            data=json.dumps({
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        data = json.loads(_ur.urlopen(req, timeout=15).read())
        formatted = []
        for r in data.get("results", []):
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "score": r.get("score", 0),
            })
        return formatted
    except Exception as e:
        logger.debug("Tavily search failed: %s", e)
    return []


def register_tavily_search_tool(registry):
    import os
    api_key = os.environ.get("TAVILY_API_KEY", "")

    def handler(args=None, timeout=30):
        query = (args or {}).get("query", "")
        if not query:
            return json.dumps({"error": "No query provided"})
        max_results = int((args or {}).get("max_results", 5))

        results = _search_tavily(query, max_results, api_key=api_key)
        if not results:
            return json.dumps({"error": "Tavily search failed (check TAVILY_API_KEY env)"})

        return json.dumps(results, ensure_ascii=False)

    registry.register("tavily_search", {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": (
                "Search the web via Tavily (AI-optimized, higher relevance). "
                "Use when web_search (SearXNG) returns insufficient results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {"type": "integer", "description": "Maximum number of results (default: 5)"},
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
                },
                "required": ["query"],
            },
        },
    }, handler, toolset="core")
