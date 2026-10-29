import json
import logging
from typing import Awaitable, Callable, List, Optional, Union

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

TokenCallback = Callable[[str], Union[None, Awaitable[None]]]


class OllamaClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def _timeout(self) -> httpx.Timeout:
        # Fast connect (Ollama down → fail quickly), generous read (slow models).
        return httpx.Timeout(settings.ollama_timeout, connect=5.0)

    async def list_models(self) -> Optional[List[str]]:
        """Installed model names, or None when Ollama is unreachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning(f"Ollama not reachable: {exc}")
            return None

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
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        on_token: Optional[TokenCallback] = None,
    ) -> dict:
        """Chat call returning the final assistant message dict (which may hold
        a `tool_calls` list).

        With `on_token`, the reply is streamed and each content chunk is passed
        to the callback as it arrives. Older Ollama versions that ignore
        streaming when tools are given just send one chunk — handled the same.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": on_token is not None,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            if on_token is None:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                await _raise_for_status(resp)
                return resp.json().get("message", {}) or {}

            content = ""
            tool_calls: List[dict] = []
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                await _raise_for_status(resp)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    msg = chunk.get("message") or {}
                    token = msg.get("content") or ""
                    if token:
                        content += token
                        result = on_token(token)
                        if result is not None:
                            await result
                    tool_calls.extend(msg.get("tool_calls") or [])
                    if chunk.get("done"):
                        break
            return {"role": "assistant", "content": content, "tool_calls": tool_calls}


async def _raise_for_status(resp: httpx.Response) -> None:
    """Like raise_for_status, but surfaces Ollama's own error text
    (e.g. "model 'x' not found, try pulling it first")."""
    if resp.status_code < 400:
        return
    try:
        await resp.aread()
        detail = resp.json().get("error") or resp.text
    except Exception:
        detail = resp.text if hasattr(resp, "text") else ""
    raise RuntimeError(f"Ollama HTTP {resp.status_code}: {detail}".strip())


ollama_client = OllamaClient()
