"""What the model reads of a conversation before a new question: its earlier questions and answers, as the server
stored them (suveryn-tracker#251). Built here, beside the prompt, because everything that goes to the model passes
through the harness; the browser no longer sends it.

Only question-and-answer pairs whose answer completed: a question whose answer failed or was stopped is left out
together with that answer, so roles always alternate user/assistant (several chat templates, Mistral's among them,
reject two user messages in a row). Answers go with their citation markers: the grounded prompt shows them to the
model as [*] (they refer to that answer's passages, not to the new excerpts), so it sees cited answers; stripped, it
copied their uncited style and follow-ups cited nothing. Only the last ``MAX_HISTORY`` messages, and at most
``HISTORY_CHARS`` characters of them, oldest pairs first out: a request holds at most 200 messages and
``MAX_TOTAL_CHARS`` characters, and the question and the documents' passages need room too.
"""

from collections.abc import Iterable

from .schemas import MAX_TOTAL_CHARS, ChatMessage

MAX_HISTORY = 40
HISTORY_CHARS = 60_000


def conversation_history(pairs: Iterable[tuple[str, str | None]], question: str = "") -> list[ChatMessage]:
    """The messages before a new question, from ``pairs`` in order: (a question, its completed answer, or None when
    it has none: failed, stopped, or not written). With the new ``question`` they stay within ``MAX_TOTAL_CHARS``."""
    out: list[tuple[str, str]] = []
    for asked, answer in pairs:
        if answer is not None:
            out += [("user", asked), ("assistant", answer)]
    kept = out[-MAX_HISTORY:]  # an even number: still starts with a question
    chars = sum(len(text) for _, text in kept)
    room = min(HISTORY_CHARS, MAX_TOTAL_CHARS - len(question))
    while kept and chars > room:
        chars -= len(kept[0][1]) + len(kept[1][1])  # a pair at a time: roles keep alternating
        del kept[:2]
    return [ChatMessage(role=role, content=text) for role, text in kept]
