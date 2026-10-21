"""Thinking before answering (docs/design/sidebar.md §5, *Fast* and *Thorough*).

A model that can think (``llm.can_think``) reasons first when a request asks for it
(``ChatRequest.thinking``). The appliance's presets switch thinking off for speed
(models/manifest.json: ``enable_thinking`` false); a request turns it on for itself through
llama-server's ``chat_template_kwargs``.

llama-server hands the reasoning back apart from the answer, as ``reasoning_content`` (its default
``--reasoning-format``). A server that leaves it in the text writes it between ``<think>`` and
``</think>`` at the start of the answer; ``ThinkSplitter`` takes it out, also when the tags arrive
split over several chunks. Either way the answer the person reads, checks and saves never holds the
reasoning, and the reasoning is never sent back to the model with a later question.

Data handling: the reasoning quotes the documents as the answer does. It is streamed to the person
and saved with their conversation like the answer, never logged.
"""

OPEN, CLOSE = "<think>", "</think>"

# Tokens the reasoning may use on top of the answer's own ``max_tokens``: Qwen3 reasons in about
# 500 to 3,000 tokens on a notarial question, and an answer cut off by its own reasoning is worse
# than a slower one.
THINKING_TOKENS = 4096


class ThinkSplitter:
    """Splits streamed text into reasoning and answer when the reasoning is in the text itself.

    Only a ``<think>`` at the very start (after whitespace) opens reasoning; everything after its
    ``</think>`` is answer. Text that starts any other way is all answer, at once.
    """

    def __init__(self) -> None:
        self._held = ""           # text that may still turn out to be a tag
        self._state = "start"     # start: deciding; reasoning: inside <think>; answer: the rest

    def feed(self, text: str) -> tuple[str, str]:
        """(reasoning, answer) that can be passed on now."""
        self._held += text
        reasoning = answer = ""
        if self._state == "start":
            stripped = self._held.lstrip()
            if stripped.startswith(OPEN):
                self._state, self._held = "reasoning", stripped[len(OPEN):]
            elif OPEN.startswith(stripped):
                return "", ""      # "<thi": wait for more
            else:
                self._state = "answer"
        if self._state == "reasoning":
            if CLOSE in self._held:
                reasoning, self._held = self._held.split(CLOSE, 1)
                self._state, self._held = "answer", self._held.lstrip()
            else:
                keep = _partial_tail(self._held, CLOSE)
                reasoning, self._held = self._held[:len(self._held) - keep], self._held[len(self._held) - keep:]
                return reasoning, ""
        if self._state == "answer":
            answer, self._held = self._held, ""
        return reasoning, answer

    def flush(self) -> tuple[str, str]:
        """What is still held at the end: reasoning never closed stays reasoning."""
        held, self._held = self._held, ""
        if self._state == "reasoning":
            return held, ""
        return "", held.lstrip() if self._state == "start" else held


def _partial_tail(text: str, tag: str) -> int:
    """How many characters at the end of ``text`` could be the start of ``tag``."""
    for n in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-n:]):
            return n
    return 0
