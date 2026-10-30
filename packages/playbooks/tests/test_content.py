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
            assert set(words.labels) == {f.id for f in p.facts} and all(v.strip() for v in words.labels.values()), lang
        assert all(f"| {f.id} | | |" in p.instructions for f in p.facts)
        # the routine's questions are the pack's words too: every request and ask step has them in every language
        for step in p.steps:
            if step.kind == "request":
                assert all(p.text[lang].question(step.id).strip() for lang in LANGUAGES), step.id
            if step.kind == "ask":
                assert all(p.text[lang].question(step.id, f).strip() != p.text[lang].labels[f] for lang in LANGUAGES for f in step.facts), step.id


def test_deed_intake_fits_a_sale_and_is_covered():
    p = by_slug("deed-intake")
    assert p is not None and p.id == "playbook/be-notary/deed-intake" and p.pack == "pack/be-notary"
    assert for_case_type("sale") == [p] and for_case_type("estate") == []
    assert find(p.id) is p and covered(p.id) and not covered("playbook/be-notary/nothing")
    assert len(p.facts) == 13 and p.version == "1.1" and [s.kind for s in p.steps] == ["request", "read", "ask", "checkpoint", "produce"]


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
