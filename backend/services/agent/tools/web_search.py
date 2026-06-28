import asyncio

from services.agent.tool_registry import register_tool


@register_tool(
    name="web_search",
    description=(
        "Search the web for current information using DuckDuckGo. Returns top "
        "results with titles, snippets and URLs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)
async def web_search(query: str, max_results: int = 5) -> str:
    try:
        # ddgs performs blocking HTTP requests, so run it off the event loop.
        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _search(query, max_results)
        )
    except Exception as exc:
        return f"Search error: {exc}"

    if not results:
        return f"No results found for: {query}"

    lines = []
    for r in results:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        href = (r.get("href") or "").strip()
        lines.append(f"- {title}\n  {body}\n  {href}")
    return "\n".join(lines)


def _search(query: str, max_results: int) -> list:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))
