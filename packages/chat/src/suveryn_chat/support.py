"""Does the cited source say it? A check of every citation marker against its own passage (suveryn-tracker#11).

``unverified_figures`` (calc.py) already flags figures that are in *no* passage. This module checks
the citations themselves: for each claim in the answer, the concrete facts in it must be in the
passages it cites, not merely somewhere in the documents. A claim is the text from the previous
marker group (or the start of the sentence) up to a marker group such as ``[2]`` or ``[1][3]``.

Facts checked, deterministically and without another model call:
- **figures**: amounts and other numbers with a separator or of 5+ digits (as ``unverified_figures``),
  compared by value ("410.000" matches "410.000,00"); figures that are a calculation's result, or in
  no passage at all (already reported), are skipped;
- **dates**: numeric (12/03/2021) and written (12 maart 2021, 12 mars 2021, 12 March 2021), compared as
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
import unicodedata
from decimal import Decimal

from suveryn_engine import Calculation, Citation, CitationIssue

from .calc import DATE, TEXT_FIGURE, _value, source_decimal_separator

GROUP = re.compile(r"(?:\[\d{1,2}\])+")
BOLD = re.compile(r"\*\*[^*]+\*\*")
ONE = re.compile(r"\[(\d{1,2})\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
WORD = re.compile(r"[^\W\d_][\w'’-]*")
MONTHS = {m: i for i, names in enumerate([
    ("januari", "janvier", "january", "jan"), ("februari", "février", "fevrier", "february", "feb"),
    ("maart", "mars", "march", "mrt"), ("april", "avril", "apr"), ("mei", "mai", "may"), ("juni", "juin", "june"),
    ("juli", "juillet", "july"), ("augustus", "août", "aout", "august", "aug"),
    ("september", "septembre", "sep", "sept"), ("oktober", "octobre", "october", "okt", "oct"),
    ("november", "novembre", "nov"), ("december", "décembre", "decembre", "dec")], 1) for m in names}
WRITTEN_DATE = re.compile(r"\b(\d{1,2})(?:e|er|ste|de)?\s+([^\W\d_]{3,})\.?\s+(\d{4})\b", re.IGNORECASE)
MIN_NAME = 4
YEAR = re.compile(r"(?<![\d.,/-])(?:1[89]|20)\d\d(?![\d.,/-]\d)")


def _fold(text: str) -> str:
    """Lower case without accents, for comparing words."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _dates(text: str) -> set[tuple[int, int, int]]:
    out = set()
    for m in DATE.finditer(text):
        d, mo, y = (int(x) for x in re.split(r"[./-]", m.group(0)))
        out.add((d, mo, y + 2000 if y < 100 else y))
    for m in WRITTEN_DATE.finditer(text):
        if (mo := MONTHS.get(_fold(m.group(2)))) is not None:
            out.add((int(m.group(1)), mo, int(m.group(3))))
    return out


def _figures(text: str, sep: str) -> dict[Decimal, str]:
    """Figures worth checking, by value, as written. Dates are taken out first."""
    text = WRITTEN_DATE.sub(" ", DATE.sub(" ", text))
    out = {}
    for f in TEXT_FIGURE.findall(text):
        if not re.search(r"[.,  ]", f) and len(f) < 5:
            continue  # article numbers, counts, years: too ambiguous to check
        if (v := _value(f, sep)) is not None:
            out.setdefault(v, f)
    return out


def _words(text: str) -> set[str]:
    return {_fold(w) for w in WORD.findall(text)}


def _names(claim: str, sentence_start: bool, lowercase_in_sources: set[str]) -> list[tuple[str, bool]]:
    """Capitalised words in the claim that the passages never write in lower case, each with whether
    it opens the sentence (then it may just be a capitalised common word: see ``citation_issues``)."""
    out: list[tuple[str, bool]] = []
    for i, m in enumerate(WORD.finditer(claim)):
        w = m.group(0)
        if len(w) < MIN_NAME or not w[0].isupper() or _fold(w) in MONTHS:
            continue
        if _fold(w) not in lowercase_in_sources and w not in (x for x, _ in out):
            out.append((w, i == 0 and sentence_start))
    return out


def _near(word: str, vocabulary: set[str]) -> str | None:
    """A word in the passages one edit away (two for long words), with the same first letter."""
    w = _fold(word)
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
    for sentence in SENTENCE_END.split(answer):
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
    sep = source_decimal_separator(everything)
    computed = {v for c in calculations if c.result for v in _figures(c.result, sep)}
    figures = [set(_figures(t, sep)) for t in texts]
    dates = [_dates(t) for t in texts]
    words = [_words(t) for t in texts]
    years = [set(YEAR.findall(t)) for t in texts]
    vocabulary = set().union(*words)
    lowercase = {_fold(w) for w in WORD.findall(everything) if w[0].islower()}
    for c in calculations:  # the shown "a + b = c" isn't a claim about the sources
        if c.result is not None:
            answer = answer.replace(f"{c.expression} = {c.result}", " ")

    issues: list[CitationIssue] = []
    for claim, sentence_start, cited, first in _claims(answer, len(citations)):
        if not cited:
            continue
        found: list[tuple[str, list[int], str | None]] = []
        for value, written in _figures(claim, sep).items():
            if value in computed or not any(value in f for f in figures):
                continue  # a calculation's result, or in no passage (unverified_figures reports those)
            if not _in_cited(figures, value, cited):
                found.append((written, _elsewhere(figures, value, cited), None))
        for year in sorted(set(YEAR.findall(WRITTEN_DATE.sub(" ", DATE.sub(" ", claim))))):
            if not _in_cited(years, year, cited):
                found.append((year, _elsewhere(years, year, cited), None))
        for d in _dates(claim):
            if not _in_cited(dates, d, cited):
                found.append((_written_date(claim, d), _elsewhere(dates, d, cited), None))
        # Bold text is the model's own label ("**Kettingbeding en Bodemrapport**: …"), not a fact from the
        # source: its words aren't checked as names (figures and dates in bold still are). Seen on the pod.
        for name, opens_sentence in _names(BOLD.sub(" ", claim), sentence_start, lowercase):
            key = _fold(name)
            if _in_cited(words, key, cited):
                continue
            if key in vocabulary:
                found.append((name, _elsewhere(words, key, cited), None))
            elif not opens_sentence and (near := _near(name, vocabulary)) is not None:
                spelled = next(w for w in WORD.findall(everything) if _fold(w) == near)
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
    for m in DATE.finditer(claim):
        if _dates(m.group(0)) == {d}:
            return m.group(0)
    for m in WRITTEN_DATE.finditer(claim):
        if _dates(m.group(0)) == {d}:
            return m.group(0)
    return f"{d[0]}/{d[1]}/{d[2]}"
