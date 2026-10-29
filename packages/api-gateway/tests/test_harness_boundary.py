"""Harness boundary (claude/repo-architecture.md, suveryn-tracker#CI): calling the model and
shaping its prompt and answer is suveryn_harness's job alone (LlamaServerClient, grounded_messages,
every citation checked against its passage). api-gateway, rag and playbooks take that behaviour from
suveryn_harness; none of them talks to llama-server directly or re-implements its client.

This fails if a file outside suveryn_harness references the model server's own endpoints, builds its
settings from scratch, or imports a different model SDK. It does not fail on ordinary httpx use for
other backends (Keycloak, the directory, document fetches): only on the specific signs of a second,
untracked path to the model.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
WATCHED = ["api-gateway/src", "rag/src", "playbooks/src"]

FORBIDDEN = [
    re.compile(r"/v1/chat/completions"),
    re.compile(r"/v1/completions\b"),
    re.compile(r"\bLLMSettings\s*\("),  # harness builds its own settings; everyone else takes a LlamaServerClient
    re.compile(r"^\s*import\s+openai\b", re.MULTILINE),
    re.compile(r"^\s*import\s+anthropic\b", re.MULTILINE),
    re.compile(r"\bllama_cpp\b"),
]


def _python_files(subdir: str) -> list[Path]:
    base = PACKAGES / subdir
    return [p for p in base.rglob("*.py") if "tests" not in p.parts]


def test_nothing_outside_harness_talks_to_the_model_directly():
    offenders = []
    for subdir in WATCHED:
        for path in _python_files(subdir):
            text = path.read_text()
            for pattern in FORBIDDEN:
                if pattern.search(text):
                    offenders.append(f"{path.relative_to(PACKAGES)}: matches {pattern.pattern!r}")
    assert offenders == [], (
        "Model-calling code found outside suveryn_harness:\n" + "\n".join(offenders)
    )
