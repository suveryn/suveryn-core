"""Where in a cited passage each claim comes from, for the source card to mark (suveryn-tracker#25, step 2).

The chat UI marked this with its own rules (``packages/chat-ui/src/lib/answer.ts``). The rules now run here,
beside the citation check (``support.py``), which reads the answer's claims with the same sentences
(``answer_sentences``): a marking and a check can't disagree on what a claim is. The UI keeps its copy of the
rules for saved conversations from before, and the two are held to the same cases
(``tests/marking_cases.json``).

Per valid marker (its occurrence, as the UI and ``citation_issues`` count them): the sentences of the cited
passage the claim rests on, and within them the claim's facts however the passage writes them ("12" for
"twelve", "12/03/2021" for "12 March 2021", "1.200.000,00" for "1.2 million"); and anywhere in the passage the
claim's figures, dates and names. Offsets are in UTF-16 code units, as the browser counts.

The word tables (months, number words, abbreviations, words that say nothing) are language data, like the
interface's translation tables.
"""

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from .schemas import Citation, SupportSpan

# ---------------------------------------------------------------------------------------------- facts

LETTER = r"[^\W\d_]"
NOT_AFTER_WORD = r"(?<![^\W_])"  # not after a letter or a digit
NOT_BEFORE_WORD = r"(?![^\W_])"

# A number on its own, not glued to letters ("oyosish4" in OCR noise is no 4). Grouped by . or , or by a (hard)
# space between thousands ("1 250"), not any space ("2021 12" is two numbers).
NUMBER = re.compile(NOT_AFTER_WORD + r"(?:\d{1,3}(?:[   ]\d{3})+(?!\d)|\d+)(?:[.,]\d+)*(?!" + LETTER + ")")

MONTHS: dict[str, int] = {}
for _n, _names in enumerate([
    "januari jan january janvier janv", "februari feb febr february février fevrier févr fév fevr",
    "maart mrt mar march mars", "april apr avril avr", "mei may mai", "juni jun june juin",
    "juli jul july juillet juil", "augustus aug august août aout", "september sep sept septembre",
    "oktober okt october oct octobre", "november nov novembre", "december dec décembre decembre déc"], 1):
    for _name in _names.split():
        MONTHS[_name] = _n
MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"

# Words for numbers on their own. "een", "un", "une" and "one" are left out: mostly articles ("a"), not counts.
NUMBER_WORDS: dict[str, int] = {}
for _words, _values in [
    ("nul één twee drie vier vijf zes zeven acht negen tien elf twaalf dertien veertien vijftien zestien zeventien "
     "achttien negentien", range(20)),
    ("zéro zero", [0, 0]),
    ("deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize", range(2, 17)),
    ("two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
     "eighteen nineteen", range(2, 20)),
    ("twintig dertig veertig vijftig zestig zeventig tachtig negentig", range(20, 100, 10)),
    ("vingt trente quarante cinquante soixante septante huitante octante nonante", [20, 30, 40, 50, 60, 70, 80, 80, 90]),
    ("twenty thirty forty fifty sixty seventy eighty ninety", range(20, 100, 10)),
    ("honderd hundred duizend mille thousand", [100, 100, 1000, 1000, 1000]),
]:
    NUMBER_WORDS.update(zip(_words.split(), _values))
DUTCH_UNITS = {"een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9}
DUTCH_COMPOUND = re.compile(r"^(een|één|twee|drie|vier|vijf|zes|zeven|acht|negen)(?:en|ën)"
                            r"(twintig|dertig|veertig|vijftig|zestig|zeventig|tachtig|negentig)$")
# Parts of a hyphenated number ("vingt-et-un", "quatre-vingt-dix", "twenty-one"), where "un" and "one" do count.
PARTS = {**NUMBER_WORDS, "un": 1, "une": 1, "one": 1, "vingts": 20}

# Scale words after a number: "1,2 miljoen", "two million", "3 mio".
SCALES = {"duizend": 1e3, "mille": 1e3, "thousand": 1e3, "miljoen": 1e6, "miljoenen": 1e6, "million": 1e6,
          "millions": 1e6, "mio": 1e6, "mln": 1e6, "miljard": 1e9, "milliard": 1e9, "milliards": 1e9,
          "billion": 1e9, "mld": 1e9}
SCALE = re.compile(r"[   ]*(" + "|".join(SCALES) + r")\.?(?!" + LETTER + ")", re.IGNORECASE)


@dataclass
class Fact:
    start: int
    end: int
    values: list[str]


def number_value(raw: str) -> float:
    """A written number's value: the last separator is decimal when 1 or 2 digits follow it, or 3 after a lone 0."""
    s = re.sub(r"[   ]", "", raw)
    last = re.match(r"^(.*?)([.,])(\d+)$", s)
    if not last:
        return float(s)
    head, _, tail = last.groups()
    if len(tail) != 3 or head == "0":
        return float(re.sub(r"[.,]", "", head) + "." + tail)
    return float(re.sub(r"[.,]", "", s))


def show(v: float) -> str:
    """As the browser writes it: whole numbers without a decimal point, others to two places at most."""
    if v == int(v):
        return str(int(v))
    r = math.floor(v * 100 + 0.5) / 100
    return str(int(r)) if r == int(r) else repr(r)


def word_value(word: str) -> int | None:
    """A number word's value ("twaalf", "eenentwintig", "vingt-deux", "quatre-vingt-dix", "twenty-one"), or None."""
    w = word.lower()
    if w in NUMBER_WORDS:
        return NUMBER_WORDS[w]
    if m := DUTCH_COMPOUND.match(w):
        return DUTCH_UNITS[m.group(1)] + NUMBER_WORDS[m.group(2)]
    parts = [p for p in re.split(r"[- ]+", w) if p != "et"]
    if len(parts) < 2 or any(p not in PARTS for p in parts):
        return None
    # "quatre-vingt(s)" is 4 × 20; otherwise the parts add up, largest first ("dix-sept", "vingt-et-un").
    if parts[0] == "quatre" and parts[1] in ("vingt", "vingts"):
        values = [80, *(PARTS[p] for p in parts[2:])]
    else:
        values = [PARTS[p] for p in parts]
    if values[0] < 10 or any(v >= values[i] for i, v in enumerate(values[1:])):
        return None
    return sum(values)


def _pad(n: int) -> str:
    return f"{n:02d}"


def _year(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 50 else 1900 + int(y)


def _month(name: str) -> int:
    return MONTHS.get(name.lower().rstrip("."), 0)


def _date(y: int, m: int, d: int) -> list[str] | None:
    if not 1 <= m <= 12 or not 1 <= d <= 31:
        return None
    return [f"d:{y}-{_pad(m)}-{_pad(d)}", f"m:{y}-{_pad(m)}", f"n:{y}"]


def _month_year(m: re.Match) -> list[str] | None:
    mo = _month(m.group(1))
    return [f"m:{m.group(2)}-{_pad(mo)}", f"n:{m.group(2)}"] if mo else None


def _word(m: re.Match) -> list[str] | None:
    v = word_value(m.group(0).replace(" ", "-"))
    return None if v is None else [f"n:{v}"]


DAY = r"(\d{1,2})(?:er|e|de|ste|st|nd|rd|th)?"
PATTERNS = [
    # 2021-03-12
    (re.compile(r"(?<![\d.,/-])(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), lambda m: _date(int(m[1]), int(m[2]), int(m[3]))),
    # 12/03/2021, 12-03-2021, 12.03.2021, 12/03/21
    (re.compile(r"(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?!\d|[.,]\d)"),
     lambda m: _date(_year(m[4]), int(m[3]), int(m[1]))),
    # 12 March 2021, 1er mars 2021
    (re.compile(NOT_AFTER_WORD + DAY + r"\s+(" + MONTH + r")\s+(\d{4})(?!\d)", re.IGNORECASE),
     lambda m: _date(int(m[3]), _month(m[2]), int(m[1]))),
    # March 12, 2021
    (re.compile(NOT_AFTER_WORD + "(" + MONTH + r")\s+" + DAY + r",?\s+(\d{4})(?!\d)", re.IGNORECASE),
     lambda m: _date(int(m[3]), _month(m[1]), int(m[2]))),
    # March 2021
    (re.compile(NOT_AFTER_WORD + "(" + MONTH + r")\s+(\d{4})(?!\d)", re.IGNORECASE), _month_year),
    # 1.275.000,00 and 1 250, with a scale word after them
    (NUMBER, lambda m: [f"n:{show(number_value(m.group(0)))}"]),
    # vingt et un, twelve, vingt-deux, eenentwintig
    (re.compile(NOT_AFTER_WORD + r"(?:(?:vingt|trente|quarante|cinquante|soixante) et (?:un|une|onze)|"
                + LETTER + "+(?:-" + LETTER + "+)*)" + NOT_BEFORE_WORD, re.IGNORECASE), _word),
]


def facts(text: str) -> list[Fact]:
    """The facts of a text with where they are, earlier patterns (dates) before later ones (numbers) where they overlap."""
    out: list[Fact] = []
    for pattern, read in PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(start < f.end and end > f.start for f in out):
                continue
            values = read(m)
            if not values:
                continue
            # "in acht nemen" ("to take into account") is no 8.
            if m.group(0).lower() == "acht" and re.search(r"\bin\s+$", text[max(0, start - 4):start], re.IGNORECASE):
                continue
            if len(values) == 1 and values[0].startswith("n:") and (scale := SCALE.match(text, end)):
                values = [f"n:{show(float(values[0][2:]) * SCALES[scale.group(1).lower()])}"]
                end = scale.end()
            out.append(Fact(start, end, values))
    return sorted(out, key=lambda f: f.start)


def fact_values(text: str) -> set[str]:
    return {v for f in facts(text) for v in f.values}


# ------------------------------------------------------------------------------------------- sentences

# Abbreviations whose full stop doesn't end a sentence. A single capital is an initial ("J. Peeters").
ABBREVIATIONS = set(
    "art artt nr nrs no nos n° bv b.v vb zgn enz e.a e.g i.e cf vgl al par hfst hfdst afd blz p pp ca resp "
    "dhr mevr mr mme mlle me dr prof st ste ir ing lic jr sr vs viz approx fig tab vol "
    "jan feb febr mrt apr jun jul aug sep sept okt oct nov dec".split())
ABBREVIATION = re.compile(r"(?<![^\W\d_])(?<![°.])((?:[^\W\d_]|°)(?:[^\W\d_]|[°.])*)\.\Z")


def abbreviated(text: str, at: int) -> bool:
    """Whether the full stop just before ``at`` closes an abbreviation or an initial rather than a sentence."""
    if at < 1 or text[at - 1] != ".":
        return False
    m = ABBREVIATION.search(text[max(0, at - 40):at])
    if not m:
        return False
    word = m.group(1)
    return word.lower() in ABBREVIATIONS or (len(word) == 1 and word.isupper())


def answer_sentences(text: str) -> list[str]:
    """An answer's sentences: split after . ! ? (not after an abbreviation: "art. 3") and at line ends."""
    out, start = [], 0
    for b in re.finditer(r"(?<=[.!?])\s+|\n+", text):
        if "\n" not in b.group(0) and abbreviated(text, b.start()):
            continue
        out.append(text[start:b.start()])
        start = b.end()
    out.append(text[start:])
    return out


# The ways a passage breaks into sentences, tried in this order at each whitespace (as the browser's one regex).
_AFTER_STOP = re.compile(r"(?<=[.!?;:])\s+")
_BLANK = re.compile(r"\n\s*\n")
_ITEM = re.compile(r"\n(?=\s*(?:[-*•▪]|\d+[.)])\s)")
_PART = re.compile(r"(?<=\S)\s+(?=\d{1,2}\)\s)")
_BEFORE_ROW = re.compile(r"\n(?=[^\n]*[|\t])")
_NEWLINE = re.compile(r"\n")


def _break_at(passage: str, p: int) -> re.Match | None:
    if (m := _AFTER_STOP.match(passage, p)) and m.end() < len(passage):
        c = passage[m.end()]
        if c.isupper() or c.isdigit() or c in "“\"'(":
            return m
    for pattern in (_BLANK, _ITEM, _PART, _BEFORE_ROW):
        if m := pattern.match(passage, p):
            return m
    # after a table row: the line ending here holds | or a tab
    if passage[p] == "\n" and re.search(r"[|\t]", passage[passage.rfind("\n", 0, p) + 1:p]):
        return _NEWLINE.match(passage, p)
    return None


def sentence_ranges(passage: str) -> list[tuple[int, int]]:
    """The passage's sentences as [start, end) ranges: split after . ! ? ; : before a capital, digit or quote (not
    after an abbreviation), at a blank line, before a list item, before a numbered part within a line ("… 11) …
    12) …", as in a form's legend), and around a table row (a line with | or a tab)."""
    out: list[tuple[int, int]] = []
    start = p = 0
    while p < len(passage):
        if not passage[p].isspace() or not (b := _break_at(passage, p)):
            p += 1
            continue
        p = b.end()
        if "\n" not in b.group(0) and abbreviated(passage, b.start()):
            continue
        # "1)" closing a parenthesis opened earlier on the line ("the audit (module 1) yearly") is no numbered part.
        line = passage[passage.rfind("\n", 0, b.start()) + 1:b.start()]
        following = passage[b.end()] if b.end() < len(passage) else ""
        if (re.match(r"^\s+\d", b.group(0) + following) and "\n" not in b.group(0)
                and line.count("(") > line.count(")")):
            continue
        out.append((start, b.start()))
        start = b.end()
    out.append((start, len(passage)))
    return [(a, z) for a, z in out if passage[a:z].strip()]


# --------------------------------------------------------------------------------------- support

# Words that say nothing about which sentence a claim comes from (Dutch, French, English).
STOP = set((
    "de het een en van in op te voor met aan is zijn was werd wordt worden door bij als dat die dit deze om tot "
    "uit naar ook niet maar of er over na hij zij ze we wij u uw hun haar zijn heeft hebben had kan zal zou moet "
    "le la les un une des du et en au aux est sont par pour sur dans que qui avec ce cette ces il elle "
    "the a an and of in on to for with is are was were by as that this these from at it be has have").split())
_HYPHEN = re.compile(r"([^\W\d_])-[ \t]*\n\s*([^\W\d_])")


def _join_hyphens(text: str) -> str:
    return _HYPHEN.sub(lambda m: m.group(1) + m.group(2) if m.group(2).islower() else m.group(0), text)


def tokens(raw: str) -> set[str]:
    """The comparable words (``w:``) and facts (``n:``) of a text: words without line-break hyphens, facts normalised."""
    text = _join_hyphens(raw)
    found = facts(text)
    rest = list(text)
    for f in found:  # the facts' own words ("twelve", "March") count as facts, not words
        rest[f.start:f.end] = " " * (f.end - f.start)
    words = {w for w in re.findall(LETTER + "{3,}", "".join(rest).lower()) if w not in STOP}
    return {f"w:{w}" for w in words} | {f"n:{v}" for f in found for v in f.values}


@lru_cache(maxsize=64)
def _sentences(passage: str) -> tuple[tuple[int, int, frozenset[str]], ...]:
    """A passage's sentences with their tokens, kept for the answer's other markers citing it."""
    return tuple((a, z, frozenset(tokens(passage[a:z]))) for a, z in sentence_ranges(passage))


def _weight(key: str) -> int:
    return 2 if key.startswith("n:") else 1


def supporting_ranges(passage: str, claims: list[str]) -> list[tuple[int, int]]:
    """Where in a passage each claim comes from: the sentences sharing most of the claim's words and facts (a fact
    counts double). A sentence is taken when it holds at least a third of the claim and nearly as much as the best
    sentence (80%). A claim drawn from several sentences: a further sentence is taken when it adds what the taken
    ones don't hold, at least a fact or two words and a quarter of the claim."""
    sentences = _sentences(passage)
    picked: dict[int, list[set[str]]] = {}
    for claim in claims:
        own = sorted(tokens(claim))
        total = sum(_weight(k) for k in own)
        if total < 2:
            continue

        def held(i: int, skip: frozenset[str] = frozenset()) -> int:
            return sum(_weight(k) for k in own if k in sentences[i][2] and k not in skip)

        scores = [held(i) / total for i in range(len(sentences))]
        best = max(scores, default=0)
        if best < 1 / 3:
            continue
        taken = {i for i, s in enumerate(scores) if s >= max(1 / 3, 0.8 * best)}
        for _ in range(2):
            covered = frozenset(k for k in own if any(k in sentences[i][2] for i in taken))
            gains = [0 if i in taken else held(i, covered) for i in range(len(sentences))]
            gain = max(gains, default=0)
            if gain < max(2, total / 4):
                break
            taken.add(gains.index(gain))
        for i in taken:
            picked.setdefault(i, []).append(set(own))
    return [_trim_lines(passage, sentences[i][0], sentences[i][1], picked[i]) for i in sorted(picked)]


def _trim_lines(passage: str, a: int, z: int, claims: list[set[str]]) -> tuple[int, int]:
    """A sentence range without its first and last lines that share nothing with the claims (a heading, noise from a
    figure). A word hyphenated over two lines keeps its lines together."""
    def shares(line: str) -> bool:
        t = tokens(line)
        return any(c & t for c in claims)

    lines: list[list[int]] = []
    for m in re.finditer(r"[^\n]*(?:\n|$)", passage[a:z]):
        s, e = a + m.start(), a + m.end()
        if e <= s:
            continue
        if lines and re.search(r"[^\W\d_]-[ \t]*\n$", passage[lines[-1][0]:lines[-1][1]]) and re.match(r"\s*[^\W\d_]", m.group(0)) \
                and m.group(0).lstrip()[:1].islower():
            lines[-1][1] = e
        else:
            lines.append([s, e])
    i, j = 0, len(lines) - 1
    while i < j and not shares(passage[lines[i][0]:lines[i][1]]):
        i += 1
    while j > i and not shares(passage[lines[j][0]:lines[j][1]]):
        j -= 1
    end = lines[j][1] - 1 if passage[lines[j][0]:lines[j][1]].endswith("\n") else lines[j][1]
    return lines[i][0], end


# ------------------------------------------------------------------------------------------ terms

PARTICLE = r"(?:van|von|de|der|den|het|ter|ten|te|op|in|'t|du|des|le|la|les|di|da|del|della|d'|l')"
NAME_WORD = r"(?:[dDlL]['’])?[A-ZÀ-Þ](?:[^\W\d_]|['’-])+"
NAME = re.compile(NAME_WORD + r"(?:\s+(?:" + PARTICLE + r"\s+)*" + NAME_WORD + ")*")
FIGURE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d+(?:[.,\u00a0\u202f]\d+)+|(?<![A-Za-z0-9_])(?:1[89]|20)\d\d(?![A-Za-z0-9_])|\d{5,}")


def clean_claim(claim: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", claim.replace("**", "")).strip()


def terms_of(raw_claim: str) -> list[str]:
    """The figures, years, dates and names of one claim, to mark anywhere in its passage. Names (with their
    particles: "Eric Van de Plas") only for a claim without numbers."""
    claim = raw_claim.replace("**", "")
    terms = [m.group(0) for m in FIGURE.finditer(claim)]
    if re.search(r"\d", claim):
        return terms
    for m in NAME.finditer(claim):
        text = m.group(0).rstrip("'’")  # a closing quote after a name isn't part of it
        several = bool(re.search(r"\s", text))
        if (several or (m.start() > 0 and len(text) >= 4)) and text not in terms:
            terms.append(text)
        # At the start of a claim the first word may be a title ("Notary Charlotte d'Hondt"): the name without it too.
        rest = re.sub(r"^\S+\s+", "", text, count=1)
        if several and m.start() == 0 and re.search(r"\s", rest) and rest not in terms:
            terms.append(rest)
    return terms


def term_ranges(passage: str, terms: list[str]) -> list[tuple[int, int]]:
    """Where the terms are in the passage: case-insensitive, longest first, a space matching any whitespace."""
    usable = sorted({t for t in terms if len(t.strip()) >= 2 or re.fullmatch(r"\d", t.strip())}, key=len, reverse=True)
    if not usable:
        return []
    alternatives = "|".join(r"\s+".join(re.escape(p) for p in t.split()) for t in usable)
    pattern = re.compile(NOT_AFTER_WORD + "(?:" + alternatives + ")" + NOT_BEFORE_WORD, re.IGNORECASE)
    return [m.span() for m in pattern.finditer(passage)]


# ----------------------------------------------------------------------------------------- spans

def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, z in sorted(ranges):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], z)
        else:
            out.append([a, z])
    return [(a, z) for a, z in out]


def marks(passage: str, claim: str, sentences: list[tuple[int, int]] | None = None,
          ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The supporting sentences of one claim in a passage (``sentences`` when already chosen, by meaning), and the
    facts to mark strongly: in those sentences the claim's facts in any form, anywhere its figures, dates and names
    (also in another form). Code-point offsets."""
    terms = terms_of(claim)
    claim_facts, term_facts = fact_values(claim), {v for t in terms for v in fact_values(t)}
    ranges = supporting_ranges(passage, [claim]) if sentences is None else sentences
    strong = term_ranges(passage, terms)
    for f in facts(passage):
        in_sentence = any(a <= f.start and f.end <= z for a, z in ranges)
        if any(v in term_facts or (in_sentence and v in claim_facts) for v in f.values):
            strong.append((f.start, f.end))
    return _merge(ranges), _merge(strong)


def _utf16(text: str):
    """Code-point offsets of ``text`` to UTF-16 offsets, as JavaScript counts a string."""
    if text.isascii() or all(ord(c) < 0x10000 for c in text):
        return lambda i: i
    prefix = [0]
    for c in text:
        prefix.append(prefix[-1] + (2 if ord(c) >= 0x10000 else 1))
    return lambda i: prefix[i]


GROUP = re.compile(r"(?:\[\d{1,2}\])+")


def marker_claims(answer: str, available: int) -> list[tuple[int, str]]:
    """Per valid marker, in the order the UI numbers them: its source number and the claim before it."""
    out: list[tuple[int, str]] = []
    for sentence in answer_sentences(answer):
        start = 0
        for g in GROUP.finditer(sentence):
            claim = clean_claim(sentence[start:g.start()])
            start = g.end()
            out.extend((n, claim) for n in map(int, re.findall(r"\d{1,2}", g.group(0))) if 1 <= n <= available)
    return out


def support_spans(answer: str, citations: list[Citation], similarities: dict[int, list[float]] | None = None,
                  meaning: "Meaning | None" = None) -> list[SupportSpan]:
    """Per valid marker: what in its cited passage to mark (see the module docstring). ``similarities``: per marker
    occurrence that ``needs_meaning`` listed, its claim's similarity to each sentence of its passage."""
    out: list[SupportSpan] = []
    for occ, (n, claim) in enumerate(marker_claims(answer, len(citations))):
        passage = citations[n - 1].text
        if not claim or not passage:
            continue
        chosen, how = None, "words"
        if similarities and meaning and occ in similarities and (i := meaning.closest(claim, passage, similarities[occ])) is not None:
            a, z, _ = _sentences(passage)[i]
            chosen, how = [(a, z)], "meaning"
        ranges, strong = marks(passage, claim, chosen)
        if not ranges and not strong:
            continue
        at = _utf16(passage)
        out.append(SupportSpan(marker=occ, n=n, ranges=[(at(a), at(z)) for a, z in ranges],
                               facts=[(at(a), at(z)) for a, z in strong], how=how))
    return out


# --------------------------------------------------------------------------------------- meaning

@dataclass(frozen=True)
class Meaning:
    """Marking by meaning (step 3): when no sentence of the passage shares enough of a claim's words and facts (a
    paraphrase: "employer" for "undertaking"; a French source for a Dutch answer), the sentence the embedding model
    finds closest in meaning, when it is close enough (``minimum``), clearly closer than the next (``margin``), and
    holds at least one of the claim's facts if the claim has any. The source card says it was found by meaning."""

    minimum: float
    margin: float = 0.03

    def closest(self, claim: str, passage: str, similarities: list[float]) -> int | None:
        sentences = _sentences(passage)
        if len(similarities) != len(sentences) or not sentences:
            return None
        order = sorted(range(len(sentences)), key=lambda i: -similarities[i])
        best = order[0]
        runner_up = similarities[order[1]] if len(order) > 1 else -1.0
        if similarities[best] < self.minimum or similarities[best] - runner_up < self.margin:
            return None
        claim_facts = {k for k in tokens(claim) if k.startswith("n:")}
        if claim_facts and not claim_facts & sentences[best][2]:
            return None  # a sentence about other figures or dates isn't what the claim rests on
        return best


def needs_meaning(answer: str, citations: list[Citation]) -> list[tuple[int, str, list[str]]]:
    """The markers whose claim no sentence of the cited passage supports by its words and facts, with a claim of three
    words or more: (occurrence, claim, the passage's sentences). Only these are given to the embedding model."""
    out: list[tuple[int, str, list[str]]] = []
    for occ, (n, claim) in enumerate(marker_claims(answer, len(citations))):
        passage = citations[n - 1].text
        if not passage or len(re.findall(LETTER + "{2,}", claim)) < 3 or supporting_ranges(passage, [claim]):
            continue
        out.append((occ, claim, [passage[a:z] for a, z, _ in _sentences(passage)]))
    return out
