"""A person's words for a choice become its option (Runtime.normalise): in the run's language, in any other
language the pack has, or as the id; anything else is no value. Without a database: the runtime's method alone."""

from suveryn_api_gateway.playbook_runtime import Runtime
from suveryn_playbooks import by_slug


def test_a_choice_is_normalised_from_its_words_in_any_language_or_its_id():
    p = by_slug("company-formation")  # the fictional test pack (conftest.py)
    runtime = Runtime(store=None, documents=None, uploaded=None)  # type: ignore[arg-type]
    for given, lang, expected in (("In cash", "nl", "cash"), ("in geld", "nl", "cash"), ("En nature", "nl", "in_kind"), ("mixed", "fr", "mixed"),
                                  ("In kind", "en", "in_kind"), ("gold bars", "nl", ""), ("", "nl", "")):
        assert runtime.normalise(p, "contribution_kind", given, lang) == expected, (given, lang)
    assert runtime.normalise(p, "seat", "  Sint-Jansvest 18  ", "nl") == "Sint-Jansvest 18"  # other kinds pass as written
