import json
import logging
import re
import uuid
from collections.abc import Callable

from services.agent.ollama_client import OllamaClient
from services.agent.tool_registry import execute_tool, tools_as_json_schema

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """You are a capable AI assistant with access to tools.

Available tools:
{tools_json}

To use a tool, output a JSON block (and only a JSON block) in this format:
```tool
{{"tool": "<tool_name>", "args": {{...}}}}
```

After receiving the tool result, continue your response naturally.
If you don't need any tools, just respond directly.
Think step by step."""


class ReactAgent:
    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model
        self.max_iterations = 10

    def _build_system_prompt(self) -> str:
        tools_json = json.dumps(tools_as_json_schema(), indent=2)
        return SYSTEM_TEMPLATE.format(tools_json=tools_json)

    def _extract_tool_call(self, text: str) -> dict | None:
        pattern = r"```tool\s*\n(.*?)\n```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Fallback: bare JSON with "tool" key
        try:
            data = json.loads(text.strip())
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass
        return None

    async def run(
        self,
        messages: list[dict],
        on_event: Callable[[dict], None] | None = None,
    ) -> str:
        system_msg = {"role": "system", "content": self._build_system_prompt()}
        history = [system_msg, *messages]

        for _ in range(self.max_iterations):
            accumulated = ""

            def on_token(token: str):
                nonlocal accumulated
                accumulated += token
                if on_event:
                    on_event({"type": "token", "content": token})

            response = await self.client.stream_chat(
                model=self.model,
                messages=history,
                on_token=on_token,
            )

            tool_call = self._extract_tool_call(response)

            if not tool_call:
                # Plain response — we're done
                if on_event:
                    on_event({"type": "message_complete", "full_content": response})
                return response

            # Execute tool
            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args", {})
            call_id = uuid.uuid4().hex

            if on_event:
                on_event({"type": "tool_call", "id": call_id, "tool_name": tool_name, "args": tool_args})

            tool_result = await execute_tool(tool_name, tool_args)

            if on_event:
                on_event(
                    {"type": "tool_result", "id": call_id, "tool_name": tool_name, "result": str(tool_result)}
                )

            # Append assistant turn + tool result to history
            history.append({"role": "assistant", "content": response})
            history.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool_name}:\n{tool_result}",
                }
            )

        if on_event:
            on_event({"type": "error", "message": "Max iterations reached"})
        return "Max iterations reached without a final response."
