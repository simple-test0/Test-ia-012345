import json
import logging
import re
import uuid
from typing import Callable, List, Optional

from services.agent.ollama_client import OllamaClient
from services.agent.tool_registry import execute_tool, tools_as_ollama_schema

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """You are a capable AI assistant with access to tools.
Use a tool only when it helps answer the user's request; otherwise answer directly.
After receiving a tool result, continue your response naturally. Think step by step."""


class ReactAgent:
    """Agent that uses Ollama's native tool/function calling, with a regex
    fallback for models/servers that don't return structured tool calls."""

    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model
        self.max_iterations = 10

    def _extract_tool_call(self, text: str) -> Optional[dict]:
        """Fallback: parse a ```tool {json}``` block (or bare JSON) from text."""
        match = re.search(r"```tool\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict) and "tool" in data:
                return data
        except json.JSONDecodeError:
            pass
        return None

    @staticmethod
    def _normalize_args(args) -> dict:
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {}
        return args or {}

    async def run(
        self,
        messages: List[dict],
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> str:
        tools = tools_as_ollama_schema()
        history = [{"role": "system", "content": SYSTEM_TEMPLATE}] + messages

        for _ in range(self.max_iterations):
            try:
                message = await self.client.chat(
                    model=self.model, messages=history, tools=tools
                )
            except Exception as exc:
                logger.exception("Ollama chat failed")
                if on_event:
                    on_event({"type": "error", "message": f"Ollama error: {exc}"})
                return f"Error contacting the model: {exc}"

            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls") or []

            # Fallback: some models embed a ```tool block instead of returning
            # native tool_calls.
            if not tool_calls:
                legacy = self._extract_tool_call(content)
                if legacy:
                    tool_calls = [{
                        "function": {
                            "name": legacy.get("tool", ""),
                            "arguments": legacy.get("args", {}),
                        }
                    }]

            if not tool_calls:
                # Final answer. Emit it as a token (so the UI renders content)
                # then signal completion.
                if on_event:
                    if content:
                        on_event({"type": "token", "content": content})
                    on_event({"type": "message_complete", "full_content": content})
                return content

            history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                tool_args = self._normalize_args(fn.get("arguments", {}))
                call_id = str(uuid.uuid4())

                if on_event:
                    on_event({
                        "type": "tool_call",
                        "id": call_id,
                        "tool_name": tool_name,
                        "args": tool_args,
                    })

                tool_result = await execute_tool(tool_name, tool_args)

                if on_event:
                    on_event({
                        "type": "tool_result",
                        "id": call_id,
                        "tool_name": tool_name,
                        "result": str(tool_result),
                    })

                history.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": str(tool_result),
                })

        if on_event:
            on_event({"type": "error", "message": "Max iterations reached"})
        return "Max iterations reached without a final response."
