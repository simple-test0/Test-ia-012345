import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable


_registry: Dict[str, Tool] = {}


def register_tool(name: str, description: str, parameters: dict):
    def decorator(func: Callable) -> Callable:
        _registry[name] = Tool(name=name, description=description, parameters=parameters, func=func)
        logger.debug(f"Registered tool: {name}")
        return func
    return decorator


def get_tool(name: str) -> Optional[Tool]:
    return _registry.get(name)


def list_tools() -> List[Tool]:
    return list(_registry.values())


def tools_as_json_schema() -> List[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in _registry.values()
    ]


def tools_as_ollama_schema() -> List[dict]:
    """Tools in Ollama's native function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _registry.values()
    ]


async def execute_tool(name: str, args: dict) -> Any:
    tool = get_tool(name)
    if not tool:
        return f"Error: tool '{name}' not found"
    try:
        import asyncio
        if asyncio.iscoroutinefunction(tool.func):
            return await tool.func(**args)
        return tool.func(**args)
    except Exception as exc:
        logger.exception(f"Tool {name} raised: {exc}")
        return f"Error executing {name}: {exc}"
