"""Token usage per model call (suveryn-tracker#7, development context §5.3).

Every call to the model server goes through ``LlamaServerClient``, so usage is captured here,
once, for chat answers, summaries and playbook steps alike. The client hands each call's counts
to a ``UsageRecorder`` (the gateway stores them in PostgreSQL); the engine itself stores nothing.

Only counts are recorded: who (the Keycloak user id), when, which kind of call, which model, and
llama-server's own prompt/completion token counts. Never prompt or answer text. The counts are
informational: nothing limits or slows anyone down because of them.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

Kind = Literal["chat", "summary", "playbook-step"]


@dataclass(frozen=True)
class UsageRecord:
    """One model call's token counts. ``total_tokens`` is prompt plus completion."""

    user: str
    kind: Kind
    model: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# Receives each call's counts. It must not raise; if it does, the error is logged (by type only)
# and the answer is unaffected.
UsageRecorder = Callable[[UsageRecord], Awaitable[None]]
