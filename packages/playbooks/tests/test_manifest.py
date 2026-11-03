"""The manifest loader (``suveryn_playbooks.manifest``): what it accepts, what it refuses and how
it says so, and that deed intake as a manifest is the deed intake that was code."""

import dataclasses
import json
from pathlib import Path

import pytest
from suveryn_playbooks import DEED_INTAKE, Wording
from suveryn_playbooks.manifest import ManifestError, answer_scaffold, json_schema, load, parse, read_schema

FIXTURES = Path(__file__).parent / "fixtures"
PACK = Path(__file__).parents[1] / "src" / "suveryn_playbooks" / "be_notary"

MINIMAL = """\
manifest: 2
id: playbook/be-notary/example
pack: pack/be-notary
version: "1.0"
name: Example
case_types: [sale]
facts:
  - id: price
    ask: the price
    kind: amount
  - id: sellers
    ask: who sells
instructions: Read the excerpts and fill in the table.
steps:
  - {id: read, kind: read, facts: all}
  - {id: confirm, kind: checkpoint}
  - {id: summary, kind: produce}
"""

WORDS = {lang: Wording("Example", "An example", {"price": "Price", "sellers": "Sellers"}) for lang in ("en", "nl", "fr")}


def test_deed_intake_1_2_reads_what_1_0_read():
    """The snapshot is ``DEED_INTAKE`` 1.0 as main built it in Python (669e5c6). 1.1 added the routine
    (format 2); 1.2 asks for the answer as JSON of the facts' shape instead of a table (format 3). The
    facts and their wording are 1.0's, byte for byte, so a run made under 1.0 reads the same facts; the
    instructions keep 1.0's rules (as written, never guess, the documents' language) and differ only in
    the answer's shape. What is new is the version, the steps and the questions."""
    old = json.loads((FIXTURES / "deed-intake-1.0.json").read_text(encoding="utf-8"))
    new = json.loads(json.dumps(dataclasses.asdict(DEED_INTAKE)))  # tuples to lists, as the snapshot has them
    assert new["version"] == "1.2" and old["version"] == "1.0" and new["format"] == 3
    for k in ("id", "pack", "name", "case_types"):
        assert new[k] == old[k], k
    assert [{k: f[k] for k in ("id", "ask", "kind")} for f in new["facts"]] == old["facts"]
    assert all(f["fields"] == [] and f["item_kind"] == "text" for f in new["facts"])
    for words in ("as the documents write it", "never guess, never fill in from general knowledge", "language of the documents"):
        assert words in old["instructions"] and words in new["instructions"], words
    assert "table" in old["instructions"] and "table" not in new["instructions"].split("Answer with one JSON")[0]
    assert new["instructions"].endswith(answer_scaffold(DEED_INTAKE.facts))
    for lang, words in old["text"].items():
        assert {k: new["text"][lang][k] for k in ("title", "summary", "labels")} == words, lang
    assert [(s["id"], s["kind"]) for s in new["steps"]] == [("agreement", "request"), ("read", "read"), ("missing", "ask"),
                                                            ("confirm", "checkpoint"), ("summary", "produce")]


def test_the_shortest_routine_reads_confirms_and_produces():
    p = parse(MINIMAL).to_playbook(WORDS)
    assert [(s.id, s.kind, s.needs, s.facts) for s in p.steps] == [
        ("read", "read", (), ("price", "sellers")), ("confirm", "checkpoint", ("read",), ()), ("summary", "produce", ("confirm",), ())]
    assert p.step("confirm") is not None and p.step("nothing") is None


STEPS = """\
steps:
  - {id: agreement, kind: request, min: 2, allow_none: true}
  - {id: read, kind: read, facts: all}
  - {id: missing, kind: ask, facts: [price]}
  - {id: confirm, kind: checkpoint}
  - {id: summary, kind: produce}
"""
FORMAT_2 = MINIMAL[:MINIMAL.index("steps:\n")] + STEPS


def test_a_format_2_manifest_resolves_its_steps():
    p = parse(FORMAT_2).to_playbook(WORDS)
    assert p.format == 2
    agreement, read, missing, confirm, summary = p.steps
    assert agreement.kind == "request" and agreement.min == 2 and agreement.allow_none and agreement.needs == ()
    assert read.facts == ("price", "sellers") and read.needs == ("agreement",)   # "all" expanded; needs defaults to the step before
    assert missing.facts == ("price",) and confirm.by == "anyone_in_case" and summary.template == "summary"
    assert summary.needs == ("confirm",)


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("manifest: 2", "manifest: 1", "'manifest' must be 2 or 3 (the format this product reads); got 1"),
        ("  - {id: confirm, kind: checkpoint}\n", "", "needs a checkpoint"),
        ("  - {id: summary, kind: produce}\n", "  - {id: summary, kind: produce, needs: [read]}\n", "nothing is produced before a checkpoint"),
        ("  - {id: missing, kind: ask, facts: [price]}\n", "  - {id: missing, kind: ask, facts: [price], needs: [agreement]}\n", "before any read step it needs reads them"),
        ("  - {id: read, kind: read, facts: all}\n", "  - {id: read, kind: read, facts: [colour]}\n", "fact 'colour' is not one of the playbook's facts"),
        ("  - {id: confirm, kind: checkpoint}\n", "  - {id: confirm, kind: checkpoint, needs: [summary]}\n", "in a circle"),
        ("  - {id: confirm, kind: checkpoint}\n", "  - {id: read, kind: checkpoint}\n", "read listed twice"),
        ("  - {id: agreement, kind: request, min: 2, allow_none: true}\n", "  - {id: agreement, kind: request, facts: all}\n", "facts does not apply to this kind"),
        ("  - {id: read, kind: read, facts: all}\n", "  - {id: read, kind: read}\n", "facts is required"),
        ("  - {id: summary, kind: produce}\n", "  - {id: summary, kind: produce, needs: [nowhere]}\n", "needs 'nowhere', which is not a step"),
    ],
    ids=["format-1-retired", "no-checkpoint", "produce-before-checkpoint", "ask-before-read", "unknown-fact", "cycle",
         "step-twice", "field-of-another-kind", "read-without-facts", "unknown-need"],
)
def test_a_wrong_routine_is_refused_and_the_error_names_the_step(old, new, said):
    text = FORMAT_2.replace(old, new, 1)
    assert text != FORMAT_2
    with pytest.raises(ManifestError) as e:
        parse(text, where="example.yaml")
    assert said in str(e.value), str(e.value)


def test_a_manifest_without_steps_is_refused():
    with pytest.raises(ManifestError, match="steps: Field required"):
        parse(MINIMAL[:MINIMAL.index("steps:\n")])


def test_questions_come_from_the_packs_wording():
    words = Wording("Example", "An example", {"price": "Price", "sellers": "Sellers"},
                    {"agreement": "Upload the agreement.", "missing": "What is {label}?", "missing.sellers": "Who sells?"})
    assert words.question("agreement") == "Upload the agreement."
    assert words.question("missing", "price") == "What is Price?"       # the template, with the label
    assert words.question("missing", "sellers") == "Who sells?"         # the fact's own text wins
    assert words.question("nothing") == "" and words.question("nothing", "price") == "Price"


def test_a_minimal_manifest_loads():
    m = parse(MINIMAL)
    p = m.to_playbook(WORDS)
    assert p.id == "playbook/be-notary/example" and p.slug == "example" and p.version == "1.0" and p.format == 2
    assert [(f.id, f.kind) for f in p.facts] == [("price", "amount"), ("sellers", "text")]
    assert p.instructions == "Read the excerpts and fill in the table.\n\n" + answer_scaffold(p.facts)
    assert p.instructions.endswith('"sources": [<excerpt numbers>]}\n}\nA fact the excerpts do not contain gets "value": null and '
                                   '"sources": []. Every value is a string copied as the documents write it; never a number or a date in another form.')
    assert '  "price": {"value": <the price; copied as written, or null>, "sources": [<excerpt numbers>]},\n  "sellers":' in p.instructions
    assert p.wording("nl").title == "Example" and p.wording("de") is p.wording("en")


def test_load_reads_the_packs_wording_beside_the_file():
    p = load(PACK / "deed-intake.yaml")
    assert p.id == DEED_INTAKE.id and set(p.text) == {"en", "nl", "fr"}
    assert p.text["nl"].labels["price"] and p.text["fr"].title


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("manifest: 2\n", "", "'manifest' must be 2 or 3"),                                            # the format version is required
        ("id: playbook/be-notary/example", "id: playbook/be-lawyer/example", "does not belong to pack"),
        ('version: "1.0"', 'version: "1"', "version: String should match pattern"),
        ("case_types: [sale]", "case_types: [sale, sale]", "listed twice"),
        ("case_types: [sale]", "case_types: [Sale]", "lower-case letters"),
        ("  - id: sellers\n    ask: who sells\n", "  - id: price\n    ask: again\n", "fact 'price' is listed twice"),
        ("    kind: amount\n", "    kind: money\n", "kind: Input should be 'text', 'amount', 'date', 'number' or 'list'"),
        ("name: Example\n", "name: Example\ncolour: blue\n", "colour: Extra inputs are not permitted"),
        ("instructions: Read the excerpts and fill in the table.\n", "", "instructions: Field required"),
        ("    ask: the price\n", '    ask: ""\n', "ask: String should have at least 1 character"),
    ],
    ids=["no-format-version", "id-outside-pack", "bad-version", "case-type-twice", "case-type-case", "fact-twice",
         "unknown-kind", "unknown-key", "no-instructions", "empty-ask"],
)
def test_a_wrong_manifest_is_refused_and_the_error_names_the_field(old, new, said):
    text = MINIMAL.replace(old, new, 1)
    assert text != MINIMAL, "the fixture must actually change"
    with pytest.raises(ManifestError) as e:
        parse(text, where="example.yaml")
    assert "example.yaml" in str(e.value) and said in str(e.value), str(e.value)


def test_not_yaml_and_not_a_mapping_are_refused_plainly():
    with pytest.raises(ManifestError, match="not valid YAML"):
        parse("manifest: [1", where="x.yaml")
    with pytest.raises(ManifestError, match="a manifest is a mapping"):
        parse("- just\n- a list\n", where="x.yaml")
    with pytest.raises(ManifestError, match="'manifest' must be 2 or 3.*got 4"):
        parse(MINIMAL.replace("manifest: 2", "manifest: 4"), where="x.yaml")


# ------------------------------------------------------------------ format 3: numbers and lists

LISTS = MINIMAL.replace("manifest: 2", "manifest: 3").replace("  - id: sellers\n    ask: who sells\n", """  - {id: sellers, ask: the sellers}
  - {id: shares, ask: the number of shares, kind: number}
  - id: founders
    ask: the founders, one entry each
    kind: list
    of:
      - {id: name, ask: the full name}
      - {id: contribution, ask: the contribution, kind: amount}
  - {id: conditions, ask: the conditions, kind: list, of: text}
""")


def test_a_format_3_manifest_has_numbers_and_lists_and_names_their_leaves_by_path():
    p = parse(LISTS).to_playbook(WORDS)
    assert p.format == 3 and [(f.id, f.kind) for f in p.facts] == [("price", "amount"), ("sellers", "text"), ("shares", "number"),
                                                                     ("founders", "list"), ("conditions", "list")]
    founders, conditions = p.fact("founders"), p.fact("conditions")
    assert [(x.id, x.kind) for x in founders.fields] == [("name", "text"), ("contribution", "amount")] and founders.leaf_kind == "text"
    assert conditions.fields == () and conditions.item_kind == "text" and conditions.leaf_kind == "text"
    assert p.leaf("founders[2].contribution") is founders.field("contribution") and p.leaf_kind("founders[2].contribution") == "amount"
    assert p.leaf("conditions[1]") is conditions and p.leaf("shares") is p.fact("shares") and p.leaf_kind("shares") == "number"
    for wrong in ("founders[1]", "founders[1].age", "conditions[1].x", "price[1]", "nobody", "founders[0].name", "founders[99].name"):
        assert p.leaf(wrong) is None and p.leaf_kind(wrong) == "text", wrong
    s = read_schema(p.facts)
    assert s["properties"]["founders"]["items"]["required"] == ["name", "contribution"] and s["properties"]["shares"] == s["properties"]["price"]
    scaffold = answer_scaffold(p.facts)
    assert '"founders": [\n    {\n      "name": {"value": <the full name; copied as written, or null>' in scaffold
    assert "A list (founders, conditions) has one entry per item the documents name" in scaffold


def test_paths_name_one_value_of_a_list():
    from suveryn_playbooks.paths import MAX_ENTRIES, entry, is_path, root, split
    assert split("price") == ("price", None, None) and split("founders[2].name") == ("founders", 2, "name") and split("conditions[1]") == ("conditions", 1, None)
    assert split("founders[0].name") == (None, None, None) and split(f"founders[{MAX_ENTRIES + 1}]") == (None, None, None)
    assert split("Founders[1]") == (None, None, None) and split("") == (None, None, None) and split("a.b") == (None, None, None)
    assert root("founders[2].name") == "founders" and root("price") == "price" and root("not a path") == "not a path"
    assert entry("founders", 2, "name") == "founders[2].name" and entry("conditions", 1) == "conditions[1]"
    assert is_path("founders[2].name") and not is_path("founders[2].")


def test_wording_labels_a_lists_leaves_from_the_lists_and_the_fields_labels():
    w = Wording("Formation", "Reads it", {"founders": "Founder(s)", "founders.name": "Name", "conditions": "Conditions", "price": "Price"},
                {"missing": "The documents don't mention {label}."})
    assert w.label("price") == "Price" and w.label("founders[2].name") == "Founder(s) 2 · Name" and w.label("conditions[1]") == "Conditions 1"
    assert w.label("founders") == "Founder(s)" and w.label("founders[1].age") == "Founder(s) 1 · age" and w.label("nobody") == "nobody"
    assert w.question("missing", "founders[2].name") == "The documents don't mention Founder(s) 2 · Name."


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("manifest: 3", "manifest: 2", "fact 'shares': kind number needs manifest: 3"),
        ("kind: list\n    of:\n      - {id: name, ask: the full name}\n      - {id: contribution, ask: the contribution, kind: amount}\n", "kind: list\n", "kind list needs 'of'"),
        ("kind: number}", "kind: number, of: text}", "'of' only applies to kind list"),
        ("      - {id: contribution, ask: the contribution, kind: amount}\n", "      - {id: name, ask: again}\n", "field name is listed twice"),
        ("kind: list, of: text}", "kind: list, of: colour}", "of"),
        ("      - {id: contribution, ask: the contribution, kind: amount}\n", "      - {id: contribution, ask: the contribution, kind: list}\n", "kind: Input should be 'text', 'amount', 'date' or 'number'"),
    ],
    ids=["format-2-no-lists", "list-without-of", "of-on-a-number", "field-twice", "of-unknown-kind", "no-list-in-a-list"])
def test_a_wrong_list_is_refused_and_the_error_names_the_fact(old, new, said):
    assert old in LISTS, old
    with pytest.raises(ManifestError, match=said):
        parse(LISTS.replace(old, new), where="x.yaml")


def test_missing_wording_is_a_manifest_error(tmp_path):
    (tmp_path / "example.yaml").write_text(MINIMAL, encoding="utf-8")
    with pytest.raises(ManifestError, match="no wording for en"):
        load(tmp_path / "example.yaml")
    (tmp_path / "text").mkdir()
    for lang in ("en", "nl", "fr"):
        (tmp_path / "text" / f"{lang}.json").write_text(json.dumps({"other": {}}), encoding="utf-8")
    with pytest.raises(ManifestError, match="no usable entry for 'example'"):
        load(tmp_path / "example.yaml")


def test_the_published_schema_is_the_models():
    """``schema/playbook-manifest.schema.json`` is generated from ``Manifest``; a change to one
    without the other fails here (regenerate: ``python -m suveryn_playbooks.manifest``)."""
    published = json.loads((Path(__file__).parents[1] / "schema" / "playbook-manifest.schema.json").read_text(encoding="utf-8"))
    assert published == json_schema()


def test_a_playbook_survives_the_record_a_run_keeps():
    """A run keeps the manifest it started under (docs/design/playbooks.md): the loaded playbook written
    out as plain data and read back is the same playbook, lists and words included."""
    import json

    from suveryn_playbooks import PLAYBOOKS, from_record, to_record
    for p in (*PLAYBOOKS, parse(LISTS).to_playbook(WORDS)):
        record = json.loads(json.dumps(to_record(p)))  # as the database hands it back
        assert from_record(record) == p, p.id
    with pytest.raises(KeyError):
        from_record({"id": "playbook/be-notary/x"})


# ------------------------------------------------------------------ documents by name

NAMED = MINIMAL.replace("""  - {id: read, kind: read, facts: all}
""", """  - {id: agreement, kind: request, expects: agreement}
  - {id: title, kind: request, expects: title_deed, allow_none: true}
  - {id: read, kind: read, facts: [price], documents: [agreement]}
  - {id: read_title, kind: read, facts: [sellers], documents: [title_deed]}
""")


def test_a_request_may_be_named_and_a_read_aimed_at_it():
    assert "expects: agreement" in NAMED, MINIMAL
    p = parse(NAMED).to_playbook(WORDS)
    by = {s.id: s for s in p.steps}
    assert by["agreement"].expects == "agreement" and by["title"].expects == "title_deed" and by["title"].allow_none
    assert by["read"].documents == ("agreement",) and by["read_title"].documents == ("title_deed",) and by["read_title"].needs == ("read",)
    assert parse(MINIMAL).to_playbook(WORDS).step("read").documents == ()  # unnamed: every document, as before
    from suveryn_playbooks import from_record, to_record
    assert from_record(to_record(p)) == p


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("expects: title_deed, allow_none: true}", "expects: agreement, allow_none: true}", "agreement is expected by two requests"),
        ("documents: [title_deed]}", "documents: [bank]}", "reads bank, which no request step it needs expects"),
        ("facts: [sellers], documents: [title_deed]}", "facts: [price], documents: [title_deed]}", "fact 'price' is already read by step 'read'; a fact is read once"),
        ("{id: read, kind: read, facts: [price], documents: [agreement]}", "{id: read, kind: read, facts: [price], expects: agreement}", "expects does not apply to this kind"),
    ],
    ids=["expected-twice", "unknown-document", "fact-read-twice", "expects-on-a-read"])
def test_a_wrong_named_document_is_refused_and_the_error_names_the_step(old, new, said):
    assert old in NAMED, old
    with pytest.raises(ManifestError, match=said):
        parse(NAMED.replace(old, new), where="x.yaml")
