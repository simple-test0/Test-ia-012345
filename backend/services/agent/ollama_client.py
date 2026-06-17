"""Async Ollama client with a shared, pooled HTTP connection.

A single ``httpx.AsyncClient`` is reused across requests (keep-alive connection
pooling) instead of opening a fresh TCP/TLS connection per call, which both
removes per-request overhead and avoids socket exhaustion under load.
"""

import json
import logging
from typing import Callable, List, Optional

import httpx
from core.config import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        # Lazily create so the client is bound to the running event loop.
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(120.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def list_models(self) -> List[str]:
        try:
            resp = await self._get_client().get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except httpx.HTTPError as exc:
            logger.warning("Ollama /api/tags failed: %s", exc)
            return []

    async def is_available(self) -> bool:
        try:
            resp = await self._get_client().get("/api/tags", timeout=3.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def stream_chat(
        self,
        model: str,
        messages: List[dict],
        on_token: Optional[Callable[[str], None]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
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
        client = self._get_client()
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipping non-JSON stream line: %r", line[:120])
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
