"""Entry point: `uv run suveryn-gateway` (host/port via SUVERYN_HOST / SUVERYN_PORT)."""

import os

import uvicorn


def run() -> None:
    uvicorn.run(
        "suveryn_api_gateway.app:app",
        host=os.environ.get("SUVERYN_HOST", "127.0.0.1"),
        port=int(os.environ.get("SUVERYN_PORT", "8000")),
    )
