from suveryn_playbooks import PLAYBOOKS, by_slug, covered, find, for_case_type


def test_identity_is_the_platforms():
    """docs/design/platform.md, "Identifiers": playbook/<pack>/<name>, the pack separately, the version separate from the id."""
    for p in PLAYBOOKS:
        pack = p.pack.removeprefix("pack/")
        assert p.id == f"playbook/{pack}/{p.slug}" and p.pack.startswith("pack/")
        assert p.version.count(".") == 1 and p.major >= 1
        assert len({f.id for f in p.facts}) == len(p.facts)
        for lang in ("en", "nl", "fr"):
            assert set(p.languages[lang]) == {f.id for f in p.facts}, lang
        assert all(f"| {f.id} | | |" in p.instructions for f in p.facts)


def test_deed_intake_fits_a_sale_and_is_covered():
    p = by_slug("deed-intake")
    assert p is not None and p.id == "playbook/be-notary/deed-intake" and p.pack == "pack/be-notary"
    assert for_case_type("sale") == [p] and for_case_type("estate") == []
    assert find(p.id) is p and covered(p.id) and not covered("playbook/be-notary/nothing")
    assert len(p.facts) == 13
