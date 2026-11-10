import json
import re
from pathlib import Path

from suveryn_playbooks import (
    LANGUAGES,
    PLAYBOOKS,
    by_slug,
    covered,
    find,
    for_case_type,
)


def test_identity_is_the_platforms():
    """docs/design/platform.md, "Identifiers": playbook/<pack>/<name>, the pack separately, the version separate from the id."""
    for p in PLAYBOOKS:
        pack = p.pack.removeprefix("pack/")
        assert p.id == f"playbook/{pack}/{p.slug}" and p.pack.startswith("pack/")
        assert p.version.count(".") == 1 and int(p.version.split(".")[0]) >= 1
        assert len({f.id for f in p.facts}) == len(p.facts)
        for lang in LANGUAGES:  # every language has the title, the line and a label for every fact
            words = p.text[lang]
            assert words.title.strip() and words.summary.strip(), lang
            wanted = ({f.id for f in p.facts} | {f"{f.id}.{x.id}" for f in p.facts for x in f.fields}
                      | {f"{f.id}.{o}" for f in p.facts for o in f.options})  # a choice's options have words too
            assert set(words.labels) == wanted and all(v.strip() for v in words.labels.values()), lang
        assert all(f'"{f.id}": ' in p.instructions for f in p.facts)  # the answer's shape names every fact
        # the routine's questions are the pack's words too: every request and ask step has them in every language
        for step in p.steps:
            if step.kind == "request":
                assert all(p.text[lang].question(step.id).strip() for lang in LANGUAGES), step.id
            if step.kind == "ask":
                assert all(p.text[lang].question(step.id, f).strip() != p.text[lang].labels[f] for lang in LANGUAGES for f in step.facts), step.id
            if step.kind == "check":  # a sentence saying what holds when it holds, in every language
                assert all(p.text[lang].checks.get(step.id, "").strip() for lang in LANGUAGES), step.id


def test_deed_intake_fits_a_sale_and_is_covered():
    p = by_slug("deed-intake")
    assert p is not None and p.id == "playbook/be-notary/deed-intake" and p.pack == "pack/be-notary"
    assert for_case_type("sale") == [p] and for_case_type("estate") == []
    assert find(p.id) is p and covered(p.id) and not covered("playbook/be-notary/nothing")
    assert len(p.facts) == 13 and p.version == "1.6" and [s.kind for s in p.steps] == [*["request"] * 3, *["read"] * 3, "ask", *["check"] * 5, "checkpoint", "produce"]
    # 1.5: each fact read from the documents that state it; together the reads cover every fact once
    reads = [s for s in p.steps if s.kind == "read"]
    assert [s.documents for s in reads] == [("sale_agreement",), ("sale_agreement", "title_deed"), ("certificates", "sale_agreement")]
    assert sorted(f for s in reads for f in s.facts) == sorted(f.id for f in p.facts)
    assert [(f.id, [x.id for x in f.fields]) for f in p.facts if f.kind == "list"] == [
        ("sellers", ["name", "address", "register"]), ("buyers", ["name", "address", "register"]), ("conditions", ["condition", "term"])]
    assert [s.rule for s in p.steps if s.kind == "check"] == ["count(sellers) >= 1", "count(buyers) >= 1", "deposit <= price",
                                                              "agreement_date < deed_deadline", "latest(conditions.term) <= deed_deadline"]


def test_the_languages_are_the_interfaces():
    """One list of languages (docs/translations.md): the playbooks' and the chat UI's are the same,
    in the same order, and each pack has exactly one words file per language."""
    ui = Path(__file__).parents[2] / "chat-ui" / "src" / "i18n" / "languages.ts"
    listed = re.search(r"export const LANGS = \[([^\]]*)\]", ui.read_text(encoding="utf-8"))
    assert listed and tuple(re.findall(r'"([a-z]{2})"', listed.group(1))) == LANGUAGES
    realm = json.loads((Path(__file__).parents[2] / "api-gateway" / "keycloak" / "suveryn-realm.json").read_text(encoding="utf-8"))
    assert tuple(realm["supportedLocales"]) == LANGUAGES  # the sign-in page offers the same languages
    packs = Path(__file__).parents[1] / "src" / "suveryn_playbooks"
    for text in packs.glob("*/text"):
        assert sorted(f.stem for f in text.glob("*.json")) == sorted(LANGUAGES), text.parent.name


def _texts(value, path=""):
    """Every text in a pack's words file, by its path (``.deed-intake.labels.price``)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _texts(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _texts(v, f"{path}[{i}]")


def test_every_sentence_is_translated():
    """A sentence left in English in another language's words file: the file is there and every label too
    (the tests above), but a text copied from en.json to add a fact and never translated would pass them.
    Short ones may rightly be the same word; four words or more, identical, is untranslated
    (as the chat's src/i18n/untranslated.test.ts)."""
    packs = Path(__file__).parents[1] / "src" / "suveryn_playbooks"
    for english in packs.glob("*/text/en.json"):
        base = dict(_texts(json.loads(english.read_text(encoding="utf-8"))))
        for lang in LANGUAGES:
            if lang == "en":
                continue
            other = english.with_name(f"{lang}.json")
            same = [f"{k}: {s}" for k, s in _texts(json.loads(other.read_text(encoding="utf-8")))
                    if base.get(k) == s and len([w for w in s.split() if re.search(r"[^\W\d_]{2}", w)]) >= 4]
            assert same == [], f"{other.relative_to(packs)} still has English: {same}"
