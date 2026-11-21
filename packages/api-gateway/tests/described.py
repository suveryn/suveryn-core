"""An answer of the gateway against its description (``openapi.json``; suveryn-tracker#159, #236): the chat UI's
code is generated from the description, so what the gateway answers has to be what the description says.

``answer_is_described(response, "POST", "/v1/admin/clock")`` fails when the status isn't one the operation
describes, when the answer is sent as another media type, or when its body isn't the described shape: a member
missing, of another type, or one the description doesn't name.

``Kept`` keeps answers the gateway really gave as a file beside the tests, for the chat UI's tests to answer its
generated code with (``packages/chat-ui/src/api.clock.test.ts``): the two halves are tested on the same answers,
with no server running. The gateway's test fails when the file isn't what it answers today;
``SUVERYN_WRITE_ANSWERS=1 uv run pytest packages/api-gateway/tests`` writes it again.
"""

import copy
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator

from suveryn_api_gateway import description


def _closed(schema):
    """The schema with every object closed: a member the description doesn't name is a failure here, where the
    description itself (pydantic's) lets it pass."""
    if isinstance(schema, dict):
        if "properties" in schema and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        for value in schema.values():
            _closed(value)
    elif isinstance(schema, list):
        for value in schema:
            _closed(value)
    return schema


DESCRIBED = json.loads(description.FILE.read_text(encoding="utf-8"))
COMPONENTS = _closed(copy.deepcopy(DESCRIBED["components"]))


def answer_is_described(response, method: str, path: str) -> None:
    """``path`` as the description writes it (``/v1/admin/clock/{rid}``)."""
    where = f"{method} {path} -> {response.status_code}"
    responses = DESCRIBED["paths"][path][method.lower()]["responses"]
    assert str(response.status_code) in responses, f"{where}: not a status the description gives ({sorted(responses)})"
    content = responses[str(response.status_code)].get("content")
    if not content:
        assert response.content == b"", f"{where}: a body where the description has none"
        return
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    assert media_type in content, f"{where}: sent as {media_type!r}, described as {sorted(content)}"
    schema = {**_closed(copy.deepcopy(content[media_type]["schema"])), "components": COMPONENTS}
    errors = sorted(f"{'/'.join(map(str, e.absolute_path)) or 'the answer'}: {e.message}"
                    for e in Draft202012Validator(schema).iter_errors(response.json()))
    assert not errors, f"{where}: not the described shape: {errors}"


class Kept:
    """The answers of one area, by a name the chat UI's tests ask for them by."""

    def __init__(self, name: str):
        self.file, self.answers = Path(__file__).parent / f"{name}_answers.json", {}

    def keep(self, name: str, response, **same_every_run) -> None:
        """``same_every_run``: members whose value differs from run to run (an id, a moment), and the value kept."""
        body = response.json() if response.content else None
        for member, value in same_every_run.items():
            holder = body["params"] if member == "ref" else body
            assert member in holder, f"{name}: no {member} in the answer"
            holder[member] = value
        assert name not in self.answers
        self.answers[name] = {"status": response.status_code, "media_type": response.headers.get("content-type", "").split(";")[0] or None,
                              "body": body}

    def check(self) -> None:
        text = json.dumps(self.answers, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        if os.environ.get("SUVERYN_WRITE_ANSWERS"):
            self.file.write_text(text, encoding="utf-8")
        assert self.file.exists() and self.file.read_text(encoding="utf-8") == text, (
            f"{self.file.name} isn't what the gateway answers today: SUVERYN_WRITE_ANSWERS=1 uv run pytest "
            "packages/api-gateway/tests, and commit the file with the change")
