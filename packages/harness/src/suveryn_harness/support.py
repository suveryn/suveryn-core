"""Does the source say it? Two checks of an answer against its passages, read through ``values`` (the one reader of
amounts, numbers and dates, so a check and the source marking can't disagree).

``unverified_figures`` flags figures that are in *no* passage and no calculation made (suveryn-tracker#11).
``citation_issues`` checks the citations themselves: for each claim in the answer, the concrete facts in it must be in the
passages it cites, not merely somewhere in the documents. A claim is the text from the previous
marker group (or the start of the sentence) up to a marker group such as ``[2]`` or ``[1][3]``.

Facts checked, deterministically and without another model call:
- **figures**: amounts and other numbers with a separator, of 5+ digits, with a scale word ("1,2 miljoen") or
  in words from a thousand (as ``unverified_figures``), compared by value ("410.000" matches "410.000,00");
  figures that are a calculation's result, or in no passage at all (already reported), are skipped;
- **dates**: however written (12/03/2021, 2021-03-12, 12 maart 2021, March 12, 2021, in words), compared as
  day, month and year;
- **years** on their own (1800-2099): a cited year must be in the cited passage, also inside a date
  there ("1989" in "12 maart 1989"). Unlike other four-digit numbers (article numbers, counts), a year
  is a fact a reader checks; one in no passage at all is reported too, as nothing else reports it;
- **names**: capitalised words (outside the model's **bold labels**) that the passages only ever write capitalised (so "Artikel" in a passage
  that also says "artikel" is a common word, not a name). A name in no passage at all is reported only
  when a passage has a near spelling ("Peters" for "Peeters"): the benchmark saw models misspell
  names, while translated words in an English answer about a Dutch deed are not near spellings.

The result lists, per marker occurrence (the k-th valid marker in the answer, as the chat UI counts),
the facts its passages don't contain and which other given passages do. What this can't see: a claim
whose words are all in the passage but whose meaning isn't ("mag niet" for "mag"). Answers still say
"check the source"; this makes the obvious mismatches visible.
"""

import re
from decimal import Decimal

from .marking import answer_sentences, cited_style
from .schemas import Calculation, Citation, CitationIssue
from .values import MONTHS, PERCENT_SIGN, Found, Style, decimal_style, fold, read

GROUP = re.compile(r"(?:\[\d{1,2}\])+")
BOLD = re.compile(r"\*\*[^*]+\*\*")
ONE = re.compile(r"\[(\d{1,2})\]")
WORD = re.compile(r"[^\W\d_][\w'’-]*")
MIN_NAME = 4
YEAR = re.compile(r"(?<![\d.,/-])(?:1[89]|20)\d\d(?![\d.,/-]\d)")


def _dates(text: str) -> set[tuple[int, int, int]]:
    return {f.value for f in read(text) if f.kind == "date"}


def _worth_checking(f: Found, text: str) -> bool:
    """A figure worth checking: with a separator or a scale word ("410.000", "6.507,11", "12,5", "1,2 miljoen"), of
    five digits or more, or written in words from a thousand or followed by euro. Plain numbers up to four digits
    (plot 1, page 57, the year 2026, a count) are left alone: they are rarely amounts, and flagging them would bury
    the real warnings."""
    if f.kind != "number":
        return False
    if f.words:
        return f.value >= 1000 or f.currency
    figure = PERCENT_SIGN.sub("", text[f.start:f.end]) if f.percent else text[f.start:f.end]  # "10 %" is a short figure
    return bool(re.search(r"[.,\s\u00a0\u202f]", figure)) or f.value >= 10000


def _figures(text: str, style: Style = None) -> dict[Decimal, str]:
    """Figures worth checking, by value, as written (dates aren't figures)."""
    out: dict[Decimal, str] = {}
    for f in read(text, style):
        if _worth_checking(f, text):
            out.setdefault(f.value, text[f.start:f.end])
    return out


def _years(text: str) -> set[str]:
    """Years on their own: those outside a date."""
    for f in reversed([f for f in read(text) if f.kind in ("date", "month")]):
        text = text[:f.start] + " " * (f.end - f.start) + text[f.end:]
    return set(YEAR.findall(text))


MARKERS = re.compile(r"\[\d{1,2}\]")


def unverified_figures(answer: str, calculations: list[Calculation], source: str, asked: str = "", style: Style = None) -> list[str]:
    """Figures in the answer text that are neither in the passages nor computed by the system.

    The model must not calculate itself (it writes ``[[calc: …]]``); a figure that appears in no
    passage and is no calculation's result is one it worked out or made up, and the reader must
    check it. Values are compared, not text: "410.000" matches "410.000,00" in a passage. Figures
    the user wrote in the question (``asked``) count as given. Shown calculations ("a + b = c") and
    citation markers are skipped. Returns the figures as the answer writes them, in order, once each.
    """
    style = style or decimal_style(source)
    known = {f.value for text in (source, asked, *(c.result or "" for c in calculations))
             for f in read(text, style) if f.kind == "number"}
    for c in calculations:
        shown = f"{c.expression} = {c.result}" if c.result is not None else f"[calculation not possible: {c.expression}]"
        answer = answer.replace(shown, " ")
    answer = MARKERS.sub(" ", answer)
    out: list[str] = []
    for f in read(answer, style):
        written = answer[f.start:f.end]
        if _worth_checking(f, answer) and f.value not in known and written not in out:
            out.append(written)
    return out


def _words(text: str) -> set[str]:
    return {fold(w) for w in WORD.findall(text)}


def _names(claim: str, sentence_start: bool, lowercase_in_sources: set[str]) -> list[tuple[str, bool]]:
    """Capitalised words in the claim that the passages never write in lower case, each with whether
    it opens the sentence (then it may just be a capitalised common word: see ``citation_issues``)."""
    out: list[tuple[str, bool]] = []
    for i, m in enumerate(WORD.finditer(claim)):
        w = m.group(0)
        if len(w) < MIN_NAME or not w[0].isupper() or fold(w) in MONTHS:
            continue
        if fold(w) not in lowercase_in_sources and w not in (x for x, _ in out):
            out.append((w, i == 0 and sentence_start))
    return out


def _near(word: str, vocabulary: set[str]) -> str | None:
    """A word in the passages one edit away (two for long words), with the same first letter."""
    w = fold(word)
    limit = 1 if len(w) < 9 else 2
    for v in vocabulary:
        if v[:1] == w[:1] and abs(len(v) - len(w)) <= limit and v != w and _distance(v, w, limit) <= limit:
            return v
    return None


def _distance(a: str, b: str, limit: int) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _claims(answer: str, available: int):
    """(claim text, is sentence start, marker numbers, index of the group's first valid marker)."""
    occurrence = 0
    # The same sentences as the source card's marking (marking.py): "art. 3" doesn't end one.
    for sentence in answer_sentences(answer):
        start = 0
        for g in GROUP.finditer(sentence):
            numbers = [int(n) for n in ONE.findall(g.group(0))]
            valid = [n for n in numbers if 1 <= n <= available]
            yield sentence[start:g.start()], start == 0, valid, occurrence
            occurrence += len(valid)
            start = g.end()


def citation_issues(answer: str, citations: list[Citation], calculations: list[Calculation]) -> list[CitationIssue]:
    """Facts in the answer that the passages its markers cite don't contain. See the module docstring."""
    if not citations:
        return []
    texts = [c.text for c in citations]
    everything = "\n".join(texts)
    style = cited_style(citations)
    computed = {v for c in calculations if c.result for v in _figures(c.result, style)}
    figures = [set(_figures(t, style)) for t in texts]
    dates = [_dates(t) for t in texts]
    words = [_words(t) for t in texts]
    years = [set(YEAR.findall(t)) for t in texts]
    vocabulary = set().union(*words)
    lowercase = {fold(w) for w in WORD.findall(everything) if w[0].islower()}
    for c in calculations:  # the shown "a + b = c" isn't a claim about the sources
        if c.result is not None:
            answer = answer.replace(f"{c.expression} = {c.result}", " ")

    issues: list[CitationIssue] = []
    for claim, sentence_start, cited, first in _claims(answer, len(citations)):
        if not cited:
            continue
        found: list[tuple[str, list[int], str | None]] = []
        for value, written in _figures(claim, style).items():
            if value in computed or not any(value in f for f in figures):
                continue  # a calculation's result, or in no passage (unverified_figures reports those)
            if not _in_cited(figures, value, cited):
                found.append((written, _elsewhere(figures, value, cited), None))
        for year in sorted(_years(claim)):
            if not _in_cited(years, year, cited):
                found.append((year, _elsewhere(years, year, cited), None))
        for d in _dates(claim):
            if not _in_cited(dates, d, cited):
                found.append((_written_date(claim, d), _elsewhere(dates, d, cited), None))
        # Bold text is the model's own label ("**Kettingbeding en Bodemrapport**: …"), not a fact from the
        # source: its words aren't checked as names (figures and dates in bold still are). Seen on the pod.
        for name, opens_sentence in _names(BOLD.sub(" ", claim), sentence_start, lowercase):
            key = fold(name)
            if _in_cited(words, key, cited):
                continue
            if key in vocabulary:
                found.append((name, _elsewhere(words, key, cited), None))
            elif not opens_sentence and (near := _near(name, vocabulary)) is not None:
                spelled = next(w for w in WORD.findall(everything) if fold(w) == near)
                found.append((name, [n for n in range(1, len(texts) + 1) if near in words[n - 1]], spelled))
        if not found:
            continue
        k = first
        for n in cited:
            for item, other, spelled in found:
                issues.append(CitationIssue(marker=k, n=n, item=item, found_in=other, written_as=spelled))
            k += 1
    return issues


def _in_cited(per_source: list, item, cited: list[int]) -> bool:
    return any(item in per_source[n - 1] for n in cited)


def _elsewhere(per_source: list, item, cited: list[int]) -> list[int]:
    """The other given passages (1-based) that contain ``item``."""
    return [n for n in range(1, len(per_source) + 1) if n not in cited and item in per_source[n - 1]]


def _written_date(claim: str, d: tuple[int, int, int]) -> str:
    return next((claim[f.start:f.end] for f in read(claim) if f.kind == "date" and f.value == d), f"{d[0]}/{d[1]}/{d[2]}")
