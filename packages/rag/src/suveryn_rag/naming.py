"""A question that names one document: "de Franstalige volmacht", "the shareholders' agreement", "les statuts"
(VM regression 03c8f74, question 2; Filip, 1 November 2026).

Asked across a case, such a question searched every document, and a French power of attorney among Dutch
ones was not found: the answer said there was none. When a question names a kind of document (and maybe
its language) and exactly one document in the choice fits, only that one is read, and the answer says so.
When several fit, or none, nothing is narrowed: the search goes on over all of them, as before.

What a document is comes from its file name (notaries and lawyers name files by kind: "Statutenwijziging
2004", "Power of Attorney (FR)", "SHA - Final"); its language from its own first passages. Deterministic,
three languages, a short list of kinds: a question it doesn't recognise is searched as before.
"""

from __future__ import annotations

import re
import unicodedata

# kind -> the ways nl, fr and en name such a document in a question (folded: lower case, no accents). Only
# nouns for the document itself: "warrants" or "de hypotheek" in a question is what it asks about, not which file.
KINDS: dict[str, tuple[str, ...]] = {
    "attorney": ("volmacht", "volmachten", "procuration", "procurations", "power of attorney", "powers of attorney"),
    "care_mandate": ("zorgvolmacht", "mandat de protection", "mandat extrajudiciaire"),
    "statutes": ("statuten", "statutenwijziging", "statuts", "modification des statuts", "articles of association", "statutes"),
    "incorporation": ("oprichtingsakte", "acte constitutif", "acte constitutive", "deed of incorporation"),
    "shareholders": ("aandeelhoudersovereenkomst", "shareholders agreement", "shareholders' agreement", "sha",
                     "convention d'actionnaires", "pacte d'actionnaires"),
    "subscription": ("inschrijvingsovereenkomst", "subscription agreement", "convention de souscription"),
    "warrant": ("warrantovereenkomst", "warrant agreement"),
    "issue": ("uitgifteakte", "akte van uitgifte", "issue deed"),
    "sale": ("compromis", "verkoopovereenkomst", "koopovereenkomst", "sale agreement", "compromis de vente"),
    "mortgage": ("hypotheekakte", "acte d'hypotheque", "mortgage deed"),
    "prospectus": ("prospectus",),
}
# What a file name may say besides: a kind's topic word names the file ("Uitgifte_2150512.pdf").
FILE_WORDS: dict[str, tuple[str, ...]] = {
    "care_mandate": ("zvlm",), "incorporation": ("oprichting", "incorporation", "constitution"),
    "warrant": ("warrant", "warrants"), "issue": ("uitgifte", "emission"), "mortgage": ("hypotheek", "hypotheque", "mortgage"),
    "attorney": ("mandat",),
}
LANGUAGE_WORDS: dict[str, tuple[str, ...]] = {
    "fr": ("franstalig", "franstalige", "frans", "franse", "french", "francais", "francaise", "en francais"),
    "nl": ("nederlandstalig", "nederlandstalige", "nederlands", "nederlandse", "dutch", "neerlandais", "neerlandaise"),
    "en": ("engelstalig", "engelstalige", "engels", "engelse", "english", "anglais", "anglaise"),
}
_FILE_LANGUAGE = {"fr": re.compile(r"[(\[ _-](fr|fra)[)\] _.-]"), "nl": re.compile(r"[(\[ _-](nl|ned)[)\] _.-]"),
                  "en": re.compile(r"[(\[ _-](en|eng)[)\] _.-]")}
_STOPWORDS = {
    "nl": {"het", "een", "van", "dat", "voor", "met", "zijn", "wordt", "niet", "bij", "door", "deze"},
    "fr": {"le", "la", "les", "des", "du", "une", "que", "pour", "par", "est", "aux", "sont", "dans"},
    "en": {"the", "of", "and", "to", "with", "that", "shall", "this", "by", "is", "be", "any"},
}


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _has(text: str, phrase: str) -> bool:
    """Whether a folded text holds the phrase as words (a file name's "_" and "-" count as spaces)."""
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text) is not None


def kinds_in(text: str, in_file_name: bool = False) -> set[str]:
    """The kinds of document a question (or a file name) speaks of. In a file name a kind's word may also sit
    inside a longer one ("Warrantovereenkomst"), unless that longer word is another kind's ("zorgvolmacht")."""
    t = re.sub(r"[_\-.]+", " ", fold(text))
    joined = t.replace(" ", "")
    every = [w for words in (*KINDS.values(), *FILE_WORDS.values()) for w in words]
    found = set()
    for kind, words in KINDS.items():
        for w in (*words, *(FILE_WORDS.get(kind, ()) if in_file_name else ())):
            inside = (in_file_name and len(w) >= 6 and " " not in w and w in joined
                      and not any(w != x and w in x and x in joined for x in every))
            if _has(t, w) or inside:
                found.add(kind)
                break
    return found


def language_in(question: str) -> str | None:
    """A language the question names for the document ("de Franstalige volmacht")."""
    t = fold(question)
    named = {lang for lang, words in LANGUAGE_WORDS.items() if any(_has(t, w) for w in words)}
    return named.pop() if len(named) == 1 else None


def language_of(sample: str, filename: str = "") -> str | None:
    """A document's language: a marker in its file name ("(FR)"), else the most common stopwords in its text."""
    f = f" {fold(filename)} "
    for lang, marker in _FILE_LANGUAGE.items():
        if marker.search(f):
            return lang
    words = re.findall(r"[a-z]+", fold(sample))
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 5 and counts[best] >= 2 * sorted(counts.values())[-2] else None


def named_document(question: str, documents: dict[str, tuple[str, str]]) -> str | None:
    """The one document (id) the question names, from ``documents`` (id -> file name, a sample of its text),
    or None when the question names no kind, or several documents (or none) fit it."""
    asked = kinds_in(question)
    if not asked or len(documents) < 2:
        return None
    candidates = [d for d, (name, _) in documents.items() if kinds_in(name, in_file_name=True) & asked]
    language = language_in(question)
    if language is not None:
        candidates = [d for d in candidates if language_of(documents[d][1], documents[d][0]) == language]
    return candidates[0] if len(candidates) == 1 else None
