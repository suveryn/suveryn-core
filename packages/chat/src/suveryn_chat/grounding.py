"""Prompt assembly for answers grounded in retrieved passages, and citation-marker parsing.

The model receives the passages as numbered excerpts and must cite each statement as [n].
The answer's ``citations`` list holds the same passages in the same order, so marker [n] in
the text refers to ``citations[n - 1]``. That positional contract is what the chat UI uses to
link a marker to its source page.

Prompt order follows the benchmark: earlier turns, then the excerpts, then the question last,
so llama-server's prompt cache can reuse everything before the question.
"""

import re

from suveryn_engine import ChatMessage, Citation

GROUNDED_INSTRUCTIONS = (
    "You are the assistant of a notarial office. Answer only from the numbered excerpts of the "
    "office's own documents below. After every statement, name, number, amount or date, cite the "
    "excerpt it comes from as [1], [2] and so on; cite several as [1][3]. Copy names, numbers and "
    "dates exactly as they are written in the excerpts. Do not calculate new figures. If the "
    "excerpts do not contain the answer, say so plainly instead of guessing. Answer in the "
    "language of the question, concisely."
)

_MARKER = re.compile(r"\[(\d{1,2})\]")


def excerpt_block(citations: list[Citation], filenames: list[str]) -> str:
    """The numbered excerpts, each headed by its file name and position."""
    parts = []
    for n, (c, name) in enumerate(zip(citations, filenames, strict=True), 1):
        where = c.source.location if c.source and c.source.location else "position unknown"
        parts.append(f"[{n}] ({name}, {where})\n{c.text.strip()}")
    return "\n\n".join(parts)


# Tells the model what the excerpts cover, so it can answer general questions about a whole
# document, and knows that "not found" means "not in the passages selected" when it is a selection.
SCOPE_COMPLETE = "EXCERPTS (the complete text of the documents, in reading order):"
SCOPE_SELECTED = "EXCERPTS (the passages of the documents that best match the question; not the whole text):"


def grounded_messages(history: list[ChatMessage], question: str, citations: list[Citation],
                      filenames: list[str], complete: bool = False) -> list[ChatMessage]:
    """Messages for a grounded answer: instructions, earlier turns, then excerpts and the question.

    ``complete`` says the excerpts are the documents' whole text rather than a search selection.
    """
    excerpts = excerpt_block(citations, filenames) if citations else "(no matching passages were found)"
    scope = SCOPE_COMPLETE if complete else SCOPE_SELECTED
    return [ChatMessage(role="system", content=GROUNDED_INSTRUCTIONS), *history,
            ChatMessage(role="user", content=f"{scope}\n{excerpts}\n\nQUESTION: {question}")]


def cited_numbers(answer: str, available: int) -> list[int]:
    """Marker numbers used in the answer that refer to an existing excerpt, in order of first use."""
    seen: list[int] = []
    for m in _MARKER.finditer(answer):
        n = int(m.group(1))
        if 1 <= n <= available and n not in seen:
            seen.append(n)
    return seen
