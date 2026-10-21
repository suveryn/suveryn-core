"""Which of a case's documents a question is about (docs/harness.md, "Focus").

A question asked in a case with nothing attached is given the case's sources (the chat UI's
``lib/questionDocuments.ts``). Searching all of them at once mixed documents: with ten real documents
in one case, 7 of 44 answers cited another document, 4 of them wrongly, and answers took 11 to 17 s
(Pod check of 705b91d). With the one document attached there was no mixing. So such a question is
first narrowed to the documents it is about, and only those are read:

1. **Named.** A document whose file name has a word the question uses ("the lease" for
   ``huurcontract-lease.pdf``), when that word names at most ``MOST`` of the documents. A word in
   every file name ("akte") names none in particular and is ignored.
2. **Ranked.** Otherwise by the search itself: of the ``TOP`` best passages across the documents, each
   counts 1/rank for its document (the best 1, the second 1/2, ...). The best document is kept, and
   any other with at least ``SHARE`` of its weight (two documents of one transaction, both relevant),
   at most ``MOST`` in all, best first.

The chosen documents are then read as before: whole when they fit, else their best passages.
"""

import re
import uuid

from .integrity import norm

TOP = 10      # passages that decide
SHARE = 0.5   # of the best document's weight, to be kept beside it
MOST = 3      # documents at most
MIN_LETTERS = 4


def words(text: str) -> set[str]:
    """Distinctive words: four letters or more, not numbers."""
    return {w for w in re.findall(r"\w+", norm(text)) if len(w) >= MIN_LETTERS and not w.isdigit()}


def named(question: str, filenames: dict[uuid.UUID, str]) -> list[uuid.UUID]:
    """The documents the question names by a word of their file name (its extension left out), when
    the words it uses name at most ``MOST`` of them together; otherwise none."""
    asked = words(question)
    by_word: dict[str, set[uuid.UUID]] = {}
    for doc, name in filenames.items():
        for w in words(re.sub(r"\.\w+$", "", name)):
            by_word.setdefault(w, set()).add(doc)
    hits: set[uuid.UUID] = set()
    for w in asked:
        docs = by_word.get(w, set())
        if 0 < len(docs) < len(filenames):  # a word every file name has names nothing in particular
            hits |= docs
    if not hits or len(hits) > MOST:
        return []
    return [d for d in filenames if d in hits]


def choose(weights: dict[uuid.UUID, float]) -> list[uuid.UUID]:
    """The best document, and the others with at least ``SHARE`` of its weight; at most ``MOST``, best first."""
    if not weights:
        return []
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    best = ranked[0][1]
    return [d for d, w in ranked if w >= SHARE * best][:MOST]
