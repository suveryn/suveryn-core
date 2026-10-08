"""Async client for an OpenAI-compatible llama.cpp server (llama-server)."""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath

import httpx

from .config import LLMSettings
from .schemas import ChatRequest, ChatResponse, Usage


class BackendError(RuntimeError):
    """The model backend is unreachable or returned an error."""


@dataclass
class BackendHealth:
    reachable: bool
    status: str  # "ok", "loading" or "unreachable"
    model: str | None = None
    detail: str | None = None


@dataclass
class StreamChunk:
    text: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None


class LlamaServerClient:
    def __init__(self, settings: LLMSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_s, connect=5.0),
            transport=transport,
        )
        self._model: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> BackendHealth:
        try:
            r = await self._http.get("/health", timeout=5.0)
        except httpx.HTTPError as e:
            return BackendHealth(reachable=False, status="unreachable", detail=type(e).__name__)
        if r.status_code == 503:
            return BackendHealth(reachable=True, status="loading")
        if r.status_code != 200:
            return BackendHealth(reachable=True, status="error", detail=f"HTTP {r.status_code}")
        return BackendHealth(reachable=True, status="ok", model=await self.model_name())

    async def model_name(self) -> str:
        """Name of the model llama-server is serving, e.g. 'Qwen3.8-27B-UD-Q4_K_M.gguf'."""
        if self._model is None:
            try:
                r = await self._http.get("/v1/models", timeout=5.0)
                r.raise_for_status()
                # llama-server reports the model file path; expose only the file name.
                self._model = PurePosixPath(r.json()["data"][0]["id"]).name
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                return self.settings.default_model
        return self._model

    def _payload(self, req: ChatRequest, stream: bool) -> dict:
        payload = {
            "messages": [m.model_dump() for m in req.messages],
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "stream": stream,
            # Reuse the cached prompt prefix across turns (document text first, question last).
            "cache_prompt": True,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def complete(self, req: ChatRequest) -> ChatResponse:
        try:
            r = await self._http.post("/v1/chat/completions", json=self._payload(req, stream=False))
        except httpx.HTTPError as e:
            raise BackendError(f"model backend unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            raise BackendError(f"model backend returned HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        choice = d["choices"][0]
        u = d.get("usage") or {}
        return ChatResponse(
            id=d.get("id") or f"chat-{uuid.uuid4().hex}",
            model=await self.model_name(),
            answer=choice["message"].get("content") or "",
            finish_reason=choice.get("finish_reason"),
            usage=Usage(prompt_tokens=u.get("prompt_tokens", 0), completion_tokens=u.get("completion_tokens", 0)),
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamChunk]:
        try:
            async with self._http.stream("POST", "/v1/chat/completions", json=self._payload(req, stream=True)) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")
                    raise BackendError(f"model backend returned HTTP {r.status_code}: {body[:200]}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    d = json.loads(data)
                    chunk = StreamChunk()
                    if d.get("choices"):
                        c = d["choices"][0]
                        chunk.text = (c.get("delta") or {}).get("content") or ""
                        chunk.finish_reason = c.get("finish_reason")
                    if d.get("usage"):
                        u = d["usage"]
                        chunk.usage = Usage(prompt_tokens=u.get("prompt_tokens", 0),
                                            completion_tokens=u.get("completion_tokens", 0))
                    if chunk.text or chunk.finish_reason or chunk.usage:
                        yield chunk
        except httpx.HTTPError as e:
            raise BackendError(f"model backend unreachable: {type(e).__name__}") from e
