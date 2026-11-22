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
STRICT = {"answers", "auth", "backups", "cases", "clock", "conversations", "documents", "models", "playbooks", "settings", "status", "usage", "users"}
PROBLEM = {"$ref": "#/components/schemas/ProblemDetails"}


# An answer with a failing status that is the answer asked for, not a refusal: /health says its state with 503
# while the model server isn't ready, and its body is the same as with 200. Named here on purpose.
STATES = {("GET", "/health", 503)}


# A refusal the route's own code never raises: the gateway gives it before the route is reached, by the request's size
# or by how often a person asks, or it answers for sign-in when that can't say who is there (all app.py). Each as
# that file says it: its code, its status where that isn't the code's own, and the file.
# The size limit is on every PUT under a conversation, so on its pin too; an upload must say its size, and keep to it.
BEFORE = {("PUT", "/v1/conversations/{conversation_id}"): [("conversation.too_long", None, "app.py")],
          ("PUT", "/v1/conversations/{conversation_id}/pin"): [("conversation.too_long", None, "app.py")],
          ("POST", "/v1/documents"): [("request.invalid", 411, "app.py"), ("upload.too_large", None, "app.py")],
          ("POST", "/v1/chat"): [("request.too_many", None, "app.py")],  # the limit on asking, per person
          ("GET", "/auth/me"): [("auth.unavailable", None, "app.py")]}  # the sign-in service can't be asked (``AuthUnavailable``)
# An upload is refused by document handling itself (suveryn-rag, ``UploadRejected``: not a file it reads, empty, too
# large, too many waiting): codes of the registry said outside the gateway, read here from where they are raised.
UPLOAD = ("POST", "/v1/documents")


# Outside /v1 an operation refuses only what its own code does: who is signed in says so when nobody is.
OUTSIDE = {("GET", "/auth/me"): (401, 503)}


def strict_operations() -> list[tuple[str, str, dict]]:
    return [(method, path, op) for method, path, op in operations() if op["tags"][0] in STRICT]


def test_a_strict_operation_describes_every_refusal_in_the_one_shape():
    from suveryn_api_gateway import problems

    assert strict_operations()
    for method, path, op in operations():
        refusals = {int(status): r for status, r in op["responses"].items()
                    if int(status) >= 400 and (method, path, int(status)) not in STATES}
        ours = [s for s, r in refusals.items() if r.get("content", {}).get(problems.MEDIA_TYPE, {}).get("schema") == PROBLEM]
        if op["tags"][0] not in STRICT:
            assert not ours, f"{method} {path} describes its refusals: add its group to STRICT"
            continue
        assert sorted(ours) == sorted(refusals), f"{method} {path}: a refusal in another shape or media type"
        assert all(list(r["content"]) == [problems.MEDIA_TYPE] for r in refusals.values()), f"{method} {path}"
        # sign-in guards /v1 and nothing else: outside it only what nobody planned for can take the answer's place
        if path.startswith("/v1/"):
            assert set(problems.EVERY_OPERATION) <= set(refusals), f"{method} {path}: {sorted(refusals)}"
        else:  # and what the operation's own code refuses (the next test holds that to the code)
            assert 500 in refusals and not {401, 503} & set(refusals) - set(OUTSIDE.get((method, path), ())), f"{method} {path}: {sorted(refusals)}"
    described = {(method, path, int(status)) for method, path, op in strict_operations() for status in op["responses"]}
    assert STATES <= described, f"named as a state, and not described: {sorted(STATES - described)}"


def test_a_strict_operation_describes_the_status_of_every_code_its_own_code_raises_and_no_other():
    import ast
    import pathlib
    import re

    from suveryn_api_gateway import problems
    from suveryn_harness.messages import CODES

    # what each function of routes/ raises itself, and which other functions of routes/ it calls: a refusal is
    # often raised by a helper (routes/common.py), and counts for every operation that reaches it. The accounts
    # (accounts.py, Keycloak's answers as codes) refuse for themselves outside routes/: a route reaches them as
    # ``accounts.<method>``, and they are kept under that name, apart from the routes' own functions.
    own_codes: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    package = pathlib.Path(description.__file__).parent

    def read(module: pathlib.Path, prefix: str) -> None:
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                name, inside = prefix + node.name, [c for c in ast.walk(node) if isinstance(c, ast.Call)]
                own_codes.setdefault(name, set()).update(c.args[0].value for c in inside if getattr(c.func, "id", "") == "Problem")
                # called, or handed to something that calls it (``run_in_threadpool(leave_key, …)``)
                calls.setdefault(name, set()).update(prefix + n.id for n in ast.walk(node) if isinstance(n, ast.Name))
                attributes = [n for n in ast.walk(node) if isinstance(n, ast.Attribute)]
                calls[name].update(prefix + a.attr for a in attributes)
                calls[name].update("accounts." + a.attr for a in attributes if getattr(a.value, "id", "") in ("accounts", "self") and (prefix or a.value.id == "accounts"))

    for module in (package / "routes").glob("*.py"):
        read(module, "")
    read(package / "accounts.py", "accounts.")

    def reached(name: str, seen: set[str]) -> set[str]:
        if name in seen or name not in own_codes:
            return set()
        seen.add(name)
        return own_codes[name].union(*(reached(callee, seen) for callee in calls[name]))

    raised = {name: {CODES[code].status for code in reached(name, set())} for name in own_codes}
    assert 403 in raised["create_clock_request"] and 403 not in raised["get_clock"]  # through admin_or_403, a helper
    for method, path, op in strict_operations():
        every = set(problems.EVERY_OPERATION) if path.startswith("/v1/") else {500}  # sign-in guards /v1 and nothing else
        own = {int(s) for s in op["responses"] if int(s) >= 400 and (method, path, int(s)) not in STATES} - every
        # FastAPI checks what it reads itself, parameters and a JSON body: 422, as request.invalid. A body the route
        # reads as it is (a key file) is the route's own to refuse.
        takes_input = bool(op.get("parameters") or "application/json" in op.get("requestBody", {}).get("content", {}))
        expected = (raised[op["operationId"]] | ({422} if takes_input else set())) - every
        for code, status, file in BEFORE.get((method, path), []):
            assert f'"{code}"' in (package / file).read_text(encoding="utf-8"), f"{code} isn't said in {file}"
            expected.add(status or CODES[code].status)
        if (method, path) == UPLOAD:
            reader = (package.parents[2] / "rag" / "src" / "suveryn_rag" / "service.py").read_text(encoding="utf-8")
            rejected = set(re.findall(r'UploadRejected\((?:[^()]|\([^()]*\))*?"(upload\.[a-z_]+)"', reader))
            assert len(rejected) > 5, sorted(rejected)
            expected |= {CODES[code].status for code in rejected} - every
        assert own == expected, f"{method} {path}: describes {sorted(own)}, raises {sorted(expected)}"


# A shape of a strict area that is still "any object", named with what it is: describing them is suveryn-tracker#250.
LATER = {"CaseEvent.detail": "what each line of the access log records (its actions and their details), for every area that writes one",
         "Conversation.turns": "what a turn holds (an answer's citations and calculations, a playbook's turns): in a conversation the chat UI saved",
         "SavedTurn": "the same, as the chat UI saves it",
         "Turn.meta": "what a turn of a run's thread holds (its kind and facts, turn_kinds.json): written by the server",
         "RunFact.computed": "how a value was worked out (a term, a share: suveryn_harness.terms)",
         "AnswerContent": "what rebuilds a saved answer's file, the chat UI's own data (an answer, its sources and checks)",
         "SavedCitation": "the same", "SavedCitation.source": "the same", "DocumentContent.content": "the same, as it is read back"}


# What is "any object" by its nature, and stays so.
ANY = {"ChatRequest.json_schema": "a JSON Schema the answer must have the shape of (a playbook's read): any object is what a schema is"}


def shape(content: dict) -> dict:
    """What one media type of an answer or a body holds: its schema, or for a stream of events what one event is."""
    assert ("schema" in content) != ("itemSchema" in content), content
    return content.get("schema") or content["itemSchema"]


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
            if key == "properties" and isinstance(value, dict):  # a member is named: `CaseEvent.detail`
                for member, child in value.items():
                    found += loose(child, seen, f"{where}.{member}")
            else:
                found += loose(value, seen, where)
        return found

    for method, path, op in strict_operations():
        assert any(str(s).startswith("2") for s in op["responses"])
        parts = [op.get("requestBody", {}), *op["responses"].values()]
        schemas_used = [shape(c) for part in parts for c in part.get("content", {}).values()]
        schemas_used += [p["schema"] for p in op.get("parameters", [])]
        left = set(loose(schemas_used, frozenset(), f"{method} {path}")) - set(LATER) - set(ANY)
        assert not left, f"{method} {path}: {sorted(left)}"
        for status, r in op["responses"].items():
            # nothing to read: done (204), accepted and answered elsewhere later (202), or unchanged (304)
            assert status in ("202", "204", "304") or r.get("content"), f"{method} {path}: {status} has no described body"


# A member an answer doesn't always carry, by the schema's name: named here on purpose.
SOMETIMES = {("ProblemDetails", "errors"),  # with request.invalid only
             # where a document came from: only what is known of it (routes/documents.py, ``Provenance``)
             *(("Provenance", member) for member in ("playbook", "version", "run", "conversation", "message", "noticed", "confirmed", "withdrawn"))}


def test_a_strict_operation_describes_every_member_of_an_answer_as_always_there():
    # a model's member with a default is always sent, but described as optional unless the model extends
    # description.Answer (or, outside the gateway, carries its setting): generated code would call it optional
    schemas = json.loads(description.FILE.read_text(encoding="utf-8"))["components"]["schemas"]

    def named(schema, seen):
        if isinstance(schema, list):
            return set().union(*(named(s, seen) for s in schema)) if schema else set()
        if not isinstance(schema, dict):
            return set()
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[1]
            return set() if name in seen else {name} | named(schemas[name], seen | {name})
        return named([v for v in schema.values() if isinstance(v, (dict, list))], seen)

    answers = set()
    for _, _, op in strict_operations():
        answers |= named([shape(c) for r in op["responses"].values() for c in r.get("content", {}).values()], frozenset())
    assert {"SetAnswer", "UsageReport", "ModelInfo", "ProblemDetails"} <= answers
    optional = {(name, member) for name in answers for member in schemas[name].get("properties", {})
                if member not in schemas[name].get("required", [])}
    assert optional == SOMETIMES, f"described as not always there: {sorted(optional - SOMETIMES)}"


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
