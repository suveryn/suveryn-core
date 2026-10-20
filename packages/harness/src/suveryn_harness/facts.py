"""Reading a playbook's facts from the model (suveryn-tracker#51, docs/design/playbooks.md).

A playbook run is one grounded model call (``service.ChatService.answer``) with the playbook's own
instructions instead of a question, and no history. The answer must be a Markdown table, one row per
fact, each cell citing the excerpts it comes from as [n]. This module asks for it (``read_playbook``:
once more with a stricter reminder when the answer isn't the table) and reads it (``read_facts``):
each fact's value, the passages it cites, and the same checks as a chat answer (``support``,
``calc.unverified_figures``). Storing runs and the checkpoint where a person confirms every fact are
the gateway's (``suveryn_api_gateway.playbooks``).

Nothing is logged here: the answer and the passages are document text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field
from suveryn_playbooks import Playbook

from .grounding import cited_numbers
from .schemas import ChatMessage, ChatRequest, ChatResponse, Citation
from .support import citation_issues

MAX_VALUE = 2000        # characters of one fact's value, as read or as confirmed
READ_TOKENS = 4096      # the table: thirteen rows with their citations, with room for a verbose conditions row
STRICTER = ("\n\nYour previous answer could not be read as the table. Answer with the table only: the header row, "
            "then exactly one row per fact id, in the order given, with the id copied exactly as written in the "
            "first column. No text before or after the table.")


class Unreadable(Exception):
    """The model's answer wasn't the table, also when asked a second time."""


class FactCitation(BaseModel):
    """A passage a fact was read from: enough to show it later, also after the document is deleted."""

    n: int
    document_id: str
    filename: str
    page: int | None = None
    location: str | None = None
    text: str


class RunFact(BaseModel):
    id: str
    value: str = ""                      # as the model read it, copied from the documents
    citations: list[FactCitation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)   # figures, dates or names not in the cited passages
    found: bool = True                   # False: the model said the documents don't contain it
    confirmed: str | None = None         # what the person confirmed (a correction, the value, or "")


_ROW = re.compile(r"^\s*\|?\s*([^|]+?)\s*\|(.*?)\|(.*?)\|?\s*$")
_MARKER = re.compile(r"\[(\d{1,2})\]")
_NOT_FOUND = re.compile(r"^\s*(-|—|n/?a|none|niet (gevonden|vermeld)|non (trouvé|mentionné)|not (found|mentioned|stated))\s*\.?\s*$", re.IGNORECASE)


def read_facts(playbook: Playbook, response: ChatResponse, filenames: dict[str, str]) -> list[RunFact] | None:
    """The facts in the model's table, in the playbook's order, with their cited passages and the
    check's findings; None if the answer isn't the table (``error: unreadable_answer``).

    The check reuses the chat's, both halves: ``citation_issues`` (a figure, date or name that is in
    a passage but not the cited one) works on the whole answer and reports by marker occurrence, so
    markers are counted here in the same order to map them to facts; ``unverified_figures`` (a figure
    in no passage at all: made up or worked out) is matched to the fact whose value writes it, a
    substring match that can attach a figure to two facts that both write it (tolerable: both get
    the warning, and a person looks at both).

    The first column names the fact: its id as given, or, since a small model sometimes translates
    or paraphrases, its label in any of the playbook's languages (review 2026-10-17). Rows are never
    taken by position: a skipped row would shift every fact after it onto the wrong label, silently,
    which is worse than a run that fails and is started again."""
    citations = response.citations
    rows: dict[str, tuple[str, list[int]]] = {}
    marker_facts: list[str] = []  # which fact the i-th valid marker (in text order) belongs to
    names = _fact_names(playbook)
    for line in response.answer.splitlines():
        m = _ROW.match(line)
        if not m or m.group(1) in ("id",) or set(m.group(2).strip()) <= {"-", ":"}:
            continue
        fact_id, value, source = names.get(_fold(m.group(1))), m.group(2).strip(), m.group(3)
        if fact_id is None or fact_id in rows:
            continue
        # markers in the value cell count first (text order), then the source cell
        numbers = cited_numbers(value, len(citations)) + cited_numbers(source, len(citations))
        marker_facts += [fact_id] * (len(_valid(value, len(citations))) + len(_valid(source, len(citations))))
        rows[fact_id] = (_MARKER.sub("", value).strip(" *_"), list(dict.fromkeys(numbers)))
    if len(rows) < max(1, len(playbook.facts) // 2):
        return None
    issues_by_fact: dict[str, list[str]] = {}
    for issue in citation_issues(response.answer, citations, response.calculations):
        if issue.marker < len(marker_facts):
            issues_by_fact.setdefault(marker_facts[issue.marker], []).append(issue.item)
    for fact_id, (value, _) in rows.items():
        issues_by_fact.setdefault(fact_id, []).extend(u for u in response.unverified_figures if u in value)
    facts = []
    for f in playbook.facts:
        value, numbers = rows.get(f.id, ("", []))
        found = bool(value) and not _NOT_FOUND.match(value)
        cited = [_cite(n, citations[n - 1], filenames) for n in numbers if 0 < n <= len(citations)]
        # a value is kept to MAX_VALUE characters: a fact is a line, not a page; what is cut is still in the passage
        facts.append(RunFact(id=f.id, value=value[:MAX_VALUE] if found else "", citations=cited if found else [],
                             issues=list(dict.fromkeys(issues_by_fact.get(f.id, []))) if found else [], found=found))
    return facts


def _fold(text: str) -> str:
    """A fact's name as the model may write it: case, accents, surrounding marks and spacing ignored."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[\s_*`'\"()-]+", " ", text).strip()


def _fact_names(playbook: Playbook) -> dict[str, str]:
    """Every way the first column may name a fact (id, label in each language, id with spaces) -> id."""
    names = {}
    for f in playbook.facts:
        names[_fold(f.id)] = f.id
        for words in playbook.text.values():
            if f.id in words.labels:
                names[_fold(words.labels[f.id])] = f.id
    return names


def _valid(text: str, available: int) -> list[int]:
    return [int(n) for n in _MARKER.findall(text) if 0 < int(n) <= available]


def _cite(n: int, c: Citation, filenames: dict[str, str]) -> FactCitation:
    s = c.source
    return FactCitation(n=n, document_id=s.document_id if s else "", filename=filenames.get(s.document_id, "") if s else "",
                        page=s.page if s else None, location=s.location if s else None, text=c.text)


async def read_playbook(answer: Callable[[ChatRequest], Awaitable[ChatResponse]], playbook: Playbook, filenames: dict[str, str],
                        case_id: str | None, on_retry: Callable[[int], None] | None = None) -> tuple[list[RunFact], ChatResponse]:
    """Ask the model for the playbook's table over the documents ``filenames`` (id -> file name) and
    read it. An answer that isn't the table is asked for once more, with a stricter reminder (review
    2026-10-17: a small model's most likely failure, and a retry is cheaper than a person's); then
    ``Unreadable``. ``answer`` is the grounded call (the caller binds its user); its errors pass
    through. ``on_retry(attempt)`` is told when an answer couldn't be read."""
    for attempt, instructions in enumerate((playbook.instructions, playbook.instructions + STRICTER)):
        req = ChatRequest(messages=[ChatMessage(role="user", content=instructions)], document_ids=list(filenames),
                          case_id=case_id, max_tokens=READ_TOKENS)
        response = await answer(req)
        facts = read_facts(playbook, response, filenames)
        if facts is not None:
            return facts, response
        if on_retry is not None:
            on_retry(attempt + 1)
    raise Unreadable
