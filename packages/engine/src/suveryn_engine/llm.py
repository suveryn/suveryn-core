"""Async client for an OpenAI-compatible llama.cpp server (llama-server).

The model server is a separate runtime (installed by suveryn-appliance); this client only
talks HTTP to it. Nothing here is specific to one model: Qwen3.8-27B is the default and
Mistral Small 3.2 24B works unchanged, because the served model is read from the server.

Data handling: prompts and answers pass through this client but are never logged or stored
here. Error messages may include up to 200 characters of the backend's error body (llama-server
error texts, e.g. "context size exceeded"), which the gateway passes on to the caller.
"""

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
    """Result of a health probe; ``status`` is "ok", "loading", "error" or "unreachable"."""

    reachable: bool
    status: str
    model: str | None = None
    detail: str | None = None  # exception class or HTTP status, never request content


@dataclass
class StreamChunk:
    """One parsed server-sent event from llama-server: a piece of text, the finish reason, or usage."""

    text: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None


class LlamaServerClient:
    """Talks to one llama-server instance.

    ``transport`` exists for tests: they inject an ``httpx.MockTransport`` instead of a real
    server. One instance is shared by the whole gateway (it holds a connection pool).
    """

    def __init__(self, settings: LLMSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_s, connect=5.0),
            transport=transport,
        )
        self._model: str | None = None

    async def aclose(self) -> None:
        """Close the connection pool (called when the gateway shuts down)."""
        await self._http.aclose()

    async def health(self) -> BackendHealth:
        """Probe ``/health``. Never raises: an unreachable server is a status, not an error.

        llama-server answers 503 while it is still loading the model, which can take tens of
        seconds after a start; that is reported as "loading" rather than as a failure.
        """
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
        """Name of the model llama-server is serving, e.g. 'Qwen3.8-27B-UD-Q4_K_M.gguf'.

        Cached after the first successful lookup. Falls back to ``settings.default_model`` if
        the server can't be asked, so a response always names a model.
        """
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
            # Reuse the cached prompt prefix across turns: a follow-up question on the same
            # document was ~6x faster in the benchmark (document text first, question last).
            # The cache lives in llama-server's GPU and RAM memory and contains personal data;
            # its retention/encryption is an open design item (development context §11.5).
            "cache_prompt": True,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def complete(self, req: ChatRequest) -> ChatResponse:
        """Ask for a whole answer at once. Raises ``BackendError`` if the server fails."""
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
        """Yield the answer as it is generated.

        Text chunks come first; the finish reason and token usage arrive in the last events.
        Raises ``BackendError`` on connection failures or a non-200 response, possibly after
        some text has already been yielded; the caller must handle a partial answer.
        """
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
