"""A stand-in for llama-server, for the end-to-end stack (e2e/README.md).

It speaks what ``suveryn_harness.llm.LlamaServerClient`` expects of a llama-server in router mode: ``/health``,
``/models`` (two presets, one loaded), ``/v1/models``, and ``POST /v1/chat/completions`` as one answer or as
server-sent events with ``timings`` and a final ``usage``. No model runs: the answer is made from the prompt
itself, so the stack is deterministic and needs no GPU, and still exercises everything around the model: the
grounded prompt, citations checked against their passages, the facts a playbook reads, thinking.

How it answers (``answer_for``):

- A playbook's read (the request carries the facts' JSON Schema, ``response_format``; the question spells the
  shape): the JSON object, one key per fact, each value a sentence of an excerpt that mentions the fact's keyword
  (``KEYWORDS``), citing that excerpt; a fact without a keyword in any excerpt is null, as the instructions ask, so
  the routine asks a person; a list is [] (the stub names no entries).
- A grounded question: the first sentence of the excerpt that shares most words with the question, cited; with
  no excerpts, a sentence saying the documents don't say.
- Thinking asked for (``chat_template_kwargs.enable_thinking``): a short ``reasoning_content`` before the answer.

Test hooks, for the lifecycle and error scenarios, by a word in the question:

- ``e2e:think-too-long``: with thinking on, reasoning only, no answer, ``finish_reason: length``; asked again without
  thinking (as the harness does), a normal answer.
- ``e2e:slow``: the answer arrives after ``E2E_STUB_SLOW_S`` seconds (default 20), for stop and cancel.
- ``e2e:error``: HTTP 500 with a llama-server-like error body.

Everything the stub receives is a test fixture's text; nothing is logged but the request's shape.

    uv run python e2e/llama_stub.py        # E2E_STUB_PORT (default 8080)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger("e2e.llama_stub")

MODELS = [
    {"id": "qwen3.8-27b", "loaded": True},        # the default (LLMSettings.default_model), thinks
    {"id": "mistral-small-3.2-24b", "loaded": False},
]

# A fact's keyword in the documents the stack uploads (the fictional trap deed is Dutch); matched case-insensitively
# against each excerpt's sentences. Facts without a keyword here, or whose keyword no excerpt has, are "not found".
KEYWORDS = {
    "sellers": ["verkoper"],              # a plain fact (a manifest that keeps the parties as text)
    "sellers.name": ["verkoper"],         # a list's field (deed intake 1.3): one entry, with that field
    "buyers": ["koper "],
    "buyers.name": ["koper "],
    "property": ["bedrijfspand", "het verkochte"],
    "cadastral": ["kadastraal"],
    "price": ["koopprijs bedraagt"],
    "conditions": ["ontbindende voorwaarde"],
    "conditions.condition": ["ontbindende voorwaarde"],
    "occupancy": ["huurder"],
}

_SHAPE = re.compile(r'^  "([a-z_][a-z0-9_]*)": (\{"value": <|\[)', re.MULTILINE)   # the answer's shape, as the loader spells it
_FIELD = re.compile(r'^      "([a-z_][a-z0-9_]*)": \{"value": <', re.MULTILINE)      # a list entry's fields, six spaces in
_EXCERPT = re.compile(r"^\[(\d{1,2})\] \((.*?)\)\n(.*?)(?=\n\n\[\d{1,2}\] \(|\n\n\(The excerpts above|\Z)", re.MULTILINE | re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])|\n+")  # a full stop inside "1.275.000,00" is not an end
_WORD = re.compile(r"\w{4,}", re.UNICODE)

app = FastAPI()


def excerpts(prompt: str) -> list[tuple[int, str]]:
    """The numbered excerpts in a grounded prompt: (n, text)."""
    return [(int(m.group(1)), m.group(3).strip()) for m in _EXCERPT.finditer(prompt)]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s and s.strip()]


def sentence_with(text: str, keyword: str) -> str | None:
    for s in sentences(text):
        if keyword.lower() in s.lower():
            return s.strip()
    return None


def leaf_for(key: str, passages: list[tuple[int, str]]) -> dict:
    """``{"value", "sources"}`` for a fact or a list's field: the first sentence with one of its keywords."""
    for keyword in KEYWORDS.get(key, []):
        for n, text in passages:
            if (s := sentence_with(text, keyword)) is not None:
                return {"value": s, "sources": [n]}
    return {"value": None, "sources": []}


def facts_json(facts: list[tuple[str, list[str] | None]], passages: list[tuple[int, str]]) -> str:
    """The answer in the facts' shape: ``(id, fields)`` per fact, in order; ``fields`` is None for a plain fact,
    the entry's field ids for a list of entries, ``[]`` for a list of plain values. A list gets one entry when
    any of its fields has a keyword in the passages, else it is empty."""
    out: dict = {}
    for fact, fields in facts:
        if fields is None:
            out[fact] = leaf_for(fact, passages)
        elif fields:
            entry = {f: leaf_for(f"{fact}.{f}", passages) for f in fields}
            out[fact] = [entry] if any(v["value"] for v in entry.values()) else []
        else:
            out[fact] = []
    return json.dumps(out, ensure_ascii=False)


def shape_of(question: str) -> list[tuple[str, list[str] | None]]:
    """The facts the answer's shape names, each with its entry's fields when it is a list."""
    out: list[tuple[str, list[str] | None]] = []
    starts = list(_SHAPE.finditer(question))
    for i, m in enumerate(starts):
        if m.group(2) != "[":
            out.append((m.group(1), None))
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else len(question)
        out.append((m.group(1), _FIELD.findall(question[m.end():end])))
    return out


def grounded_answer(question: str, passages: list[tuple[int, str]]) -> str:
    if not passages:
        return "De documenten vermelden dit niet."
    words = {w.lower() for w in _WORD.findall(question)}
    best = max(passages, key=lambda p: len(words & {w.lower() for w in _WORD.findall(p[1])}))
    n, text = best
    for s in sentences(text):
        if words & {w.lower() for w in _WORD.findall(s)}:
            return f"{s} [{n}]"
    return f"{(sentences(text) or [text[:200]])[0]} [{n}]"


def answer_for(messages: list[dict]) -> tuple[str, str]:
    """(reasoning, answer) for the request's messages. The last user message carries the question."""
    prompt = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    passages = excerpts(prompt)
    question = prompt.rsplit("QUESTION:", 1)[-1].strip()
    facts = shape_of(question)
    if facts:
        return "Reading the excerpts for each fact in turn.", facts_json(facts, passages)
    return "Looking for the excerpt that answers the question.", grounded_answer(question, passages)


def tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/models")
async def models():
    return {"data": [{"id": m["id"], "status": {"value": "loaded" if m["loaded"] else "unloaded"}} for m in MODELS]}


@app.get("/v1/models")
async def v1_models():
    return {"object": "list", "data": [{"id": m["id"], "object": "model"} for m in MODELS]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    model = body.get("model") or MODELS[0]["id"]
    thinking = bool((body.get("chat_template_kwargs") or {}).get("enable_thinking"))
    stream = bool(body.get("stream"))
    question = (messages[-1].get("content", "") if messages else "").lower()
    log.info("completion: model=%s stream=%s thinking=%s messages=%d", model, stream, thinking, len(messages))
    for m in MODELS:
        m["loaded"] = m["id"] == model

    if "e2e:error" in question:
        return JSONResponse({"error": {"code": 500, "message": "e2e: the stub was asked to fail", "type": "server_error"}}, status_code=500)
    if "e2e:slow" in question:
        await asyncio.sleep(float(os.environ.get("E2E_STUB_SLOW_S", "20")))

    reasoning, answer = answer_for(messages)
    finish = "stop"
    if "e2e:think-too-long" in question and thinking:  # asked again without thinking, it answers
        reasoning, answer, finish = "Thinking and thinking without reaching an answer. " * 20, "", "length"
    if not thinking:
        reasoning = ""
    prompt_n = sum(tokens(m.get("content", "")) for m in messages)
    predicted_n = tokens(reasoning) + tokens(answer)
    usage = {"prompt_tokens": prompt_n, "completion_tokens": predicted_n, "total_tokens": prompt_n + predicted_n}
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if not stream:
        message = {"role": "assistant", "content": answer}
        if reasoning:
            message["reasoning_content"] = reasoning
        return {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage}

    async def events() -> AsyncIterator[bytes]:
        def chunk(delta: dict, finish_reason: str | None = None, n: int = 0) -> bytes:
            d = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                 "timings": {"prompt_n": prompt_n, "predicted_n": n}}
            return f"data: {json.dumps(d)}\n\n".encode()

        n = 0
        for piece in re.findall(r"\S+\s*", reasoning):
            n += 1
            yield chunk({"reasoning_content": piece}, n=n)
            await asyncio.sleep(0.005)
        pieces = re.findall(r"\S+\s*|\n", answer)
        for i, piece in enumerate(pieces):
            n += 1
            yield chunk({"content": piece}, finish if i == len(pieces) - 1 else None, n=n)
            await asyncio.sleep(0.005)
        if not pieces:
            yield chunk({}, finish, n=n)
        last = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                "choices": [], "usage": usage, "timings": {"prompt_n": prompt_n, "predicted_n": predicted_n}}
        yield f"data: {json.dumps(last)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_STUB_PORT", "8080")), log_level="warning")
