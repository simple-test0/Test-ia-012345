import inspect
import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable, List, Optional, Union

from services.agent.ollama_client import OllamaClient
from services.agent.tool_registry import execute_tool, tools_as_ollama_schema

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """You are a capable AI assistant with access to tools.
Use a tool only when it helps answer the user's request; otherwise answer directly.
After receiving a tool result, continue your response naturally. Think step by step."""

EventCallback = Callable[[dict], Union[None, Awaitable[None]]]

# Text that may be a legacy tool-call block rather than an answer. While a reply
# could still turn out to be one, streaming is held back so raw JSON never
# flashes in the chat.
_TOOL_PREFIXES = ("```tool", '{"tool"', "{ \"tool\"", "{\n")


def _maybe_tool_block(text: str) -> bool:
    head = text.lstrip()[:8]
    return any(p.startswith(head) or head.startswith(p) for p in _TOOL_PREFIXES)


class ReactAgent:
    """Agent that uses Ollama's native tool/function calling, with a regex
    fallback for models/servers that don't return structured tool calls."""

    def __init__(self, client: OllamaClient, model: str, system_prompt: str = ""):
        self.client = client
        self.model = model
        self.system_prompt = (system_prompt or "").strip()
        self.max_iterations = 10

    def _system_message(self) -> str:
        if self.system_prompt:
            return f"{SYSTEM_TEMPLATE}\n\n{self.system_prompt}"
        return SYSTEM_TEMPLATE

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
                args = json.loads(args)
            except json.JSONDecodeError:
                return {}
        return args if isinstance(args, dict) else {}

    async def run(
        self,
        messages: List[dict],
        on_event: Optional[EventCallback] = None,
    ) -> str:
        async def emit(event: dict) -> None:
            if on_event is None:
                return
            result: Any = on_event(event)
            if inspect.isawaitable(result):
                await result

        tools = tools_as_ollama_schema()
        history = [{"role": "system", "content": self._system_message()}] + messages

        for _ in range(self.max_iterations):
            # Stream tokens to the UI as they arrive, except while the reply
            # might still be a legacy ```tool block.
            state = {"buffer": "", "streamed": False}

            async def on_token(token: str) -> None:
                state["buffer"] += token
                if not state["streamed"] and _maybe_tool_block(state["buffer"]):
                    return
                text = token if state["streamed"] else state["buffer"]
                state["streamed"] = True
                await emit({"type": "token", "content": text})

            try:
                message = await self.client.chat(
                    model=self.model, messages=history, tools=tools, on_token=on_token
                )
            except Exception as exc:
                logger.warning(f"Ollama chat failed: {exc}")
                await emit({"type": "error", "message": f"Ollama error: {exc}"})
                return f"Error contacting the model: {exc}"

            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls") or []

            # Fallback: some models embed a ```tool block instead of returning
            # native tool_calls.
            if not tool_calls and not state["streamed"]:
                legacy = self._extract_tool_call(content)
                if legacy:
                    tool_calls = [{
                        "function": {
                            "name": legacy.get("tool", ""),
                            "arguments": legacy.get("args", {}),
                        }
                    }]

            if not tool_calls:
                # Final answer. Anything not streamed yet (non-streaming client,
                # or a held-back reply) is sent now as one token.
                if content and not state["streamed"]:
                    await emit({"type": "token", "content": content})
                await emit({"type": "message_complete", "full_content": content})
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

                await emit({
                    "type": "tool_call",
                    "id": call_id,
                    "tool_name": tool_name,
                    "args": tool_args,
                })

                tool_result = await execute_tool(tool_name, tool_args)

                await emit({
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

        await emit({"type": "error", "message": "Max iterations reached"})
        return "Max iterations reached without a final response."
