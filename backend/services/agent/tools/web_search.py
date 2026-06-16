import httpx

from services.agent.tool_registry import register_tool


@register_tool(
    name="web_search",
    description="Search the web for current information using DuckDuckGo. Returns top results with titles and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {"type": "integer", "description": "Number of results to return (default 5)", "default": 5},
        },
        "required": ["query"],
    },
)
async def web_search(query: str, max_results: int = 5) -> str:
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        results = []
        if data.get("AbstractText"):
            results.append(f"Summary: {data['AbstractText']}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append(f"- {topic['Text']}")

        if not results:
            return f"No results found for: {query}"
        return "\n".join(results)
    except Exception as exc:
        return f"Search error: {exc}"
