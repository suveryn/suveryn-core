"""The planted-error benchmark: how many mistakes the answer checks catch, and how many correct answers they flag.

The checks (``support.citation_issues``, ``support.unverified_figures``) were tuned one finding at a time. This
measures them: ``check_cases.json`` holds correct answers on fictional passages; each rule below plants one kind of
mistake in an answer (a figure, a date, a name, a small number, the unit, a "not", the party, the source cited).
A planted mistake is caught when the checks report something for the changed answer; a correct answer that gets a
report is a false alarm. ``check_benchmark.json`` records the result, and ``test_check_benchmark.py`` holds the
checks to it: a change may catch more, never less, and never flag more correct answers.

    python packages/harness/tests/check_benchmark.py            # the table
    python packages/harness/tests/check_benchmark.py --update   # record it, after looking at what changed
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from suveryn_harness.language import NUMBER_WORDS, any_of
from suveryn_harness.marking import cited_style
from suveryn_harness.schemas import Citation, SourceRef
from suveryn_harness.support import citation_issues, unverified_figures

HERE = Path(__file__).parent
CASES = HERE / "check_cases.json"
RECORD = HERE / "check_benchmark.json"

FIGURE = r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d{2})?"
MONTH = any_of(name for table in NUMBER_WORDS.values() for name in table["months_written"])
# What a planted mistake changes, per language of a case: test data about a language, kept with the cases.
PLANT = json.loads(CASES.read_text(encoding="utf-8"))["plant"]
ARTICLE = any_of(word for words in PLANT["article"].values() for word in words)


def _bump(digits: str) -> str:
    return str(int(digits) % 9 + 1) if len(digits) == 1 else str(int(digits) + 1)


def amount(a: str, case: dict) -> str | None:
    """Another amount: the first digit of the first grouped figure changes ("412.500,00" -> "512.500,00")."""
    m = re.search(rf"(?<![\d/.-]){FIGURE}(?![\d/]|\s?m²)", a)
    return a[:m.start()] + _bump(a[m.start()]) + a[m.start() + 1:] if m else None


def date(a: str, case: dict) -> str | None:
    """Another day: "12 oktober 2026" -> "13 oktober 2026", "01/03/2027" -> "02/03/2027"."""
    m = re.search(rf"\b(\d{{1,2}})(?=(?:er)?\s+{MONTH}\s+\d{{4}})|(?<![\d/.-])(\d{{1,2}})(?=[/.-]\d{{1,2}}[/.-]\d{{4}})", a)
    if not m:
        return None
    day = int(m.group(0))
    return a[:m.start()] + f"{day + 1 if day < 28 else day - 1:0{len(m.group(0))}d}" + a[m.end():]


def name(a: str, case: dict) -> str | None:
    """A name misspelled by one letter ("Peeters" -> "Peters")."""
    n = case.get("name")
    if not n or n not in a:
        return None
    return a.replace(n, n[:2] + n[3:] if len(n) > 4 else n[:2] + n[1] + n[2:], 1)  # a short name gets a letter twice


def percentage(a: str, case: dict) -> str | None:
    """Another percentage: "6 %" -> "7 %"."""
    m = re.search(r"(?<![\d.,])(\d{1,2})(?=\s?%)", a)
    return a[:m.start()] + _bump(m.group(1)) + a[m.end():] if m else None


def count(a: str, case: dict) -> str | None:
    """Another small number before a word: "2 kopers" -> "3 kopers", "6 weken" -> "7 weken"."""
    for m in re.finditer(r"(?<![\d\[/.,])\b(\d{1,2})(?=\s+[a-zé])", a):
        before, after = a[max(0, m.start() - 9):m.start()].lower(), a[m.end():]
        if re.search(ARTICLE + r"\s$", before) or re.match(rf"(?:er)?\s+{MONTH}\b", after, re.IGNORECASE):
            continue
        return a[:m.start()] + _bump(m.group(1)) + a[m.end():]
    return None


def article(a: str, case: dict) -> str | None:
    """Another article: "artikel 9" -> "artikel 10"."""
    m = re.search(r"(?i)\b" + ARTICLE + r"\s+(\d+)", a)
    return a[:m.start(1)] + _bump(m.group(1)) + a[m.end(1):] if m else None


def unit(a: str, case: dict) -> str | None:
    """Money told as a surface: "€ 385.000" -> "385.000 m²"."""
    for pattern, repl in ((rf"(?:€|EUR|USD)\s?({FIGURE})", r"\1 m²"), (rf"({FIGURE})\s?(?:EUR|euros?|USD)\b", r"\1 m²")):
        out, n = re.subn(pattern, repl, a, count=1)
        if n:
            return out
    return None


def negation(a: str, case: dict) -> str | None:
    """The opposite: a "not" taken out, or put in after may, must, can ("mag" -> "mag niet")."""
    lang = case["lang"]
    take = PLANT["take_not"][lang]
    out, n = re.subn(take[0], take[1], a, count=1)
    if n:
        return out
    put = PLANT["put_not"][lang]
    out, n = re.subn(put[0], put[1], a, count=1)
    return out if n else None


def party(a: str, case: dict) -> str | None:
    """The other party: koper for verkoper, acheteur for vendeur, buyer for seller."""
    pairs = tuple(PLANT["party"][case["lang"]])
    for x, y in (pairs, pairs[::-1]):
        m = re.search(rf"(?i)(?<![a-zé]){x}", a)
        if m:
            other = y.capitalize() if m.group(0)[0].isupper() else y
            out = a[:m.start()] + other + a[m.end():]
            for wrong, right in PLANT["party_article"].get(case["lang"], []):  # the article follows the word
                out = out.replace(wrong, right)
            return out
    return None


def source(a: str, case: dict) -> str | None:
    """The wrong source cited: [1] for [2] and [2] for [1]."""
    if len(case["passages"]) < 2 or "[1]" not in a or "[2]" not in a:
        return None
    return a.replace("[1]", "[\x00]").replace("[2]", "[1]").replace("[\x00]", "[2]")


# In the order of the report. The first six are facts the checks compare; the last four need more than comparing
# figures, dates and names: what a number measures, what a sentence means, who does what.
RULES = [amount, date, name, source, percentage, count, article, unit, negation, party]


def reports(answer: str, case: dict) -> list[str]:
    """What the checks say about an answer: figures in no passage, and facts their cited passage doesn't hold."""
    citations = [Citation(text=p["text"], source=SourceRef(document_id=f"d{i}", page=1, decimals=p.get("decimals")))
                 for i, p in enumerate(case["passages"])]
    text = "\n".join(c.text for c in citations)
    return [*unverified_figures(answer, [], text, style=cited_style(citations)), *(i.item for i in citation_issues(answer, citations, []))]


def run() -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    out = {"cases": len(cases), "false_alarms": [], "caught": {}, "missed": {}}
    for case in cases:
        if reports(case["answer"], case):
            out["false_alarms"].append(case["answer"])
    for rule in RULES:
        planted = [(case, changed) for case in cases if (changed := rule(case["answer"], case)) and changed != case["answer"]]
        caught = [changed for case, changed in planted if reports(changed, case)]
        out["caught"][rule.__name__] = [len(caught), len(planted)]
        out["missed"][rule.__name__] = [changed for _, changed in planted if changed not in caught]
    return out


def table(result: dict) -> str:
    lines = [f"{result['cases']} correct answers, {len(result['false_alarms'])} flagged (false alarms)"]
    lines += [f"  flagged though correct: {a}" for a in result["false_alarms"]]
    lines.append("planted mistake   caught")
    for rule in RULES:
        caught, planted = result["caught"][rule.__name__]
        lines.append(f"  {rule.__name__:14}  {caught} of {planted}   {(rule.__doc__ or '').split(':')[0].strip()}")
    return "\n".join(lines)


if __name__ == "__main__":
    result = run()
    print(table(result))
    if "--missed" in sys.argv:
        for rule, answers in result["missed"].items():
            for a in answers:
                print(f"  missed ({rule}): {a}")
    if "--update" in sys.argv:
        record = {"_about": "The planted-error benchmark as last recorded (check_benchmark.py --update): per kind of mistake, how many "
                            "the checks caught of how many were planted, and how many correct answers they flagged.",
                  "cases": result["cases"], "false_alarms": len(result["false_alarms"]), "caught": result["caught"]}
        RECORD.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded in {RECORD.name}")
