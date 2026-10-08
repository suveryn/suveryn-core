"""Engine settings, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMSettings:
    # OpenAI-compatible llama.cpp server. In development this is usually an SSH tunnel to the GPU box.
    base_url: str = "http://127.0.0.1:8080"
    # Label used when the backend does not report a model name. The model actually served is
    # whatever llama-server was started with (Qwen3.8-27B by default, Mistral Small 3.2 24B also works).
    default_model: str = "qwen3.8-27b"
    timeout_s: float = 300.0

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(
            base_url=os.environ.get("SUVERYN_LLM_BASE_URL", cls.base_url).rstrip("/"),
            default_model=os.environ.get("SUVERYN_LLM_DEFAULT_MODEL", cls.default_model),
            timeout_s=float(os.environ.get("SUVERYN_LLM_TIMEOUT_S", cls.timeout_s)),
        )
