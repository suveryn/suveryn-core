"""The gateway's description of itself (suveryn-tracker#159, #161): kept as a file the chat UI's code is to be
generated from, so it is what the gateway describes today, and every operation has a name and a group that follow
the naming convention."""

import json

from suveryn_api_gateway import description

# The groups (the convention's thirteen). A new group is added here on purpose, in the change that adds it.
GROUPS = {"auth", "answers", "models", "cases", "settings", "playbooks", "documents", "conversations", "users", "usage",
          "backups", "clock", "status"}
READS = ("get_", "list_", "preview_")


def operations() -> list[tuple[str, str, dict]]:
    described = json.loads(description.FILE.read_text(encoding="utf-8"))
    return [(method.upper(), path, op) for path, by_method in described["paths"].items() for method, op in by_method.items()]


def test_the_file_is_what_the_gateway_describes_today():
    # a change to a route or a model changes openapi.json in the same PR:
    #   uv run python -m suveryn_api_gateway.description
    assert description.FILE.read_text(encoding="utf-8") == description.as_text(description.describe()), (
        "packages/api-gateway/openapi.json is out of date: run `uv run python -m suveryn_api_gateway.description`")
    assert description.main(["--check"]) == 0


def test_every_operation_has_a_name_of_its_own_and_one_group():
    ops = operations()
    names = [op["operationId"] for _, _, op in ops]
    assert len(set(names)) == len(names), sorted(name for name in set(names) if names.count(name) > 1)
    for method, path, op in ops:
        name = op["operationId"]
        # its function's name: lower case words, and no path in it (FastAPI's default id carries the path and method)
        assert name.replace("_", "").isalnum() and name == name.lower() and "__" not in name and "_v1_" not in name, f"{method} {path}: {name}"
        assert len(op.get("tags", [])) == 1 and op["tags"][0] in GROUPS, f"{method} {path}: {op.get('tags')}"
    assert {op["tags"][0] for _, _, op in ops} == GROUPS  # and no group listed here that the gateway no longer has


def test_a_name_starts_with_a_verb_that_fits_what_the_operation_does():
    # the convention: a read is get_, list_ or preview_, and nothing else is; a change of some fields is update_
    for method, path, op in operations():
        name = op["operationId"]
        assert (method == "GET") == name.startswith(READS), f"{method} {path}: {name}"
        if method == "PATCH":
            assert name.startswith("update_"), f"{method} {path}: {name}"
        if name.startswith(("create_", "start_")):
            assert method == "POST", f"{method} {path}: {name}"
        if name.startswith("delete_"):
            assert method == "DELETE", f"{method} {path}: {name}"
        if method == "DELETE":
            assert name.startswith(("delete_", "remove_", "cancel_")), f"{method} {path}: {name}"
        assert "_" in name, f"{method} {path}: {name} (a verb, then what it acts on)"
        # one word for one thing (names.md): a picture, an upload
        assert "avatar" not in name and "_job" not in name, f"{method} {path}: {name}"


def test_every_route_of_the_gateway_is_in_the_description():
    # a module can hold routers of several groups (routes/cases.py); one left out of its `routers` would drop its
    # operations from the gateway without a word. And a route is left out of the description only on purpose.
    import ast
    import pathlib

    routes = pathlib.Path(description.__file__).parent / "routes"
    declared, hidden = 0, []
    for module in routes.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "patch", "delete"):
                    if any(k.arg == "include_in_schema" for k in d.keywords):
                        hidden.append(node.name)
                    else:
                        declared += 1
    assert declared == len(operations()), f"{declared} routes are declared in routes/, {len(operations())} are described"
    # the two sign-in redirects: a browser follows them, no screen's code calls them
    assert sorted(hidden) == ["callback", "login"], f"routes left out of the description: {sorted(hidden)}"


# The groups whose operations are described strictly (suveryn-tracker#159, one area at a time): what they answer,
# and every refusal. The chat UI's code for them is generated (packages/chat-ui/src/generated). A group is added
# here in the change that moves it.
STRICT = {"clock"}
PROBLEM = {"$ref": "#/components/schemas/ProblemDetails"}


def strict_operations() -> list[tuple[str, str, dict]]:
    return [(method, path, op) for method, path, op in operations() if op["tags"][0] in STRICT]


def test_a_strict_operation_describes_every_refusal_in_the_one_shape():
    from suveryn_api_gateway import problems

    assert strict_operations()
    for method, path, op in operations():
        refusals = {int(status): r for status, r in op["responses"].items() if int(status) >= 400}
        ours = [s for s, r in refusals.items() if r.get("content", {}).get(problems.MEDIA_TYPE, {}).get("schema") == PROBLEM]
        if op["tags"][0] not in STRICT:
            assert not ours, f"{method} {path} describes its refusals: add its group to STRICT"
            continue
        assert sorted(ours) == sorted(refusals), f"{method} {path}: a refusal in another shape or media type"
        assert all(list(r["content"]) == [problems.MEDIA_TYPE] for r in refusals.values()), f"{method} {path}"
        assert set(problems.EVERY_OPERATION) <= set(refusals), f"{method} {path}: {sorted(refusals)}"


def test_a_strict_operation_describes_the_status_of_every_code_its_own_code_raises_and_no_other():
    import ast
    import pathlib

    from suveryn_api_gateway import problems
    from suveryn_harness.messages import CODES

    # what each function of routes/ raises itself, and which other functions of routes/ it calls: a refusal is
    # often raised by a helper (routes/common.py), and counts for every operation that reaches it
    own_codes: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    for module in (pathlib.Path(description.__file__).parent / "routes").glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                inside = [c for c in ast.walk(node) if isinstance(c, ast.Call)]
                own_codes.setdefault(node.name, set()).update(c.args[0].value for c in inside if getattr(c.func, "id", "") == "Problem")
                calls.setdefault(node.name, set()).update(getattr(c.func, "id", None) or getattr(c.func, "attr", "") for c in inside)

    def reached(name: str, seen: set[str]) -> set[str]:
        if name in seen or name not in own_codes:
            return set()
        seen.add(name)
        return own_codes[name].union(*(reached(callee, seen) for callee in calls[name]))

    raised = {name: {CODES[code].status for code in reached(name, set())} for name in own_codes}
    assert 403 in raised["create_clock_request"] and 403 not in raised["get_clock"]  # through admin_or_403, a helper
    for method, path, op in strict_operations():
        own = {int(s) for s in op["responses"] if int(s) >= 400} - set(problems.EVERY_OPERATION)
        takes_input = bool(op.get("parameters") or op.get("requestBody"))  # FastAPI checks it: 422, as request.invalid
        expected = (raised[op["operationId"]] | ({422} if takes_input else set())) - set(problems.EVERY_OPERATION)
        assert own == expected, f"{method} {path}: describes {sorted(own)}, raises {sorted(expected)}"


def test_a_strict_operation_leaves_nothing_undescribed():
    # "any object", "anything": what generated code can only call unknown
    schemas = json.loads(description.FILE.read_text(encoding="utf-8"))["components"]["schemas"]

    def loose(schema, seen, where):
        if isinstance(schema, list):
            return [x for i, s in enumerate(schema) for x in loose(s, seen, where)]
        if not isinstance(schema, dict):
            return []
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[1]
            if name in seen:
                return []
            return loose(schemas[name], seen | {name}, name)
        found = []
        typed = any(k in schema for k in ("type", "anyOf", "oneOf", "allOf", "enum", "const"))
        if not typed or schema.get("additionalProperties") is True or (schema.get("type") == "object" and "properties" not in schema
                                                                       and not isinstance(schema.get("additionalProperties"), dict)):
            found.append(where)
        for key in ("properties", "additionalProperties", "items", "anyOf", "oneOf", "allOf"):
            value = schema.get(key)
            for child in (value.values() if key == "properties" and isinstance(value, dict) else [value]):
                found += loose(child, seen, where)
        return found

    for method, path, op in strict_operations():
        assert any(str(s).startswith("2") for s in op["responses"])
        parts = [op.get("requestBody", {}), *op["responses"].values()]
        schemas_used = [c["schema"] for part in parts for c in part.get("content", {}).values()]
        schemas_used += [p["schema"] for p in op.get("parameters", [])]
        assert not loose(schemas_used, frozenset(), f"{method} {path}"), f"{method} {path}: {loose(schemas_used, frozenset(), path)}"
        for status, r in op["responses"].items():
            assert status == "204" or r.get("content"), f"{method} {path}: {status} has no described body"


class _Answer:
    def __init__(self, status, body, media_type="application/json"):
        self.status_code, self._body, self.headers = status, body, {"content-type": media_type}
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        return self._body


def test_the_check_of_an_answer_against_the_description_fails_when_they_differ():
    import pytest
    from described import answer_is_described

    good = {"id": "ab", "pending": False, "ok": False, "moved_ms": None, "failure": {"kind": "refused", "code": "clock.synced", "params": {}}}
    answer_is_described(_Answer(200, good), "GET", "/v1/admin/clock/{rid}")
    problem = {"type": "urn:suveryn:problem:clock.busy", "title": "t", "status": 409, "detail": "d", "kind": "refused", "code": "clock.busy", "params": {}}
    answer_is_described(_Answer(409, problem, "application/problem+json; charset=utf-8"), "POST", "/v1/admin/clock")
    for answer, method, path, says in (
        (_Answer(418, good), "GET", "/v1/admin/clock/{rid}", "not a status"),
        (_Answer(409, problem), "POST", "/v1/admin/clock", "sent as"),                                   # the wrong media type
        (_Answer(200, {k: v for k, v in good.items() if k != "id"}), "GET", "/v1/admin/clock/{rid}", "'id' is a required"),
        (_Answer(200, {**good, "moved_ms": "far"}), "GET", "/v1/admin/clock/{rid}", "moved_ms"),          # another type
        (_Answer(200, {**good, "note": "x"}), "GET", "/v1/admin/clock/{rid}", "'note'"),                  # a member it doesn't name
        (_Answer(200, {**good, "failure": {"kind": "odd", "code": "x", "params": {}}}), "GET", "/v1/admin/clock/{rid}", "failure"),
        (_Answer(200, {**good, "failure": {"kind": "refused", "code": "x", "params": {}, "more": 1}}), "GET", "/v1/admin/clock/{rid}", "'more'"),
        (_Answer(204, {"now_ms": 1}), "POST", "/v1/clock", "a body where"),
        (_Answer(200, {"now_ms": "now"}), "GET", "/v1/clock", "now_ms"),
    ):
        with pytest.raises(AssertionError, match=says):
            answer_is_described(answer, method, path)
