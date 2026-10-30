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
manifest: 1
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
"""

WORDS = {lang: Wording("Example", "An example", {"price": "Price", "sellers": "Sellers"}) for lang in ("en", "nl", "fr")}


def test_deed_intake_as_a_manifest_is_the_deed_intake_that_was_code():
    """The snapshot is ``DEED_INTAKE`` as main built it in Python (669e5c6), field for field: the
    file form changes where a playbook lives, not what it is. The run record and the model prompt
    stay byte-identical, so a run made before this change reads the same after it."""
    old = json.loads((FIXTURES / "deed-intake-1.0.json").read_text(encoding="utf-8"))
    new = json.loads(json.dumps(dataclasses.asdict(DEED_INTAKE)))  # tuples to lists, as the snapshot has them
    assert new == old


def test_a_minimal_manifest_loads():
    m = parse(MINIMAL)
    p = m.to_playbook(WORDS)
    assert p.id == "playbook/be-notary/example" and p.slug == "example" and p.version == "1.0"
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
        ("manifest: 1\n", "", "'manifest' must be 1"),                                  # the format version is required
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
    with pytest.raises(ManifestError, match="'manifest' must be 1.*got 2"):
        parse(MINIMAL.replace("manifest: 1", "manifest: 2"), where="x.yaml")


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
