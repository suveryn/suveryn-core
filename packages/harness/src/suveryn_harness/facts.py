"""Reading a playbook's facts from the model (suveryn-tracker#51, docs/design/playbooks.md).

A playbook run is one grounded model call (``service.ChatService.answer``) with the playbook's own
instructions instead of a question, and no history. The answer is JSON of the facts' shape
(``suveryn_playbooks.read_schema``: per value, what the documents write and the excerpts it comes from
as numbers), which the model server holds the model to by grammar. This module asks for it
(``read_playbook``: once more with a stricter reminder when the answer still can't be read, as when the
server has no grammar support) and reads it (``read_facts``): every value, plain or inside a list's
entries, becomes one ``RunFact`` named by its path (``founders[2].contribution``), with the passages it
cites and the same checks as a chat answer (``support``, ``calc.unverified_figures``), plus the check by
kind: an amount, a date or a number compared by meaning with its cited passage. A list the documents
name no entries of is one not-found fact under the list's own id, so an ask step can ask about it.
Storing runs and the checkpoint where a person confirms every fact are the gateway's
(``suveryn_api_gateway.playbooks``).

Nothing is logged here: the answer and the passages are document text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from suveryn_playbooks import Playbook, entry, read_schema
from suveryn_playbooks.paths import MAX_ENTRIES, root


from .schemas import ChatMessage, ChatRequest, ChatResponse, Citation, PassageContext
from .marking import cited_style
from .identifiers import valid
from .support import _dates, _figures, citation_issues, unverified_figures
from .values import Style, as_date, as_number, first_amount, numbers_in

MAX_VALUE = 2000        # characters of one fact's value, as read or as confirmed
READ_TOKENS = 6144      # the JSON: a dozen values with their sources, with room for a list of parties
STRICTER = ("\n\nYour previous answer could not be read as the JSON object described. Answer with that JSON object only: "
            "every fact id as a key, exactly as written, each with \"value\" and \"sources\"; a list as an array of entries. "
            "No text, no code fence, nothing before or after the object.")


class Unreadable(Exception):
    """The model's answer wasn't the JSON object asked for, also when asked a second time."""


class FactCitation(BaseModel):
    """A passage a fact was read from: enough to show it later, also after the document is deleted."""

    n: int
    document_id: str
    filename: str
    page: int | None = None
    location: str | None = None
    text: str
    context: PassageContext | None = None  # the text around it on its page, for the source panel (board P02)


class FactAlternative(BaseModel):
    """A later document's reading that differs from what a person confirmed (or answered): shown beside it until a
    person chooses at the checkpoint; the confirmed value stands meanwhile (decision of 10 November 2026)."""
    value: str
    citations: list[FactCitation] = Field(default_factory=list)


class RunFact(BaseModel):
    id: str
    value: str = ""                      # as the model read it, copied from the documents
    citations: list[FactCitation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)   # figures, dates or names not in the cited passages
    found: bool = True                   # False: the model said the documents don't contain it
    confirmed: str | None = None         # what the person confirmed (a correction, the value, or "")
    source: Literal["document", "person", "none"] = "document"   # where ``value`` came from: the documents, a person's answer, nowhere
    by: str | None = None                # for a person's value: who gave it (an answer or a correction in the conversation)
    was: str | None = None               # for a correction of a value read from the documents: the value as read
    at: datetime | None = None           # for a person's value: when it was given
    # A date, an amount or a number the value doesn't give as one ("uiterlijk vier maanden na de ondertekening"): a
    # person works it out and checks it (``not_a_date``, ``not_an_amount``, ``not_a_number``; decision, 1 November
    # 2026: *Kijk na* by meaning); an amount the document gives as approximate ("ongeveer € 450.000": ``approximate``).
    needs: str | None = None
    # A value worked out from another fact (``terms``; board P01): ``needs`` is "computed", ``value`` as worked out, and
    # this how. A term: {"written": the term as the agreement writes it, "from": the fact counted from, "base", "date"
    # (ISO), "amount", "unit" (day, week, month, year, workday), "direction" (after, before), and for working days
    # "calendar" (its name per language)}. A share: {"written", "from": the amount it is a share of, "kind": "share",
    # "percent", "of", "amount" (decimal strings)}.
    computed: dict | None = None
    # A document added later reads this fact differently from what is confirmed: both are shown, a person chooses.
    alternative: FactAlternative | None = None


_MARKER = re.compile(r"\[(\d{1,2})\]")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_NOT_FOUND = re.compile(r"^\s*(-|—|n/?a|none|niet (gevonden|vermeld)|non (trouvé|mentionné)|not (found|mentioned|stated))\s*\.?\s*$", re.IGNORECASE)


def read_facts(playbook: Playbook, response: ChatResponse, filenames: dict[str, str],
               fact_ids: set[str] | None = None) -> list[RunFact] | None:
    """The facts in the model's answer, one ``RunFact`` per value in the playbook's order (a list's
    entries in the order given, each field a fact of its own, named by path); None if the answer
    isn't the JSON object asked for (``error: unreadable_answer``). ``fact_ids``: the read step's
    facts; None for all.

    Each value's checks: ``citation_issues`` on the value with its sources as markers (a figure, date or
    name that is in a passage but not the cited one); ``unverified_figures`` (a figure in no passage at
    all: made up or worked out); and the check by kind (``_by_meaning``). A value the model writes as
    "not found" in words, or empty, is not found. Sources the model names that don't exist are
    dropped; a value with no valid source is kept, uncited, for the person to see."""
    data = _json_object(response.answer)
    if data is None:
        return None
    facts = [f for f in playbook.facts if fact_ids is None or f.id in fact_ids]
    if sum(1 for f in facts if f.id in data) < max(1, len(facts) // 2):
        return None  # a JSON object, but not the one asked for
    citations = response.citations
    source = "\n".join(c.text for c in citations)
    style = cited_style(citations)
    out: list[RunFact] = []
    for f in facts:
        raw = data.get(f.id)
        if f.kind != "list":
            out.append(_leaf(f.id, f.leaf_kind, raw, citations, filenames, source, style, f.options, f.format))
            continue
        entries = raw if isinstance(raw, list) else []
        if not entries:
            out.append(RunFact(id=f.id, found=False, source="none"))  # the list as a whole: the documents name none
            continue
        for i, item in enumerate(entries[:MAX_ENTRIES], 1):
            if f.fields:
                record = item if isinstance(item, dict) else {}
                for x in f.fields:
                    out.append(_leaf(entry(f.id, i, x.id), x.kind, record.get(x.id), citations, filenames, source, style,
                                      form=x.format))
            else:
                out.append(_leaf(entry(f.id, i), f.item_kind, item, citations, filenames, source, style))
    return work_out_terms(playbook, out)


def work_out_terms(playbook: Playbook, facts: list[RunFact]) -> list[RunFact]:
    """Values worked out from another fact (``terms``; board P01): a date written as a term ("binnen vier maanden na
    de ondertekening", "binnen tien werkdagen na …", on the pack's calendar) from the date the playbook says it counts
    from (``counts_from``), and an amount written as a percentage ("tien procent van de koopprijs") of the amount it
    is a share of (``share_of``), when that fact was read as such. The fact stays under *Check* (``needs: computed``)
    until a person confirms it; otherwise it stays as written (``not_a_date``, ``not_an_amount``)."""
    from .terms import work_out, work_out_share
    by_id = {f.id: f for f in facts}
    out = []
    for f in facts:
        spec = playbook.leaf(f.id)
        done, source = None, ""
        if spec is not None and spec.counts_from and f.needs == "not_a_date":
            base = by_id.get(spec.counts_from)
            if base is not None and base.found and base.needs is None:
                done, source = work_out(f.value, as_date(base.value), playbook.calendar), spec.counts_from
        elif spec is not None and spec.share_of and f.needs == "not_an_amount":
            base = by_id.get(spec.share_of)
            if base is not None and base.found and base.needs is None:
                done, source = work_out_share(f.value, base.value), spec.share_of
        if done is not None:
            value, how = done
            f = f.model_copy(update={"value": value, "needs": "computed", "computed": {"written": f.value, "from": source, **how}})
        out.append(f)
    return out


def _json_object(answer: str) -> dict | None:
    """The one JSON object in the answer: as is, or inside a code fence, or the outermost braces of
    text around it (a server without grammar support lets the model add words)."""
    import json
    text = answer.strip()
    for candidate in (text, _FENCE.sub("", text).strip()):
        try:
            d = json.loads(candidate)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    a, b = text.find("{"), text.rfind("}")
    if 0 <= a < b:
        try:
            d = json.loads(text[a:b + 1])
            return d if isinstance(d, dict) else None
        except ValueError:
            return None
    return None


def _leaf(path: str, kind: str, raw: object, citations: list[Citation], filenames: dict[str, str], source: str, style: Style,
          options: tuple[str, ...] = (), form: str = "") -> RunFact:
    """One value as the model gave it -> the fact, cited and checked. A choice is one of its options, as the
    schema holds the model to; anything else (a server without grammar support) is not found."""
    if isinstance(raw, dict):
        value, sources = raw.get("value"), raw.get("sources")
    else:
        value, sources = raw, []  # a bare value: tolerated, uncited
    value = str(value).strip() if value is not None and not isinstance(value, (dict, list)) else ""
    numbers = [int(n) for n in (sources if isinstance(sources, list) else []) if isinstance(n, int) and 0 < n <= len(citations)]
    numbers += _valid(value, len(citations))  # markers the model wrote in the value count too
    numbers = list(dict.fromkeys(numbers))
    value = _MARKER.sub("", value).strip(" *_")
    if not value or _NOT_FOUND.match(value):
        return RunFact(id=path, found=False, source="none")
    if kind == "choice":
        value = _option(value, options)
        if value is None:
            return RunFact(id=path, found=False, source="none")
        return RunFact(id=path, value=value, citations=[_cite(n, citations[n - 1], filenames) for n in numbers], found=True, source="document")
    cited = [_cite(n, citations[n - 1], filenames) for n in numbers]
    issues: list[str] = []
    if cited:
        claim = value + " " + "".join(f"[{n}]" for n in numbers)
        issues = [i.item for i in citation_issues(claim, citations, [])]
    issues += [u for u in unverified_figures(value, [], source, style=style) if u not in issues]
    needs = None
    if kind in ("amount", "date", "number"):
        needs, issue = _by_meaning(kind, value, [c.text for c in cited], style)
        if issue and not any(i in value for i in issues):  # unless the check already named its figure or date
            issues.append(issue)
    if form and valid(form, value) is False:
        needs = "invalid_number"  # its check digits don't match: a typo, or a scan's misreading (``identifiers``)
    # a value is kept to MAX_VALUE characters: a fact is a line, not a page; what is cut is still in the passage
    return RunFact(id=path, value=value[:MAX_VALUE], citations=cited, issues=list(dict.fromkeys(issues)), found=True,
                   source="document", needs=needs)


def _by_meaning(kind: str, value: str, passages: list[str], style: Style) -> tuple[str | None, str | None]:
    """A fact of kind amount, date or number compared by what it means, not how it is spelled (decision,
    1 November 2026): "26.800 euro" against "zesentwintigduizend achthonderd euro" agrees; "28.600 euro"
    doesn't (an issue, the value as written); a value that gives no date, amount or number at all ("vier
    maanden na de ondertekening") needs a person to work it out (``needs``). Without cited passages
    nothing is compared. A number is any figure, short ones included ("3 aandelen"), which the chat's
    figure check skips as too ambiguous; here the playbook asked for a count."""
    if kind == "date":
        d = as_date(value)
        if d is None:
            return "not_a_date", None
        if passages and not any(d in _dates(p) for p in passages):
            return None, value
        return None, None
    if kind == "number":
        n = as_number(value, style)
        if n is None:
            return "not_a_number", None
        if passages and not any(n in numbers_in(p, style) for p in passages):
            return None, value
        return None, None
    found = first_amount(value, style)
    if found is None:
        return "not_an_amount", None
    approximate = "approximate" if found.approximate else None  # "ongeveer € 450.000": a person decides what it is
    if passages and not any(found.value in _figures(p, style) for p in passages):
        return approximate, value
    return approximate, None


def _option(value: str, options: tuple[str, ...]) -> str | None:
    """The option a value names: its id, as written or folded ("In kind" -> in_kind); None for anything else."""
    folded = _fold(value).replace(" ", "_")
    return next((o for o in options if o == value or o == folded), None)


def option_of(value: str, options: tuple[str, ...], labels: dict[str, str] | None = None) -> str | None:
    """A person's answer as an option: the id, or the option's label in the given words (folded)."""
    found = _option(value, options)
    if found or not labels:
        return found
    want = _fold(value)
    return next((o for o, label in labels.items() if _fold(label) == want), None)


def _fold(text: str) -> str:
    """A fact's name as the model may write it: case, accents, surrounding marks and spacing ignored."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[\s_*`'\"()-]+", " ", text).strip()


def _valid(text: str, available: int) -> list[int]:
    return [int(n) for n in _MARKER.findall(text) if 0 < int(n) <= available]


def _cite(n: int, c: Citation, filenames: dict[str, str]) -> FactCitation:
    s = c.source
    return FactCitation(n=n, document_id=s.document_id if s else "", filename=filenames.get(s.document_id, "") if s else "",
                        page=s.page if s else None, location=s.location if s else None, text=c.text, context=c.context)


def answer_shape(playbook: Playbook, response: ChatResponse) -> dict[str, int | str | None]:
    """What an answer that couldn't be read looked like, in counts only (it is document text): its
    length and lines, whether it parsed as JSON and how many of the playbook's facts it had as keys,
    and why the model stopped. Enough to tell a missing object from a reshaped one, and a server
    without grammar support from a model that ignored the shape."""
    d = _json_object(response.answer)
    return {"chars": len(response.answer), "lines": len(response.answer.splitlines()),
            "json": d is not None, "keys": len(d) if d else 0,
            "named_keys": sum(1 for f in playbook.facts if d and f.id in d),
            "finish": response.finish_reason, "reasoning_chars": len(response.reasoning or "")}


def search_for(playbook: Playbook, facts) -> str:
    """What a read searches the documents for, when they are longer than one reading takes: each fact's question and
    its label in every language the pack has ("the sale price", "Prijs", "Prix"), and a list's fields the same way. The
    instructions are no search: they name no fact, and in a long file the passages that matched them best were the
    general clauses (the GPU round of 10 November 2026: a 25-page title deed filled the reading, and today's parties
    and price were not seen)."""
    lines: list[str] = []
    for f in facts:
        for fid, ask in ((f.id, f.ask), *((f"{f.id}.{x.id}", x.ask) for x in f.fields)):
            labels = dict.fromkeys(playbook.wording(lang).label(fid) for lang in playbook.text)
            lines.append(" · ".join([ask, *(label for label in labels if label and label != fid)]))
    return "\n".join(lines)[:8000]


async def read_playbook(answer: Callable[[ChatRequest], Awaitable[ChatResponse]], playbook: Playbook, filenames: dict[str, str],
                        case_id: str | None, on_retry: Callable[[int, dict], None] | None = None,
                        fact_ids: set[str] | None = None) -> tuple[list[RunFact], ChatResponse]:
    """Ask the model for the playbook's facts over the documents ``filenames`` (id -> file name) and
    read them. The request carries the answer's schema (``read_schema``), which the server enforces;
    an answer that still can't be read (no grammar support, or an object that isn't the one asked for)
    is asked for once more, with a stricter reminder (review 2026-10-17: a retry is cheaper than a
    person's); then ``Unreadable``. ``answer`` is the grounded call (the caller binds its user); its
    errors pass through. ``on_retry(attempt, shape)`` is told when an answer couldn't be read, with its
    shape (``answer_shape``: counts only). ``fact_ids``: the read step's facts; None for all.

    When the documents were longer than one reading takes (``complete`` False), the facts still not found are
    looked for again, one document at a time in the order given, searched for those facts alone
    (``follow_up``). A fact found stays as found: a later document never replaces it. The response returned
    is the first one (what was read in part), with the passages addressing an AI of every call."""
    wanted = {f.id for f in playbook.facts if fact_ids is None or f.id in fact_ids}
    facts, response = await _read_once(answer, playbook, filenames, case_id, on_retry, wanted)
    if response.complete is not False:
        return facts, response
    suspicious = bool(response.instruction_like_sources)
    for document_id, name in filenames.items():
        missing = {f.id for f in facts if not f.found and "[" not in f.id and "." not in f.id}
        if not missing:
            break
        more, extra = await _read_once(answer, playbook, {document_id: name}, case_id, on_retry, missing)
        found = {root(f.id) for f in more if f.found}
        facts = [f for f in facts if root(f.id) not in found] + [f for f in more if root(f.id) in found]
        suspicious = suspicious or bool(extra.instruction_like_sources)
    order = {f.id: i for i, f in enumerate(playbook.facts)}
    facts.sort(key=lambda f: order.get(root(f.id), len(order)))  # the playbook's order, entries in theirs (a stable sort)
    if suspicious and not response.instruction_like_sources:
        response = response.model_copy(update={"instruction_like_sources": [0]})  # a later call's: shown as one warning
    return facts, response


async def _read_once(answer, playbook: Playbook, filenames: dict[str, str], case_id: str | None, on_retry, wanted: set[str]
                     ) -> tuple[list[RunFact], ChatResponse]:
    """One read: asked, and asked once more with a stricter reminder when the answer can't be read."""
    facts = tuple(f for f in playbook.facts if f.id in wanted)
    schema = read_schema(facts)
    only = "" if len(facts) == len(playbook.facts) else "\n\nThis time only these facts, as keys: " + ", ".join(f.id for f in facts) + "."
    for attempt, instructions in enumerate((playbook.instructions + only, playbook.instructions + only + STRICTER)):
        req = ChatRequest(messages=[ChatMessage(role="user", content=instructions)], document_ids=list(filenames),
                          case_id=case_id, max_tokens=READ_TOKENS, json_schema=schema, search=search_for(playbook, facts))
        response = await answer(req)
        facts_read = read_facts(playbook, response, filenames, None if len(facts) == len(playbook.facts) else wanted)
        if facts_read is not None:
            return facts_read, response
        if on_retry is not None:
            on_retry(attempt + 1, answer_shape(playbook, response))
    raise Unreadable


# ------------------------------------------------------------------ answers in words (docs/design/playbooks.md, "The chat UI")

MAP_TOKENS = 512
_MAPPED = re.compile(r"^\s*[-*]?\s*`?([a-z][a-z0-9_]{0,49}(?:\[\d{1,2}\](?:\.[a-z][a-z0-9_]{0,49})?)?)`?\s*[:=]\s*(.+?)\s*$")
# The model's "no value for any fact": NOTHING, as asked (it was NONE, which a choice's option "none" read like:
# the GPU round's playbook runs, 5 November: "geen aparte vertrouwenspersoon" placed nothing), or NONE as before.
_NOTHING = re.compile(r"^\s*(none|nothing|-)\s*\.?\s*$", re.IGNORECASE)

MAP_INSTRUCTIONS = """A person answered in their own words about facts for a file. Say which of the facts below their
words give a value for, and the value, copied as they wrote it (a date, an amount, a name, a number).

The facts (id: label, and the value as it stands now, if any):
{facts}

The person wrote:
<<<
{text}
>>>

Answer with one line per fact the person gives a value for, as `id: value`, using only the ids above.
For a fact that is a choice, the value is the id of the option their words mean, from its list, even when
that option is "none" (for example `trusted_person: none` for "no trusted person").
A fact the person says is not known yet, or will follow later, is not a value: leave it out.
If their words give no value for any of the facts, answer with the single word NOTHING. Nothing else."""


def map_prompt(labels: dict[str, str], current: dict[str, str], text: str,
               choices: dict[str, dict[str, str]] | None = None) -> str:
    """The mapping's prompt. A choice fact lists its options (id = words), so "kosteloos" can be placed as
    ``unpaid``: with the label alone the model had nothing to place it on (the GPU round's playbook runs,
    5 November 2026: the care mandate's pay and trusted person, answered in words, couldn't be placed)."""
    def line(fid: str, label: str) -> str:
        options = (choices or {}).get(fid)
        listed = f" (a choice; options: {'; '.join(f'{o} = {w}' for o, w in options.items())})" if options else ""
        return f"- {fid}: {label}{listed}" + (f" (now: {current[fid]})" if current.get(fid) else "")
    facts = "\n".join(line(fid, label) for fid, label in labels.items())
    return MAP_INSTRUCTIONS.format(facts=facts, text=text.replace(">>>", "> > >"))


def read_mapping(answer: str, labels: dict[str, str], choices: dict[str, dict[str, str]] | None = None) -> dict[str, str]:
    """The model's ``id: value`` lines, only for the facts asked about; anything else is ignored, so
    an answer the model got wrong places nothing rather than something wrong. A choice's option id is a value
    even when it reads as "nothing" (the trusted person's option ``none``)."""
    out: dict[str, str] = {}
    for line in answer.splitlines():
        if _NOTHING.match(line):
            continue
        m = _MAPPED.match(line)
        option = m and m.group(2).strip().strip("`").lower() in (choices or {}).get(m.group(1), {})
        if m and m.group(1) in labels and (option or not _NOT_FOUND.match(m.group(2))):
            out[m.group(1)] = m.group(2).strip().strip("`")[:MAX_VALUE]
    return out


# "Not known yet" in a person's words, nl, fr and en (folded: lower case, no accents): at the checkpoint the
# mapping leaves such a fact out (MAP_INSTRUCTIONS), so "Bodemattest: nog niet bekend." placed nothing and got
# "that couldn't be placed" (VM regression 03c8f74, finding 8).
_UNKNOWN_WORDS = re.compile(
    r"\b(nog niet (bekend|gekend|beschikbaar|ontvangen)|(nog )?onbekend|niet gekend|volg(t|en) (later|nog)|kom(t|en) later"
    r"|pas encore (connu|connue|disponible|recu|recue)|inconnu|inconnue|suivra|a suivre"
    r"|not (yet )?known|unknown|not available yet|to follow|will follow|tbc|tbd)\b")


def said_unknown(text: str, labels: dict[str, str]) -> list[str]:
    """The facts (ids) a person names by their label and says are not known yet, in the order of ``labels``:
    "Bodemattest: nog niet bekend." -> ["soil_certificate"]. Empty when the words say nothing of the kind, or
    name no fact."""
    t = _fold(text)
    if not _UNKNOWN_WORDS.search(t):
        return []
    return [fid for fid, label in labels.items() if label.strip() and _fold(label) in t]


async def map_answer(answer: Callable[[ChatRequest], Awaitable[ChatResponse]], labels: dict[str, str], current: dict[str, str],
                     text: str, choices: dict[str, dict[str, str]] | None = None) -> tuple[dict[str, str], ChatResponse]:
    """A person's answer in words, mapped to the facts ``labels`` (id -> label) by one plain model call
    (no documents): the values it gives, per fact id. What the model can't place stays out; the caller
    then asks again in words (decision, 31 October 2026). ``answer`` is the call (the caller binds its user).
    ``choices``: for a choice fact, its options (id -> words in the run's language)."""
    req = ChatRequest(messages=[ChatMessage(role="user", content=map_prompt(labels, current, text, choices))], max_tokens=MAP_TOKENS)
    response = await answer(req)
    return read_mapping(response.answer, labels, choices), response
