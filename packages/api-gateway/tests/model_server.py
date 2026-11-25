"""What a fake llama-server answers. The harness asks for every answer as a stream of server-sent events
(suveryn-tracker#270), so a fake answers that way too."""

import json

import httpx

STREAM = {"content-type": "text/event-stream"}


def streamed(text: str, usage: dict | None = None) -> httpx.Response:
    """``text`` as one piece, the finish, and llama-server's token counts when given."""
    events = [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
              {"choices": [{"delta": {}, "finish_reason": "stop"}]},
              *([{"choices": [], "usage": usage}] if usage else [])]
    return httpx.Response(200, text="".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n", headers=STREAM)


def garbled() -> httpx.Response:
    """Answered, and not what an answer looks like."""
    return httpx.Response(200, text="data: {not json\n\n", headers=STREAM)
