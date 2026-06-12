"""Web search tool using DuckDuckGo (no API key required)."""
import json
import logging
import time

# Suppress ddgs library HTTP request logging
for _lib in ("ddgs", "duckduckgo_search", "primp", "curl_cffi"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def register_web_search_tool(registry):
    def handler(args=None, timeout=30):
        query = (args or {}).get("query", "")
        if not query:
            return json.dumps({"error": "No query provided"})
        max_results = int((args or {}).get("max_results", 5))

        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
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
            return json.dumps(formatted, ensure_ascii=False)
        except ImportError:
            return json.dumps({
                "error": "ddgs not installed. Run: pip install ddgs"
            })
        except Exception as e:
            logger.debug("Web search failed: %s", e)
            return json.dumps({"error": str(e)})

    registry.register("web_search", {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns title, URL, and snippet for each result. No API key needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)"
                    }
                },
                "required": ["query"]
            }
        }
    }, handler, toolset="core")
