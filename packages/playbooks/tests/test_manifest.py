"""The manifest loader (``suveryn_playbooks.manifest``): what it accepts, what it refuses and how
it says so, and that deed intake as a manifest is the deed intake that was code."""

import dataclasses
import json
from pathlib import Path

import pytest
from suveryn_playbooks import DEED_INTAKE, Wording
from suveryn_playbooks.manifest import ManifestError, json_schema, load, parse, table_scaffold

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


def test_deed_intake_1_1_reads_what_1_0_read_and_tells_the_model_the_same():
    """The snapshot is ``DEED_INTAKE`` 1.0 as main built it in Python (669e5c6). 1.1 added the routine
    (format 2): the facts, their wording and the model's instructions are 1.0's, byte for byte, so a
    run made under 1.0 reads the same and the model is asked the same question. What is new is the
    version, the steps and the questions."""
    old = json.loads((FIXTURES / "deed-intake-1.0.json").read_text(encoding="utf-8"))
    new = json.loads(json.dumps(dataclasses.asdict(DEED_INTAKE)))  # tuples to lists, as the snapshot has them
    assert new["version"] == "1.1" and old["version"] == "1.0" and new["format"] == 2
    for k in ("id", "pack", "name", "case_types", "facts", "instructions"):
        assert new[k] == old[k], k
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
        ("manifest: 2", "manifest: 1", "'manifest' must be 2 (the format this product reads); got 1"),
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
    assert p.instructions == "Read the excerpts and fill in the table.\n\n" + table_scaffold(p.facts)
    assert p.instructions.endswith("| id | value | source |\n|---|---|---|\n| price | | |\n| sellers | | |\n")
    assert p.wording("nl").title == "Example" and p.wording("de") is p.wording("en")


def test_load_reads_the_packs_wording_beside_the_file():
    p = load(PACK / "deed-intake.yaml")
    assert p.id == DEED_INTAKE.id and set(p.text) == {"en", "nl", "fr"}
    assert p.text["nl"].labels["price"] and p.text["fr"].title


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("manifest: 2\n", "", "'manifest' must be 2"),                                            # the format version is required
        ("id: playbook/be-notary/example", "id: playbook/be-lawyer/example", "does not belong to pack"),
        ('version: "1.0"', 'version: "1"', "version: String should match pattern"),
        ("case_types: [sale]", "case_types: [sale, sale]", "listed twice"),
        ("case_types: [sale]", "case_types: [Sale]", "lower-case letters"),
        ("  - id: sellers\n    ask: who sells\n", "  - id: price\n    ask: again\n", "fact 'price' is listed twice"),
        ("    kind: amount\n", "    kind: money\n", "kind: Input should be 'text', 'amount' or 'date'"),
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
    with pytest.raises(ManifestError, match="'manifest' must be 2.*got 3"):
        parse(MINIMAL.replace("manifest: 2", "manifest: 3"), where="x.yaml")


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
