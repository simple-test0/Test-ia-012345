import json
import logging
from collections.abc import Callable

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.ollama_base_url

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning(f"Ollama not reachable: {exc}")
            return []

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """Non-streaming chat. Returns the assistant message dict, which may
        contain a `tool_calls` list when the model decides to call tools."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("message", {}) or {}

    async def stream_chat(
        self,
        model: str,
        messages: list[dict],
        on_token: Callable[[str], None] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Streaming chat returning the full assembled response.

        Each token is also forwarded to `on_token` as it arrives. This is the
        foundation for token-by-token streaming to the agent UI (see the
        backend↔frontend parity doc); the WS layer already emits `token` events.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        full_response = ""
        async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token:
                    full_response += token
                    if on_token:
                        on_token(token)
                if chunk.get("done"):
                    break
        return full_response


ollama_client = OllamaClient()
