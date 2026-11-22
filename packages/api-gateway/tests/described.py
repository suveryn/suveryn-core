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
    if content[media_type]["schema"] == {"type": "string", "format": "binary"}:
        return  # a file as it is (a picture): its media type is what is described
    schema = {**_closed(copy.deepcopy(content[media_type]["schema"])), "components": COMPONENTS}
    errors = sorted(f"{'/'.join(map(str, e.absolute_path)) or 'the answer'}: {e.message}"
                    for e in Draft202012Validator(schema).iter_errors(response.json()))
    assert not errors, f"{where}: not the described shape: {errors}"


class Kept:
    """The answers of one area, by a name the chat UI's tests ask for them by."""

    def __init__(self, name: str):
        self.file, self.answers = Path(__file__).parent / f"{name}_answers.json", {}

    def keep(self, name: str, response, tidy=None, **same_every_run) -> None:
        """``same_every_run``: members whose value differs from run to run (an id, a moment), and the value kept.
        ``tidy``: a function that does the same deeper in the body."""
        json_sent = "json" in response.headers.get("content-type", "")
        body = response.json() if response.content and json_sent else None  # a file's own bytes are not kept
        if tidy:
            tidy(body)
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


class Checked:
    """The answers of one area's test, each checked against the description as it is given, and kept by name where
    the chat UI's tests need it."""

    def __init__(self, client, area: str):
        self.client, self.area, self.kept, self.seen = client, area, Kept(area), set()

    def __call__(self, method: str, path: str, expected: int, at: str | None = None, keep: str | None = None,
                 same_every_run: dict | None = None, tidy=None, **request):
        """``path`` as the description writes it; ``at``: the address asked, where it differs (an id, a query)."""
        r = self.client.request(method, at or path, **request)
        assert r.status_code == expected, f"{method} {at or path}: {r.status_code} {r.text}"
        answer_is_described(r, method, path)
        self.seen.add((method, path, expected))
        if keep:
            self.kept.keep(keep, r, tidy, **(same_every_run or {}))
        return r

    def not_seen(self) -> set[tuple[str, str, int]]:
        """Every status the description gives the area's operations that this test didn't see answered."""
        described = {(method.upper(), path, int(status)) for path, by_method in DESCRIBED["paths"].items()
                     for method, op in by_method.items() if op["tags"] == [self.area] for status in op["responses"]}
        return described - self.seen


def same_every_run(known: dict[str, str] | None = None, moments: tuple[str, ...] = ()):
    """A ``tidy`` for ``Kept``: this run's ids, moments and clock readings, wherever they are in an answer, made
    the same every run. An id (a UUID, written with or without its dashes) becomes a fixed one, in the order the ids
    are first seen (``known``: ones that keep a value of their own); a member named ``at`` or ending in ``_at``, or
    one of ``moments``, becomes one moment, as text or as a number, whichever it was."""
    import re

    ids = dict(known or {})
    an_id = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$")

    def fixed(value: str) -> str:
        if not an_id.match(value):
            return value
        new = ids.setdefault(value.replace("-", ""), f"00000000-0000-4000-8000-{len(ids) + 1:012x}")
        return new if "-" in value else new.replace("-", "")

    def same(body):
        if isinstance(body, list):
            return [same(item) for item in body]
        if not isinstance(body, dict):
            return fixed(body) if isinstance(body, str) else body
        out = {}
        for key, value in body.items():
            if (key == "at" or key.endswith("_at") or key in moments) and isinstance(value, (str, int, float)) and not isinstance(value, bool):
                out[fixed(key)] = "2026-11-23T09:00:00Z" if isinstance(value, str) else 1795510800.0
            else:
                out[fixed(key)] = same(value)
        return out

    def tidy(body) -> None:  # in place, as ``Kept`` asks
        new = same(body)
        if isinstance(body, dict):
            body.clear()
            body.update(new)
        else:
            body[:] = new

    tidy.ids = ids
    return tidy
